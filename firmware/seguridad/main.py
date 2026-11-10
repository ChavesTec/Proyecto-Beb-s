# ============================================================
# main.py · EP06 Aparato de seguridad conectado a Supabase (MicroPython)
#
# Placa: Raspberry Pi Pico W (MicroPython 1.23 o superior) con un sensor
# ultrasónico HC-SR04 y una cámara OV7670 sin FIFO (conexiones en
# ultrasonico.py y camara.py).
#
# Copiar a la placa: main.py, camara.py, ultrasonico.py, imagen.py,
# vigilancia.py, ../comun/supabase_micro.py y config.json (a partir de
# config.example.json; NO se sube a Git).
#
# Contrato con la base (README_BASE_DATOS.md, "Contrato para los dispositivos"):
#   * Inicia sesión con la cuenta del controlador y busca su id por código.
#   * Lee configuracion (seguridad_armada, seguridad_intervalo_foto_s) al
#     arrancar y cada pocos segundos. La app y pg_cron (horarios) la cambian.
#   * Llama a registrar_senal cada ~5 s con su estado como ultima_lectura.
#   * Armada: cada presencia nueva es un evento 'presencia'; la foto de
#     evidencia (PNG 154x120) se sube a capturas/<dispositivo_id>/ y su ruta
#     va en foto_path. El trigger crea la captura y la alerta (CA-26.2).
#   * Atiende el comando tomar_foto; cualquier otro se marca fallido.
#   * Sin red, los eventos y fotos esperan en la flash y se reenvían con su
#     hora original (RNF-17).
#
# Todo corre en un solo bucle: el sensor se lee cada 0,5 s y la red se
# atiende cada 2 s. La conexión Wi-Fi se reintenta sin bloquear el sensor.
# ============================================================

import json
import time

try:
    import gc
except ImportError:  # pragma: no cover
    gc = None

import network

from imagen import escribir_png, tamano_png
from supabase_micro import ClienteSupabase
from vigilancia import FUERA_DE_RANGO, Cola, Vigilancia, ticks_diff, ticks_ms

SEGUNDOS_RED = 2          # configuración, comandos y cola pendiente
VUELTAS_SENAL = 2         # señal de vida cada 2 vueltas de red (~4 s; contrato: 5 s)
MS_ENTRE_MEDICIONES = 500
ARCHIVO_ESTADO = "estado.json"
COLUMNAS_CONFIG = "seguridad_armada,seguridad_intervalo_foto_s"
TIPO_FOTO = "image/png"


def cargar_config():
    with open("config.json") as f:
        return json.load(f)


def cargar_estado():
    """Último armado conocido: si arranca sin red, sigue vigilando como antes."""
    try:
        with open(ARCHIVO_ESTADO) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def guardar_estado(vigilancia):
    with open(ARCHIVO_ESTADO, "w") as f:
        json.dump({"armada": vigilancia.armada, "intervalo_s": vigilancia.intervalo_s}, f)


def sincronizar_hora():
    try:
        import ntptime

        ntptime.settime()   # UTC
        return True
    except Exception:
        return False


_ultima_hora = [None, 0]     # [segundo ISO, contador dentro de ese segundo]


def ahora_iso():
    """Hora UTC con milisegundos. El reloj de la placa solo da segundos: los
    milisegundos son un contador para que dos eventos del mismo tipo en el mismo
    segundo (p. ej. una presencia y un tomar_foto) no choquen con la regla
    eventos_sin_duplicados (dispositivo_id, ocurrido_en, tipo) y uno se pierda."""
    a = time.gmtime()
    if a[0] < 2024:          # reloj sin sincronizar: mejor no enviar una fecha falsa
        return None
    segundo = "%04d-%02d-%02dT%02d:%02d:%02d" % a[:6]
    if segundo == _ultima_hora[0]:
        _ultima_hora[1] = min(_ultima_hora[1] + 1, 999)
    else:
        _ultima_hora[0], _ultima_hora[1] = segundo, 0
    return "%s.%03dZ" % (segundo, _ultima_hora[1])


def sello(ocurrido_en):
    """'2026-11-09T21:52:49.001Z' -> '20261109T215249001' (para el nombre del archivo)."""
    if not ocurrido_en:
        return "sinhora%d" % ticks_ms()
    return ocurrido_en.replace("-", "").replace(":", "").replace(".", "").rstrip("Z")


class Wifi:
    """Reconexión sin bloquear: pide conectar y sigue; revisa en la próxima vuelta."""

    def __init__(self, cfg, reintento_s=30):
        self.cfg = cfg
        self.reintento_s = reintento_s
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        self.ultimo_intento = None

    def conectado(self):
        if self.wlan.isconnected():
            return True
        if self.ultimo_intento is None or ticks_diff(ticks_ms(), self.ultimo_intento) > self.reintento_s * 1000:
            self.ultimo_intento = ticks_ms()
            try:
                self.wlan.connect(self.cfg["wifi_ssid"], self.cfg["wifi_clave"])
            except OSError as e:
                print("wifi:", e)
        return False


class Agente:
    """Une la vigilancia con la cámara, la cola en flash y Supabase."""

    def __init__(self, cfg, cliente, vigilancia, cola, camara=None, al_cambiar_config=None):
        self.cfg = cfg
        self.cliente = cliente
        self.vigilancia = vigilancia
        self.cola = cola
        self.camara = camara
        self.al_cambiar_config = al_cambiar_config
        self.byte_alto_primero = cfg.get("byte_alto_primero", True)
        self.dispositivo_id = None
        self.sensor_ok = None

    # ------------------------------------------------------------ base
    def preparar(self):
        sincronizar_hora()
        self.cliente.iniciar_sesion()
        self.dispositivo_id = self.cliente.id_dispositivo(self.cfg["codigo_dispositivo"])
        self.aplicar_config()   # CA-11.3: arranca con lo último guardado en la base

    def aplicar_config(self):
        fila = self.cliente.leer_config(self.dispositivo_id, COLUMNAS_CONFIG)
        if fila and self.vigilancia.aplicar_config(fila["seguridad_armada"], fila["seguridad_intervalo_foto_s"]):
            print("Seguridad", "ARMADA" if self.vigilancia.armada else "desarmada",
                  "· una foto cada", self.vigilancia.intervalo_s, "s")
            if self.al_cambiar_config:
                self.al_cambiar_config(self.vigilancia)

    # ------------------------------------------------------------ fotos
    def camara_lista(self):
        return self.camara is not None and self.camara.lista

    def tomar_foto(self, tipo, descripcion):
        """Captura, guarda en la cola y devuelve True. Si la cámara falla, el
        evento se encola igual, sin foto, y devuelve False."""
        ocurrido = ahora_iso()
        nombre = None
        if self.camara_lista():
            ancho, alto = self.camara.ancho, self.camara.alto
            if not self.cola.hacer_espacio(tamano_png(ancho, alto)):
                print("Flash llena: el evento se guarda sin foto")
            elif not self.camara.capturar():
                print("Error: la cámara no envió imagen (revisa VSYNC/PCLK/HREF/XCLK)")
            else:
                nombre = self.cola.nombre_foto(sello(ocurrido))
                with open(self.cola.carpeta + "/" + nombre, "wb") as f:
                    escribir_png(f, self.camara.frame, ancho, alto, self.byte_alto_primero)
                print("Foto guardada:", nombre)
        self.cola.agregar(tipo, ocurrido, descripcion, nombre)
        return nombre is not None

    def registrar_presencia(self, accion, distancia):
        descripcion = "Presencia a %d cm" % distancia
        if accion == "foto":
            self.tomar_foto("presencia", descripcion)
        elif accion == "evento":
            self.cola.agregar("presencia", ahora_iso(), descripcion)

    # ------------------------------------------------------------ comandos
    def atender_comandos(self):
        for c in self.cliente.comandos_pendientes(self.dispositivo_id):
            if c["tipo"] != "tomar_foto":
                self.cliente.marcar_comando(c["id"], "fallido",
                                            "La seguridad no admite la orden %s" % c["tipo"], ahora_iso())
            elif not self.vigilancia.armada:
                # Desarmada, la base descarta la presencia y la foto quedaría huérfana (CA-23.2).
                self.cliente.marcar_comando(c["id"], "fallido",
                                            "La seguridad está desarmada: ármela para guardar fotos.", ahora_iso())
            elif not self.tomar_foto("presencia", "Foto pedida desde la app"):
                self.cliente.marcar_comando(c["id"], "fallido",
                                            "La cámara no respondió; se registró el evento sin foto.", ahora_iso())
            else:
                self.enviar_pendientes()
                self.cliente.marcar_comando(c["id"], "ejecutado", "Foto tomada", ahora_iso())

    # ------------------------------------------------------------ cola
    def enviar_pendientes(self, maximo=3):
        """Sube fotos e inserta eventos en orden. Si algo falla, lanza la excepción
        y el elemento queda en la cola para la próxima vuelta."""
        enviados = 0
        while enviados < maximo:
            e = self.cola.primero()
            if e is None:
                break
            ruta_remota = None
            if e.get("foto"):
                ruta_remota = "%s/%s" % (self.dispositivo_id, e["foto"])
                if not e.get("subida"):
                    if gc:
                        gc.collect()
                    with open(self.cola.ruta(e), "rb") as f:
                        datos = f.read()
                    self.cliente.subir_archivo("capturas", ruta_remota, datos, TIPO_FOTO)
                    datos = None
                    self.cola.marcar_subida(e)
            evento = {"dispositivo_id": self.dispositivo_id, "tipo": e["tipo"],
                      "descripcion": e.get("descripcion"), "foto_path": ruta_remota}
            if e.get("ocurrido_en"):
                evento["ocurrido_en"] = e["ocurrido_en"]
            self.cliente.insertar_evento(evento)
            self.cola.quitar(e)
            enviados += 1
        return enviados

    # ------------------------------------------------------------ señal
    def lectura(self):
        d = self.vigilancia.ultima_distancia
        lectura = {
            "armada": self.vigilancia.armada,
            "camara": "lista" if self.camara_lista() else "sin_camara",
            "sensor": "sin_respuesta" if d is None else "ok",
            "presencia": self.vigilancia.en_presencia,
            "pendientes": len(self.cola),
        }
        if d is not None and d != FUERA_DE_RANGO:
            lectura["distancia_cm"] = round(d, 1)
        return lectura

    def senal(self):
        self.cliente.registrar_senal(self.dispositivo_id, self.lectura())

    def vuelta_red(self, contador):
        if self.dispositivo_id is None:
            self.preparar()
        self.aplicar_config()
        self.atender_comandos()
        if contador % VUELTAS_SENAL == 0:
            self.senal()
        self.enviar_pendientes()


def guardar_pruebas(camara):
    """Modo patrón de prueba: guarda el mismo cuadro con los dos órdenes de bytes
    (no se sube). El que muestre bien las barras de colores indica el valor de
    byte_alto_primero en config.json."""
    if not camara.capturar():
        print("Error: la cámara no envió imagen")
        return
    for nombre, alto_primero in (("prueba_alto_primero.png", True), ("prueba_bajo_primero.png", False)):
        with open(nombre, "wb") as f:
            escribir_png(f, camara.frame, camara.ancho, camara.alto, alto_primero)
    print("Guardadas prueba_alto_primero.png y prueba_bajo_primero.png: copie las dos a la PC y compárelas")


def principal():
    cfg = cargar_config()
    from ultrasonico import Ultrasonico

    sensor = Ultrasonico()
    camara = None
    patron = cfg.get("patron_de_prueba", False)
    try:
        from camara import Camara

        camara = Camara()
        camara.iniciar(patron)
        print("Cámara lista")
        if cfg.get("diagnostico", False):
            camara.diagnostico(patron)
    except Exception as e:
        print("La cámara falló, el sensor sigue funcionando sin ella:", e)

    vigilancia = Vigilancia(cfg.get("distancia_disparo_cm", 20))
    estado = cargar_estado()
    vigilancia.aplicar_config(estado.get("armada", False), estado.get("intervalo_s", 30))
    cola = Cola()
    cliente = ClienteSupabase(cfg["supabase_url"], cfg["supabase_anon_key"],
                              cfg["correo_controlador"], cfg["clave_controlador"])
    agente = Agente(cfg, cliente, vigilancia, cola, camara, guardar_estado)
    wifi = Wifi(cfg)
    print("Listo ·", "ARMADA" if vigilancia.armada else "desarmada", "·", len(cola), "pendiente(s)")

    ultima_red = None
    contador = 0
    while True:
        distancia = sensor.medir()
        if patron:
            if vigilancia.hay_presencia(distancia) and camara is not None and camara.lista:
                guardar_pruebas(camara)
                time.sleep(3)
        else:
            accion = vigilancia.al_medir(distancia)
            if accion:
                print("Presencia detectada a %d cm (%s)" % (distancia, accion))
                try:
                    agente.registrar_presencia(accion, distancia)
                except Exception as e:   # p. ej. error al escribir en la flash
                    print("presencia:", type(e).__name__, e)

        if ultima_red is None or ticks_diff(ticks_ms(), ultima_red) >= SEGUNDOS_RED * 1000:
            ultima_red = ticks_ms()
            if wifi.conectado():
                try:
                    agente.vuelta_red(contador)
                except Exception as e:  # La red nunca debe detener la vigilancia.
                    print("red:", type(e).__name__, str(e)[:80])
            contador += 1
        time.sleep_ms(MS_ENTRE_MEDICIONES)


if __name__ == "__main__":
    principal()
