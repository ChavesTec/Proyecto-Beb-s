# ============================================================
# juego.py · EP07 Juguete interactivo (MicroPython)
# Autor: Javier Solano (JS)
#
# Lógica del juego de cinco botones, sin red ni hardware: se prueba en la PC.
#
#   HU-29  CA-29.1  Al iniciar una ronda se enciende el LED de 1 de los 5 botones, al azar.
#   HU-30  CA-30.1  Botón correcto: suena la recompensa y empieza una ronda nueva.
#          CA-30.2  Botón incorrecto: no suena nada y el LED sigue encendido.
#          CA-30.3  Sin acierto en el tiempo de la ronda: empieza una ronda nueva.
#   HU-31  CA-31.1  Un tiempo por ronda nuevo se usa desde la SIGUIENTE ronda.
#
# Las rondas empiezan solas al encender el juguete (arquitectura: "juguete.py ·
# rondas al azar (local)"). Sin internet el juego sigue igual; los aciertos se
# guardan y se envían cuando vuelve la conexión.
#
# Hilos: el bucle del juego llama a actualizar(); el hilo de red llama a
# aplicar_config(), lectura(), tomar_aciertos() y a las pruebas. Un candado
# protege el estado compartido.
# ============================================================

import time

try:
    import _thread
    _nuevo_candado = _thread.allocate_lock
except ImportError:  # CPython sin _thread (pruebas)
    import threading
    _nuevo_candado = threading.Lock

try:
    import random
except ImportError:  # pragma: no cover
    import urandom as random

if hasattr(random, "randint"):
    _azar = random.randint
else:  # pragma: no cover  (algunas compilaciones de MicroPython solo traen getrandbits)
    def _azar(a, b):
        return a + random.getrandbits(16) % (b - a + 1)

# --- reloj: MicroPython usa ticks_*; en CPython (pruebas) se emulan ---
if hasattr(time, "ticks_ms"):
    ticks_ms, ticks_add, ticks_diff = time.ticks_ms, time.ticks_add, time.ticks_diff
else:
    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_add(t, delta):
        return t + delta

    def ticks_diff(a, b):
        return a - b


CANTIDAD_BOTONES = 5
TIEMPO_RONDA_DEFECTO_S = 10      # CA-30.3 (el mismo valor por defecto que la base)
TIEMPO_RONDA_MAXIMO_S = 300
VOLUMEN_DEFECTO = 50
PAUSA_ENTRE_RONDAS_MS = 700      # LEDs apagados entre una ronda y la siguiente
MAXIMO_ACIERTOS_GUARDADOS = 50   # sin internet, se guardan los últimos 50

# Recompensa: arpegio Do-Mi-Sol-Do (frecuencia Hz, duración ms). 0 Hz = silencio.
MELODIA_RECOMPENSA = [(523, 110), (659, 110), (784, 110), (0, 40), (1047, 260)]


class Juego:
    def __init__(self, hardware, reloj=ticks_ms, azar=_azar, reloj_epoch=time.time):
        self.hw = hardware
        self._reloj = reloj
        self._azar = azar
        self._epoch = reloj_epoch
        self._candado = _nuevo_candado()

        self.tiempo_ronda_s = TIEMPO_RONDA_DEFECTO_S   # el de la ronda en curso
        self._tiempo_pendiente_s = TIEMPO_RONDA_DEFECTO_S
        self.volumen = VOLUMEN_DEFECTO

        self.estado = "pausa"          # pausa | ronda | recompensa | prueba_luz
        self.objetivo = None           # índice 0..4 del botón iluminado
        self.ronda = 0
        self.aciertos = 0
        self.fallos = 0
        self.version = 0               # sube con cada cambio visible (para avisar a la app)
        self._aciertos_pendientes = []

        ahora = self._reloj()
        self._t_inicio_ronda = ahora
        self._t_fin_estado = ticks_add(ahora, PAUSA_ENTRE_RONDAS_MS)
        self._melodia = []
        self._t_fin_nota = ahora
        self.hw.mostrar_led(None)
        self.hw.silencio()

    # ------------------------------------------------------- configuración
    def aplicar_config(self, tiempo_ronda_s, volumen):
        """Fila de configuracion de la base. Devuelve True si algo cambió."""
        with self._candado:
            cambio = False
            try:
                t = int(tiempo_ronda_s)
            except (TypeError, ValueError):
                t = TIEMPO_RONDA_DEFECTO_S
            t = max(1, min(t, TIEMPO_RONDA_MAXIMO_S))
            if t != self._tiempo_pendiente_s:
                self._tiempo_pendiente_s = t      # CA-31.1: se usa desde la siguiente ronda
                cambio = True
            try:
                v = int(volumen)
            except (TypeError, ValueError):
                v = VOLUMEN_DEFECTO
            v = max(0, min(v, 100))
            if v != self.volumen:
                self.volumen = v                  # el volumen se aplica al próximo sonido
                cambio = True
            return cambio

    # ------------------------------------------------- pruebas desde la app
    def probar_luz(self, duracion_ms=2000):
        """Comando probar_luz (HU-07): los 5 LEDs encendidos un momento."""
        with self._candado:
            self.hw.silencio()
            self.hw.todos_leds(True)
            self.estado = "prueba_luz"
            self.objetivo = None
            self._t_fin_estado = ticks_add(self._reloj(), duracion_ms)
            self.version += 1

    def probar_buzzer(self):
        """Comando probar_buzzer (HU-07): suena la recompensa una vez."""
        with self._candado:
            self.hw.mostrar_led(None)
            self.objetivo = None
            self._iniciar_melodia()
            self.version += 1

    # ------------------------------------------------------ bucle del juego
    def actualizar(self, pulsaciones):
        """pulsaciones: índices (0..4) de los botones recién presionados. Nunca espera."""
        with self._candado:
            ahora = self._reloj()

            if self.estado == "pausa" or self.estado == "prueba_luz":
                if ticks_diff(ahora, self._t_fin_estado) >= 0:
                    self._iniciar_ronda(ahora)
                return

            if self.estado == "recompensa":
                self._avanzar_melodia(ahora)
                return

            # estado == "ronda"
            for boton in pulsaciones:
                if boton == self.objetivo:
                    self._acierto(ahora)
                    return
                self.fallos += 1          # CA-30.2: no suena y el LED sigue encendido

            if ticks_diff(ahora, self._t_inicio_ronda) >= self.tiempo_ronda_s * 1000:
                self._pausa(ahora)        # CA-30.3: se acabó el tiempo, viene otra ronda

    # ----------------------------------------------------------- internos
    def _iniciar_ronda(self, ahora):
        self.tiempo_ronda_s = self._tiempo_pendiente_s
        anterior = self.objetivo
        objetivo = self._azar(0, CANTIDAD_BOTONES - 1)
        if objetivo == anterior:                       # evita repetir el mismo botón
            objetivo = (objetivo + self._azar(1, CANTIDAD_BOTONES - 1)) % CANTIDAD_BOTONES
        self.objetivo = objetivo
        self.ronda += 1
        self.estado = "ronda"
        self._t_inicio_ronda = ahora
        self.hw.mostrar_led(objetivo)                  # CA-29.1
        self.version += 1

    def _pausa(self, ahora, duracion_ms=PAUSA_ENTRE_RONDAS_MS):
        self.hw.mostrar_led(None)
        self.hw.silencio()
        self.estado = "pausa"
        self._t_fin_estado = ticks_add(ahora, duracion_ms)
        self.version += 1

    def _acierto(self, ahora):
        reaccion_s = ticks_diff(ahora, self._t_inicio_ronda) / 1000
        boton = self.objetivo + 1                      # 1..5 para la app
        self.aciertos += 1
        self._aciertos_pendientes.append({"boton": boton, "reaccion_s": round(reaccion_s, 1),
                                          "epoch": self._epoch()})
        if len(self._aciertos_pendientes) > MAXIMO_ACIERTOS_GUARDADOS:
            self._aciertos_pendientes.pop(0)
        self.hw.mostrar_led(None)
        self._iniciar_melodia()                 # CA-30.1
        self.version += 1

    def _iniciar_melodia(self):
        self.estado = "recompensa"
        self._melodia = list(MELODIA_RECOMPENSA)
        self._t_fin_nota = self._reloj()
        self._avanzar_melodia(self._t_fin_nota)

    def _avanzar_melodia(self, ahora):
        if ticks_diff(ahora, self._t_fin_nota) < 0:
            return
        if not self._melodia:
            self.hw.silencio()
            # Tras la recompensa empieza una ronda nueva enseguida (CA-30.1).
            self._iniciar_ronda(ahora)
            return
        frecuencia, duracion = self._melodia.pop(0)
        if frecuencia and self.volumen > 0:
            self.hw.tono(frecuencia, self.volumen)
        else:
            self.hw.silencio()
        self._t_fin_nota = ticks_add(ahora, duracion)

    # ------------------------------------------------------- hacia la base
    def tomar_aciertos(self):
        """Entrega los aciertos sin enviar (el hilo de red los manda a eventos)."""
        with self._candado:
            lista = self._aciertos_pendientes
            self._aciertos_pendientes = []
            return lista

    def devolver_aciertos(self, lista):
        """Si el envío falló, se devuelven para reintentar (RNF-17)."""
        with self._candado:
            self._aciertos_pendientes = (lista + self._aciertos_pendientes)[-MAXIMO_ACIERTOS_GUARDADOS:]

    def lectura(self):
        """Lo que se manda en registrar_senal(p_lectura): la vista en vivo de la app."""
        with self._candado:
            return {
                "boton_activo": self.objetivo + 1 if self.estado == "ronda" else None,
                "ronda": self.ronda,
                "aciertos": self.aciertos,
                "fallos": self.fallos,
                "tiempo_ronda_s": self.tiempo_ronda_s,
                "volumen": self.volumen,
            }
