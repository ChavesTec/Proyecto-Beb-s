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
# La red corre en un segundo hilo para que las luces nunca se traben
# esperando una respuesta HTTP. Sin contacto con Supabase durante
# MINUTOS_SIN_CONEXION, el móvil se apaga por seguridad (los horarios los
# aplica la base y, sin red, no llegaría la orden de apagar).
# ============================================================

import json
import time

import network

from luces import MovilLed, ticks_diff, ticks_ms
from supabase_micro import ClienteSupabase

SEGUNDOS_SENAL = 5        # contrato: señal de vida cada 5 s
SEGUNDOS_CONFIG = 2       # sondeo de configuracion y comandos
MINUTOS_SIN_CONEXION = 10


def cargar_config():
    with open("config.json") as f:
        return json.load(f)


def crear_salida(cfg):
    from salidas import SalidaNeoPixel, SalidaPWM

    if cfg.get("salida", "neopixel") == "pwm":
        return SalidaPWM(cfg.get("pines_pwm", [2, 3, 4, 5, 6, 7]), cfg.get("brillo_maximo", 80))
    return SalidaNeoPixel(cfg.get("pin_neopixel", 23), cfg.get("cantidad_leds", 16), cfg.get("brillo_maximo", 30))


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


def ahora_iso():
    a = time.gmtime()
    if a[0] < 2024:          # reloj sin sincronizar: mejor no enviar una fecha falsa
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % a[:6]


class Agente:
    """Hilo de red: señal, configuración y comandos."""

    def __init__(self, cfg, movil):
        self.cfg = cfg
        self.movil = movil
        self.cliente = ClienteSupabase(cfg["supabase_url"], cfg["supabase_anon_key"],
                                       cfg["correo_controlador"], cfg["clave_controlador"])
        self.dispositivo_id = None
        self.ultimo_ok = ticks_ms()
        self.activo = True

    def preparar(self):
        sincronizar_hora()
        self.cliente.iniciar_sesion()
        self.dispositivo_id = self.cliente.id_dispositivo(self.cfg["codigo_dispositivo"])
        self.aplicar_config()   # CA-11.3 equivalente: arranca con el último estado guardado

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

    def vuelta(self, contador):
        """Una vuelta del ciclo de red. Devuelve True si hubo contacto con la base."""
        if self.dispositivo_id is None:
            self.preparar()
        self.aplicar_config()
        self.atender_comandos()
        if contador % (SEGUNDOS_SENAL // SEGUNDOS_CONFIG or 1) == 0:
            self.senal()
        return True

    def ejecutar(self):
        contador = 0
        while self.activo:
            try:
                if not network.WLAN(network.STA_IF).isconnected():
                    conectar_wifi(self.cfg)
                if self.vuelta(contador):
                    self.ultimo_ok = ticks_ms()
            except Exception as e:  # La red nunca debe tumbar las luces.
                print("red:", type(e).__name__, str(e)[:80])
            contador += 1
            time.sleep(SEGUNDOS_CONFIG)


def principal():
    cfg = cargar_config()
    movil = MovilLed(crear_salida(cfg))
    conectar_wifi(cfg)
    agente = Agente(cfg, movil)

    try:
        import _thread

        _thread.start_new_thread(agente.ejecutar, ())
        en_hilo = True
    except ImportError:
        en_hilo = False   # Sin hilos: la red se atiende en el mismo bucle (las luces se pausan un momento).

    ultimo = ticks_ms()
    try:
        while True:
            movil.actualizar()
            if not en_hilo and ticks_diff(ticks_ms(), ultimo) >= SEGUNDOS_CONFIG * 1000:
                ultimo = ticks_ms()
                try:
                    agente.vuelta(0)
                    agente.ultimo_ok = ticks_ms()
                except Exception as e:
                    print("red:", type(e).__name__)
            if ticks_diff(ticks_ms(), agente.ultimo_ok) > MINUTOS_SIN_CONEXION * 60000:
                movil.apagar_sin_conexion()
            time.sleep_ms(5)
    finally:
        agente.activo = False
        movil.salida.apagar()   # pase lo que pase, LEDs apagados


if __name__ == "__main__":
    principal()
