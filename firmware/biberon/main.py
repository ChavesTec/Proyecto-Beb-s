# ============================================================
# main.py · EP08 Termómetro del biberón conectado a Supabase (MicroPython)
#
# Placa: Raspberry Pi Pico W o ESP32. Sonda DS18B20 en GPIO22, LED verde en
# GPIO14, LED rojo en GPIO15 y botón en GPIO13 (se pueden cambiar en config.json).
# Copiar a la placa: main.py, termometro.py, hardware.py,
# ../comun/supabase_micro.py y config.json (a partir de config.example.json;
# NO se sube a Git).
#
# Contrato con la base (README_BASE_DATOS.md, "Contrato para los dispositivos"):
#   * Inicia sesión con la cuenta del controlador y busca su id por código.
#   * Lee configuracion (temp_min, temp_max) al arrancar y cada pocos segundos:
#     la app la cambia en el panel del biberón.
#   * La medición empieza al pulsar el botón y dura minutos_medicion (otra
#     pulsación la detiene antes). Fuera de ella los LEDs están apagados.
#   * registrar_senal cada 5 s, siempre (así sigue «En línea»):
#     {"midiendo": true, "temperatura_biberon": t} o {"midiendo": false}.
#   * Mientras mide, inserta el evento temperatura_biberon al empezar, cada
#     minuto y en cuanto la leche entra o sale del rango. El trigger crea «Demasiado caliente» o
#     «Demasiado fría» y las repite cada alerta_repeticion_min.
#   * Atiende probar_luz (HU-07): destello de los dos LEDs durante 2 s.
#
# Núcleos (Pico W):
#   * Núcleo 0 (bucle principal): Wi-Fi y Supabase. El chip CYW43 y la pila
#     lwIP se atienden desde el núcleo 0; usar la red desde el núcleo 1
#     (_thread) hacía que la placa se desconectara al rato.
#   * Núcleo 1 (_thread): botón, sonda y LEDs. Así los LEDs nunca esperan a una
#     petición HTTPS, y usan el último rango conocido aunque no haya red.
# Solo el núcleo 0 toca la cola; el núcleo 1 solo levanta pedir_muestra.
# Además: ahorro de energía del Wi-Fi apagado, gc.collect() en cada vuelta y
# reconexión sin bloquear si se cae la red.
# ============================================================

import json
import time

import network

try:
    import gc
except ImportError:
    gc = None

from supabase_micro import ClienteSupabase
from termometro import Boton, Cola, Termometro, ticks_add, ticks_diff, ticks_ms

SEGUNDOS_SENAL = 5         # contrato: señal de vida cada 5 s
SEGUNDOS_CONFIG = 2        # sondeo de configuracion y comandos
SEGUNDOS_MUESTRA = 60      # contrato: muestra para el historial cada minuto
COLUMNAS_CONFIG = "temp_min,temp_max"
FALLAS_PARA_RECONECTAR = 10   # ~20 s seguidos sin poder hablar con la base
PM_SIN_AHORRO = 0xa11140      # CYW43 (Pico W): sin ahorro de energía, la conexión no se duerme


def cargar_config():
    with open("config.json") as f:
        return json.load(f)


def liberar_memoria():
    if gc:
        gc.collect()


def sin_ahorro_de_energia(wlan):
    try:
        wlan.config(pm=PM_SIN_AHORRO)   # solo existe en la Pico W
    except Exception:
        pass


def conectar_wifi(cfg, espera_s=20):
    """Solo al arrancar: espera hasta espera_s a que conecte."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    sin_ahorro_de_energia(wlan)
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


class Wifi:
    """Reconexión sin bloquear: pide conectar y sigue; revisa en la próxima vuelta."""

    def __init__(self, cfg, reintento_s=30):
        self.cfg = cfg
        self.reintento_s = reintento_s
        self.wlan = network.WLAN(network.STA_IF)
        self.ultimo_intento = None

    def conectado(self):
        if self.wlan.isconnected():
            return True
        if self.ultimo_intento is None or ticks_diff(ticks_ms(), self.ultimo_intento) > self.reintento_s * 1000:
            self.ultimo_intento = ticks_ms()
            print("wifi: reconectando")
            try:
                self.wlan.active(True)
                sin_ahorro_de_energia(self.wlan)
                self.wlan.connect(self.cfg["wifi_ssid"], self.cfg["wifi_clave"])
            except OSError as e:
                print("wifi:", e)
        return False

    def reiniciar(self):
        """La placa cree estar conectada pero no llega nada: se fuerza una conexión nueva."""
        print("wifi: sin respuesta de la base, se reinicia la conexión")
        try:
            self.wlan.disconnect()
        except OSError:
            pass
        self.ultimo_intento = None


class Agente:
    """Red (núcleo 0): rango, señal, muestras y comandos."""

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
        self.fallas = 0                 # vueltas seguidas con error

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
        liberar_memoria()               # cada HTTPS deja basura; sin esto se fragmenta la RAM
        if self.dispositivo_id is None:
            self.preparar()
        self.aplicar_config()
        self.atender_comandos()
        if contador % (SEGUNDOS_SENAL // SEGUNDOS_CONFIG or 1) == 0:
            self.cliente.registrar_senal(self.dispositivo_id, self.termometro.lectura())
        if not self.termometro.midiendo:
            self.pedir_muestra = False
        elif self.pedir_muestra or self.toca_muestra():
            self.pedir_muestra = False
            self.guardar_muestra()
        self.cola.enviar(self.cliente.insertar_evento)

    def vuelta_segura(self, contador):
        """vuelta() sin dejar escapar errores. Devuelve True si hay que reiniciar el Wi-Fi."""
        try:
            self.vuelta(contador)
            self.fallas = 0
            return False
        except Exception as e:  # La red nunca debe detener el aparato.
            self.fallas += 1
            libre = gc.mem_free() if gc and hasattr(gc, "mem_free") else "?"
            print("red:", type(e).__name__, str(e)[:80], "· memoria libre:", libre)
            if self.fallas >= FALLAS_PARA_RECONECTAR:
                self.fallas = 0
                self.cliente.token = None   # sesión nueva al volver
                return True
            return False


def atender_boton(termometro, agente, boton, pulsador, ahora_ms, duracion_ms):
    if boton.pulsado(pulsador.presionado(), ahora_ms):
        if termometro.alternar(ahora_ms, duracion_ms):
            print("Medición iniciada")
            agente.pedir_muestra = True       # primera muestra enseguida
        else:
            print("Medición detenida")
    elif termometro.vencio(ahora_ms):
        print("Medición terminada por tiempo")


def medir_y_mostrar(termometro, agente, sensor, leds, ahora_ms):
    # La sonda se lee siempre, para tener el dato fresco al pulsar el botón.
    # Entró o salió del rango: muestra inmediata para que la alerta no espere al minuto.
    if termometro.al_medir(sensor.medir()) and termometro.midiendo:
        agente.pedir_muestra = True
    pintar(termometro, agente, leds, ahora_ms)


def pintar(termometro, agente, leds, ahora_ms):
    if agente.destello_hasta is not None and ticks_diff(agente.destello_hasta, ahora_ms) > 0:
        encendido = (ahora_ms // 250) % 2 == 0
        leds.mostrar(encendido, encendido)
    else:
        agente.destello_hasta = None
        leds.mostrar(*termometro.leds(ahora_ms))


def bucle_leds(termometro, agente, sensor, leds, boton, pulsador, duracion_ms):
    """Núcleo 1: botón, sonda y LEDs, cada 50 ms."""
    try:
        while agente.activo:
            try:
                ahora = ticks_ms()
                atender_boton(termometro, agente, boton, pulsador, ahora, duracion_ms)
                medir_y_mostrar(termometro, agente, sensor, leds, ahora)   # no bloquea
            except Exception as e:
                print("leds:", type(e).__name__, e)
            time.sleep_ms(50)
    finally:
        leds.apagar()


def principal():
    from hardware import Leds, Pulsador, SensorDS18B20

    cfg = cargar_config()
    sensor = SensorDS18B20(cfg.get("pin_sensor", 22))
    leds = Leds(cfg.get("pin_led_rojo", 15), cfg.get("pin_led_verde", 14))
    pulsador = Pulsador(cfg.get("pin_boton", 13))
    boton = Boton()
    duracion_ms = int(cfg.get("minutos_medicion", 10) * 60000)
    termometro = Termometro()
    agente = Agente(cfg, termometro)
    conectar_wifi(cfg)
    wifi = Wifi(cfg)

    try:
        import _thread

        _thread.start_new_thread(bucle_leds, (termometro, agente, sensor, leds, boton, pulsador, duracion_ms))
        en_hilo = True
    except ImportError:
        en_hilo = False   # sin hilos: los LEDs se atienden aquí y se pausan durante cada petición

    ultima_red = None
    contador = 0
    try:
        while True:
            ahora = ticks_ms()
            if not en_hilo:
                atender_boton(termometro, agente, boton, pulsador, ahora, duracion_ms)
                medir_y_mostrar(termometro, agente, sensor, leds, ahora)
            if ultima_red is None or ticks_diff(ahora, ultima_red) >= SEGUNDOS_CONFIG * 1000:
                ultima_red = ahora
                if wifi.conectado() and agente.vuelta_segura(contador):
                    wifi.reiniciar()
                contador += 1
            time.sleep_ms(50)
    finally:
        agente.activo = False   # el núcleo 1 sale de su bucle y apaga los LEDs
        leds.apagar()


if __name__ == "__main__":
    principal()
