# ============================================================
# main.py · EP04 Colchón inteligente conectado a Supabase (MicroPython)
#
# Placa: Raspberry Pi Pico W (o ESP32). Copiar a la placa: main.py, colchon.py,
# agente.py, nube.py, hx711.py, buzzer.py, supabase_micro.py, config.json
# y calibracion.json (se crea con calibrar.py).
#
# Dos mundos que no se estorban:
#   * Bucle principal: lee el peso (HX711), vigila la caída y hace sonar el buzzer.
#     No espera a la red: la alarma funciona aunque no haya Wi-Fi (RNF-16).
#   * Hilo de red: sesión, configuración, comandos, señal de vida y eventos.
# ============================================================

import json
import time

import network
from machine import Pin

from agente import Agente
from buzzer import Buzzer
from colchon import Balanza, Colchon, ticks_diff, ticks_ms
from hx711 import HX711

SEGUNDOS_RED = 2


def leer_json(nombre, por_defecto=None):
    try:
        with open(nombre) as f:
            return json.load(f)
    except Exception:
        if por_defecto is None:
            raise
        return por_defecto


def conectar_wifi(cfg, espera_s=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(cfg["wifi_ssid"], cfg["wifi_clave"])
        inicio = time.time()
        while not wlan.isconnected() and time.time() - inicio < espera_s:
            time.sleep(0.5)
    return wlan.isconnected()


def crear_detector_cuna(cfg):
    """HU-19 / CA-14.2: pin que lee 1 cuando el puerto de la cuna entrega 5 V."""
    pin = cfg.get("pin_deteccion_cuna")
    if pin is None:
        return lambda: False
    p = Pin(pin, Pin.IN)
    return lambda: p.value() == 1


def hilo_red(agente, cfg):
    while agente.activo:
        try:
            if not network.WLAN(network.STA_IF).isconnected():
                conectar_wifi(cfg)
            agente.vuelta(ticks_ms())
        except Exception as e:      # la red nunca debe tumbar la alarma
            print("red:", type(e).__name__, str(e)[:80])
        time.sleep(SEGUNDOS_RED)


def principal():
    cfg = leer_json("config.json")
    cal = leer_json("calibracion.json", {"offset": 0, "factor": 1.0})

    buzzer = Buzzer(cfg.get("pin_buzzer", 16), cfg.get("buzzer_tipo", "activo"))
    balanza = Balanza(HX711(cfg.get("pin_dt", 14), cfg.get("pin_sck", 15)), cal["offset"], cal["factor"])
    colchon = Colchon(balanza, buzzer, crear_detector_cuna(cfg),
                      segundos_confirmacion=cfg.get("segundos_confirmacion", 2))
    agente = Agente(cfg, colchon)

    conectar_wifi(cfg)
    try:
        import _thread
        _thread.start_new_thread(hilo_red, (agente, cfg))
        en_hilo = True
    except ImportError:
        en_hilo = False
    ultimo_red = ticks_ms()

    try:
        while True:
            ahora = ticks_ms()
            colchon.actualizar(ahora)
            if not en_hilo and ticks_diff(ahora, ultimo_red) >= SEGUNDOS_RED * 1000:
                ultimo_red = ahora
                try:
                    agente.vuelta(ahora)
                except Exception as e:
                    print("red:", type(e).__name__)
            time.sleep_ms(20)
    finally:
        agente.activo = False
        buzzer.apagar()      # pase lo que pase, el buzzer no se queda pegado


if __name__ == "__main__":
    principal()
