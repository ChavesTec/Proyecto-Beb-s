# ============================================================
# main.py · EP08 Termómetro del biberón conectado a Supabase (MicroPython)
#
# Placa: Raspberry Pi Pico W o ESP32. Sonda DS18B20 en GPIO22, LED verde en
# GPIO14 y LED rojo en GPIO15 (los pines se pueden cambiar en config.json).
# Copiar a la placa: main.py, termometro.py, hardware.py,
# ../comun/supabase_micro.py y config.json (a partir de config.example.json;
# NO se sube a Git).
#
# Contrato con la base (README_BASE_DATOS.md, "Contrato para los dispositivos"):
#   * Inicia sesión con la cuenta del controlador y busca su id por código.
#   * Lee configuracion (temp_min, temp_max) al arrancar y cada pocos segundos:
#     la app la cambia en el panel del biberón.
#   * registrar_senal cada 5 s con {"temperatura_biberon": t}.
#   * Inserta el evento temperatura_biberon cada minuto y, además, en cuanto la
#     leche entra o sale del rango. El trigger crea «Demasiado caliente» o
#     «Demasiado fría» y las repite cada alerta_repeticion_min.
#   * Atiende probar_luz (HU-07): destello de los dos LEDs durante 2 s.
#
# Los LEDs se actualizan en el bucle principal con el último rango conocido,
# así nunca esperan a la red. La red corre en otro hilo y es la única que toca
# la cola (en la Pico W los dos hilos corren en núcleos distintos).
# ============================================================

import json
import time

import network

from supabase_micro import ClienteSupabase
from termometro import Cola, Termometro, ticks_add, ticks_diff, ticks_ms

SEGUNDOS_SENAL = 5         # contrato: señal de vida cada 5 s
SEGUNDOS_CONFIG = 2        # sondeo de configuracion y comandos
SEGUNDOS_MUESTRA = 60      # contrato: muestra para el historial cada minuto
COLUMNAS_CONFIG = "temp_min,temp_max"


def cargar_config():
    with open("config.json") as f:
        return json.load(f)


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
    if a[0] < 2024:          # reloj sin sincronizar: mejor que la base ponga la hora
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % a[:6]


class Agente:
    """Hilo de red: rango, señal, muestras y comandos."""

    def __init__(self, cfg, termometro, cliente=None):
        self.cfg = cfg
        self.termometro = termometro
        self.cliente = cliente or ClienteSupabase(cfg["supabase_url"], cfg["supabase_anon_key"],
                                                  cfg["correo_controlador"], cfg["clave_controlador"])
        self.dispositivo_id = None
        self.cola = Cola()
        self.ultima_muestra = None
        self.destello_hasta = None      # ticks_ms hasta el que dura probar_luz
        self.pedir_muestra = False      # el bucle de LEDs avisa que cambió el estado
        self.activo = True

    def preparar(self):
        sincronizar_hora()
        self.cliente.iniciar_sesion()
        self.dispositivo_id = self.cliente.id_dispositivo(self.cfg["codigo_dispositivo"])
        self.aplicar_config()

    def aplicar_config(self):
        fila = self.cliente.leer_config(self.dispositivo_id, COLUMNAS_CONFIG)
        if fila:
            self.termometro.aplicar_config(fila["temp_min"], fila["temp_max"])

    def atender_comandos(self):
        for c in self.cliente.comandos_pendientes(self.dispositivo_id):
            if c["tipo"] == "probar_luz":
                self.destello_hasta = ticks_add(ticks_ms(), 2000)
                self.cliente.marcar_comando(c["id"], "ejecutado", None, ahora_iso())
            else:
                self.cliente.marcar_comando(c["id"], "fallido",
                                            "El biberón no admite la orden %s" % c["tipo"], ahora_iso())

    def guardar_muestra(self):
        """Pone en la cola la lectura actual (si hay) para el historial."""
        self.ultima_muestra = ticks_ms()
        evento = self.termometro.evento(ahora_iso())
        if evento:
            evento["dispositivo_id"] = self.dispositivo_id
        self.cola.agregar(evento)

    def toca_muestra(self, ahora_ms=None):
        if self.ultima_muestra is None:
            return True
        return ticks_diff(ahora_ms if ahora_ms is not None else ticks_ms(),
                          self.ultima_muestra) >= SEGUNDOS_MUESTRA * 1000

    def vuelta(self, contador):
        """Una vuelta del ciclo de red."""
        if self.dispositivo_id is None:
            self.preparar()
        self.aplicar_config()
        self.atender_comandos()
        if contador % (SEGUNDOS_SENAL // SEGUNDOS_CONFIG or 1) == 0:
            self.cliente.registrar_senal(self.dispositivo_id, self.termometro.lectura())
        if self.pedir_muestra or self.toca_muestra():
            self.pedir_muestra = False
            self.guardar_muestra()
        self.cola.enviar(self.cliente.insertar_evento)

    def ejecutar(self):
        contador = 0
        while self.activo:
            try:
                if not network.WLAN(network.STA_IF).isconnected():
                    conectar_wifi(self.cfg)
                self.vuelta(contador)
            except Exception as e:  # La red nunca debe trabar los LEDs.
                print("red:", type(e).__name__, str(e)[:80])
            contador += 1
            time.sleep(SEGUNDOS_CONFIG)


def medir_y_mostrar(termometro, agente, sensor, leds, ahora_ms):
    # Entró o salió del rango: muestra inmediata para que la alerta no espere al minuto.
    if termometro.al_medir(sensor.medir()):
        agente.pedir_muestra = True
    pintar(termometro, agente, leds, ahora_ms)


def pintar(termometro, agente, leds, ahora_ms):
    if agente.destello_hasta is not None and ticks_diff(agente.destello_hasta, ahora_ms) > 0:
        encendido = (ahora_ms // 250) % 2 == 0
        leds.mostrar(encendido, encendido)
    else:
        agente.destello_hasta = None
        leds.mostrar(*termometro.leds(ahora_ms))


def principal():
    from hardware import Leds, SensorDS18B20

    cfg = cargar_config()
    sensor = SensorDS18B20(cfg.get("pin_sensor", 22))
    leds = Leds(cfg.get("pin_led_rojo", 15), cfg.get("pin_led_verde", 14))
    termometro = Termometro()
    agente = Agente(cfg, termometro)
    conectar_wifi(cfg)

    try:
        import _thread

        _thread.start_new_thread(agente.ejecutar, ())
        en_hilo = True
    except ImportError:
        en_hilo = False

    ultima_red = ticks_ms()
    try:
        while True:
            ahora = ticks_ms()
            medir_y_mostrar(termometro, agente, sensor, leds, ahora)   # no bloquea (ver hardware.py)
            if not en_hilo and ticks_diff(ahora, ultima_red) >= SEGUNDOS_CONFIG * 1000:
                ultima_red = ahora
                try:
                    agente.vuelta(0)
                except Exception as e:
                    print("red:", type(e).__name__)
            time.sleep_ms(50)
    finally:
        agente.activo = False
        leds.apagar()


if __name__ == "__main__":
    principal()
