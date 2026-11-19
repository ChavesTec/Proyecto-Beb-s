# ============================================================
# main.py · EP05 Móvil de luces LED conectado a Supabase (MicroPython)
#
# Placa: ESP32 (controlador C de la arquitectura) o Raspberry Pi Pico W.
# Copiar a la placa: main.py, luces.py, salidas.py, ../comun/supabase_micro.py y
# config.json (a partir de config.example.json; NO se sube a Git).
#
# Contrato con la base (README_BASE_DATOS.md, "Contrato para los dispositivos"):
#   * Inicia sesión con la cuenta del controlador y busca su id por código.
#   * Lee configuracion al arrancar (movil_encendido, movil_secuencia,
#     movil_velocidad) y la vuelve a leer cada pocos segundos.
#     La app de escritorio y pg_cron (horarios del móvil) escriben esa fila.
#   * Llama a registrar_senal cada 5 s con su estado como ultima_lectura.
#   * Atiende el comando probar_luz y lo marca ejecutado; cualquier otro
#     comando para el móvil se marca fallido con el motivo.
#
# Hilos (igual que el juguete): las LUCES corren en el segundo núcleo
# (_thread) y solo tocan los LEDs; la RED corre en el hilo principal. En la
# Pico W el Wi-Fi (CYW43/lwIP) debe usarse desde el núcleo principal: con la
# red en el segundo núcleo la placa perdía la señal al minuto o dos.
# Así una petición HTTP lenta tampoco traba las luces.
#
# Cada vuelta de red abre conexiones HTTPS nuevas (~30-40 KB de RAM cada una y
# un socket de lwIP que tarda en liberarse): por eso la vuelta es cada
# SEGUNDOS_RED, empieza con gc.collect() y el ahorro de energía del Wi-Fi se
# desactiva (cortaba la conexión).
#
# Sin contacto con Supabase durante MINUTOS_SIN_CONEXION, el móvil se apaga
# por seguridad (los horarios los aplica la base y, sin red, no llegaría la
# orden de apagar). Lo vigila el hilo de luces, aunque la red esté trabada.
# ============================================================

import json
import time

try:
    import gc
except ImportError:  # pragma: no cover
    gc = None

import network

from luces import MovilLed, ticks_diff, ticks_ms
from supabase_micro import ClienteSupabase

SEGUNDOS_RED = 5          # configuracion, comandos y señal de vida (contrato: cada 5 s)
MINUTOS_SIN_CONEXION = 10
# Pico W: desactiva el ahorro de energía del CYW43 (valor de la documentación
# de Raspberry Pi). En MicroPython reciente WLAN.PM_NONE hace lo mismo.
PM_SIN_AHORRO_PICO = 0xa11140


def liberar_memoria():
    if gc:
        gc.collect()


def cargar_config():
    with open("config.json") as f:
        return json.load(f)


def crear_salida(cfg):
    from salidas import SalidaNeoPixel, SalidaPWM

    if cfg.get("salida", "neopixel") == "pwm":
        return SalidaPWM(cfg.get("pines_pwm", [2, 3, 4, 5, 6, 7]), cfg.get("brillo_maximo", 80))
    return SalidaNeoPixel(cfg.get("pin_neopixel", 23), cfg.get("cantidad_leds", 16), cfg.get("brillo_maximo", 30))


def desactivar_ahorro_wifi(wlan):
    """El ahorro de energía del Wi-Fi corta la conexión de a ratos."""
    for valor in (getattr(network.WLAN, "PM_NONE", None), PM_SIN_AHORRO_PICO):
        if valor is None:
            continue
        try:
            wlan.config(pm=valor)
            return True
        except Exception:
            pass
    return False


def conectar_wifi(cfg, espera_s=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    desactivar_ahorro_wifi(wlan)
    if not wlan.isconnected():
        # Sin disconnect() previo, la Pico W puede quedarse trabada en un
        # intento anterior y no volver a conectar.
        try:
            wlan.disconnect()
        except Exception:
            pass
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


def ahora_iso():
    a = time.gmtime()
    if a[0] < 2024:          # reloj sin sincronizar: mejor no enviar una fecha falsa
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % a[:6]


class Agente:
    """Red (hilo principal): señal, configuración y comandos."""

    def __init__(self, cfg, movil):
        self.cfg = cfg
        self.movil = movil
        self.cliente = ClienteSupabase(cfg["supabase_url"], cfg["supabase_anon_key"],
                                       cfg["correo_controlador"], cfg["clave_controlador"])
        self.dispositivo_id = None
        self.ultimo_ok = ticks_ms()

    def preparar(self):
        sincronizar_hora()
        self.cliente.iniciar_sesion()
        self.dispositivo_id = self.cliente.id_dispositivo(self.cfg["codigo_dispositivo"])

    def aplicar_config(self):
        fila = self.cliente.leer_config(self.dispositivo_id)
        if fila:
            self.movil.aplicar_config(fila["movil_encendido"], fila["movil_secuencia"], fila["movil_velocidad"])

    def atender_comandos(self):
        for c in self.cliente.comandos_pendientes(self.dispositivo_id):
            if c["tipo"] == "probar_luz":
                self.movil.destello(2000)
                self.cliente.marcar_comando(c["id"], "ejecutado", None, ahora_iso())
            else:
                self.cliente.marcar_comando(c["id"], "fallido",
                                            "El móvil no admite la orden %s" % c["tipo"], ahora_iso())

    def senal(self):
        self.cliente.registrar_senal(self.dispositivo_id, self.movil.lectura())

    def vuelta(self):
        """Una vuelta de red. Si termina sin excepción, hubo contacto con la base."""
        liberar_memoria()
        if self.dispositivo_id is None:
            self.preparar()
        self.aplicar_config()   # CA-11.3 equivalente: arranca con el último estado guardado
        self.atender_comandos()
        self.senal()
        self.ultimo_ok = ticks_ms()


def revisar_conexion(movil, agente):
    if ticks_diff(ticks_ms(), agente.ultimo_ok) > MINUTOS_SIN_CONEXION * 60000:
        movil.apagar_sin_conexion()


def bucle_luces(movil, agente, estado):
    """Segundo núcleo: solo LEDs. Nunca toca la red."""
    try:
        while estado["activo"]:
            movil.actualizar()
            revisar_conexion(movil, agente)
            time.sleep_ms(5)
    finally:
        movil.salida.apagar()


def principal():
    cfg = cargar_config()
    movil = MovilLed(crear_salida(cfg))
    agente = Agente(cfg, movil)
    estado = {"activo": True}

    try:
        import _thread

        _thread.start_new_thread(bucle_luces, (movil, agente, estado))
        en_hilo = True
    except ImportError:
        en_hilo = False   # Sin hilos: las luces se atienden aquí (se pausan durante cada petición).

    t_red = None   # la primera vuelta sale enseguida
    try:
        while True:
            if not en_hilo:
                movil.actualizar()
                revisar_conexion(movil, agente)
            if t_red is None or ticks_diff(ticks_ms(), t_red) >= SEGUNDOS_RED * 1000:
                t_red = ticks_ms()
                try:
                    if not network.WLAN(network.STA_IF).isconnected():
                        conectar_wifi(cfg)
                    agente.vuelta()
                except Exception as e:  # La red nunca debe tumbar las luces.
                    print("red:", type(e).__name__, str(e)[:80])
                    liberar_memoria()
            time.sleep_ms(5 if not en_hilo else 50)
    finally:
        estado["activo"] = False
        time.sleep_ms(50)
        movil.salida.apagar()   # pase lo que pase, LEDs apagados


if __name__ == "__main__":
    principal()
