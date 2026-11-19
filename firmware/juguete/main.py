# ============================================================
# main.py · EP07 Juguete interactivo conectado a Supabase (MicroPython)
# Autor: Javier Solano (JS)
#
# Placa: Raspberry Pi Pico W (también funciona en un ESP32 cambiando los pines).
# Copiar a la placa: main.py, juego.py, salidas.py, supabase_micro.py y
# config.json (a partir de config.example.json; NO se sube a Git).
#
# Contrato con la base (README_BASE_DATOS.md, "Contrato para los dispositivos"):
#   * Inicia sesión con la cuenta del controlador y busca su id por código.
#   * Lee configuracion (juguete_tiempo_ronda_s, juguete_volumen) al arrancar y
#     cada 2 s. La app la cambia desde el panel del juguete (HU-31).
#   * Llama a registrar_senal cada 5 s, y enseguida si cambia la ronda, con
#     {"boton_activo", "ronda", "aciertos", ...}: la app ilumina ese botón.
#   * Cada acierto se inserta en eventos como 'juguete_acierto'
#     (valor = segundos que tardó el bebé, descripcion = botón).
#   * Atiende los comandos probar_luz y probar_buzzer (HU-07).
#
# Hilos: el JUEGO corre en el segundo núcleo (_thread) y solo toca GPIO y PWM;
# la RED corre en el hilo principal. En la Pico W el Wi-Fi debe usarse desde el
# núcleo principal, y así una petición HTTP lenta nunca traba los botones.
# Sin internet el juego sigue; los aciertos se guardan y se envían después.
# ============================================================

import json
import time

import network

from juego import Juego, ticks_diff, ticks_ms
from supabase_micro import ClienteSupabase

SEGUNDOS_RED = 2          # sondeo de configuracion y comandos
SEGUNDOS_SENAL = 5        # contrato: señal de vida cada 5 s
MS_MINIMO_ENTRE_SENALES = 1000
COLUMNAS_CONFIG = "juguete_tiempo_ronda_s,juguete_volumen"


def cargar_config():
    with open("config.json") as f:
        return json.load(f)


def crear_hardware(cfg):
    from salidas import HardwareJuguete

    return HardwareJuguete(cfg.get("pines_botones", [10, 11, 12, 13, 14]),
                           cfg.get("pines_leds", [16, 17, 18, 19, 20]),
                           cfg.get("pin_buzzer", 15))


def conectar_wifi(cfg, espera_s=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(cfg["wifi_ssid"], cfg["wifi_clave"])
        inicio = time.time()
        while not wlan.isconnected() and time.time() - inicio < espera_s:
            time.sleep(0.5)
    return wlan.isconnected()


def sincronizar_hora():
    try:
        import ntptime

        ntptime.settime()   # UTC
        return True
    except Exception:
        return False


def iso_utc(segundos_epoch):
    """Fecha ISO en UTC, o None si el reloj nunca se sincronizó (mejor que una fecha falsa)."""
    a = time.gmtime(int(segundos_epoch))
    if a[0] < 2024:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % a[:6]


class Agente:
    """Red: configuración, comandos, aciertos y señal de vida."""

    def __init__(self, cfg, juego):
        self.cfg = cfg
        self.juego = juego
        self.cliente = ClienteSupabase(cfg["supabase_url"], cfg["supabase_anon_key"],
                                       cfg["correo_controlador"], cfg["clave_controlador"])
        self.dispositivo_id = None
        self._t_ultima_senal = None
        self._version_enviada = -1

    def preparar(self):
        sincronizar_hora()
        self.cliente.iniciar_sesion()
        self.dispositivo_id = self.cliente.id_dispositivo(self.cfg["codigo_dispositivo"])

    def aplicar_config(self):
        fila = self.cliente.leer_config(self.dispositivo_id, COLUMNAS_CONFIG)
        if fila:
            self.juego.aplicar_config(fila["juguete_tiempo_ronda_s"], fila["juguete_volumen"])

    def atender_comandos(self):
        for c in self.cliente.comandos_pendientes(self.dispositivo_id):
            ahora = iso_utc(time.time())
            if c["tipo"] == "probar_luz":
                self.juego.probar_luz(2000)
                self.cliente.marcar_comando(c["id"], "ejecutado", None, ahora)
            elif c["tipo"] == "probar_buzzer":
                self.juego.probar_buzzer()
                self.cliente.marcar_comando(c["id"], "ejecutado", None, ahora)
            else:
                self.cliente.marcar_comando(c["id"], "fallido",
                                            "El juguete no admite la orden %s" % c["tipo"], ahora)

    def enviar_aciertos(self):
        lista = self.juego.tomar_aciertos()
        for i, a in enumerate(lista):
            try:
                self.cliente.insertar_evento(
                    self.dispositivo_id, "juguete_acierto", valor=a["reaccion_s"], unidad="s",
                    descripcion="Acierto en el botón %d" % a["boton"], ocurrido_en=iso_utc(a["epoch"]))
            except Exception:
                self.juego.devolver_aciertos(lista[i:])   # se reintenta en la siguiente vuelta
                raise

    def senal(self, forzar=False):
        ahora = ticks_ms()
        version = self.juego.version
        vencida = self._t_ultima_senal is None or ticks_diff(ahora, self._t_ultima_senal) >= SEGUNDOS_SENAL * 1000
        cambio = version != self._version_enviada and (
            self._t_ultima_senal is None or ticks_diff(ahora, self._t_ultima_senal) >= MS_MINIMO_ENTRE_SENALES)
        if forzar or vencida or cambio:
            self._t_ultima_senal = ahora   # antes de enviar: sin red, no se reintenta en ráfaga
            self.cliente.registrar_senal(self.dispositivo_id, self.juego.lectura())
            self._version_enviada = version

    def vuelta(self):
        """Una vuelta completa del ciclo de red."""
        if self.dispositivo_id is None:
            self.preparar()
        self.aplicar_config()
        self.atender_comandos()
        self.enviar_aciertos()
        self.senal()


def bucle_juego(juego, hw, estado):
    """Segundo núcleo: botones, LEDs y buzzer. Nunca toca la red."""
    try:
        while estado["activo"]:
            juego.actualizar(hw.leer_pulsaciones(ticks_ms()))
            time.sleep_ms(5)
    finally:
        hw.apagar()


def principal():
    cfg = cargar_config()
    hw = crear_hardware(cfg)
    juego = Juego(hw)
    estado = {"activo": True}

    try:
        import _thread

        _thread.start_new_thread(bucle_juego, (juego, hw, estado))
        en_hilo = True
    except ImportError:
        en_hilo = False   # Sin hilos: la red se atiende en el mismo bucle (el juego se pausa un momento).

    conectar_wifi(cfg)
    agente = Agente(cfg, juego)
    t_red = ticks_ms()
    try:
        while True:
            if not en_hilo:
                juego.actualizar(hw.leer_pulsaciones(ticks_ms()))
            # La señal sale apenas cambia la ronda; el resto, cada SEGUNDOS_RED.
            try:
                if ticks_diff(ticks_ms(), t_red) >= SEGUNDOS_RED * 1000:
                    t_red = ticks_ms()
                    if not network.WLAN(network.STA_IF).isconnected():
                        conectar_wifi(cfg)
                    agente.vuelta()
                elif agente.dispositivo_id is not None:
                    agente.senal()
            except Exception as e:  # La red nunca debe tumbar el juego.
                print("red:", type(e).__name__, str(e)[:80])
            time.sleep_ms(5 if not en_hilo else 50)
    finally:
        estado["activo"] = False
        time.sleep_ms(50)
        hw.apagar()   # pase lo que pase, LEDs apagados y buzzer en silencio


if __name__ == "__main__":
    principal()
