# ============================================================
# termometro.py · EP08 Lógica del termómetro del biberón (sin hardware ni red)
#
# Reglas (README_BASE_DATOS.md y migraciones):
#   * El rango seguro de la leche está en configuracion.temp_min / temp_max
#     (35 a 40 °C por defecto, CA-33.1). La app lo cambia y el aparato lo lee.
#   * La medición empieza con el botón y dura minutos_medicion (o hasta otra
#     pulsación). Fuera de ella los LEDs están apagados y no se envían
#     temperaturas: solo la señal de vida, con {"midiendo": false}.
#   * Los LEDs se deciden AQUÍ, en la placa, con el último rango conocido: así
#     indican el estado al instante aunque no haya red.
#       verde  -> la leche está dentro del rango
#       rojo   -> demasiado caliente o demasiado fría
#       rojo parpadeando -> el sensor no responde
#   * La base crea las alertas al recibir el evento temperatura_biberon: el
#     aparato NO inserta en alertas (saldrían dos mensajes).
#   * Las muestras que no llegan a la base se guardan en una cola y se reenvían
#     con su ocurrido_en original (RNF-17).
#
# Se prueba en la PC (tests/test_firmware_biberon.py).
# ============================================================

import time

if hasattr(time, "ticks_ms"):
    ticks_ms, ticks_add, ticks_diff = time.ticks_ms, time.ticks_add, time.ticks_diff
else:
    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_add(t, delta):
        return t + delta

    def ticks_diff(a, b):
        return a - b

TEMP_MIN = 35.0      # mismo valor que crear_configuracion() para el biberón
TEMP_MAX = 40.0

EN_RANGO = "en_rango"
CALIENTE = "caliente"
FRIA = "fria"
SIN_LECTURA = "sin_lectura"


def clasificar(temperatura, temp_min, temp_max):
    """Igual que el trigger: > máximo es caliente, < mínimo es fría; los bordes están en rango."""
    if temperatura is None:
        return SIN_LECTURA
    if temperatura > temp_max:
        return CALIENTE
    if temperatura < temp_min:
        return FRIA
    return EN_RANGO


class Boton:
    """Detecta cada pulsación una sola vez (flanco de bajada con antirrebote)."""

    def __init__(self, bloqueo_ms=300):
        self.bloqueo_ms = bloqueo_ms
        self.anterior = False
        self.ultima = None

    def pulsado(self, presionado, ahora_ms):
        nuevo = presionado and not self.anterior
        self.anterior = presionado
        if not nuevo:
            return False
        if self.ultima is not None and ticks_diff(ahora_ms, self.ultima) < self.bloqueo_ms:
            return False          # rebote del contacto
        self.ultima = ahora_ms
        return True


class Termometro:
    def __init__(self, temp_min=TEMP_MIN, temp_max=TEMP_MAX):
        self.temp_min = temp_min
        self.temp_max = temp_max
        self.temperatura = None
        self.estado = SIN_LECTURA
        self.midiendo = False
        self.fin_ms = None        # ticks_ms en que termina la medición

    # --------------------------------------------------------- medición
    def alternar(self, ahora_ms, duracion_ms):
        """Pulsación del botón: empieza o detiene. Devuelve True si empezó."""
        if self.midiendo:
            self.detener()
            return False
        self.midiendo = True
        self.fin_ms = ticks_add(ahora_ms, duracion_ms)
        return True

    def detener(self):
        self.midiendo = False
        self.fin_ms = None

    def vencio(self, ahora_ms):
        """Detiene la medición si ya pasó su duración. Devuelve True si la detuvo."""
        if self.midiendo and ticks_diff(ahora_ms, self.fin_ms) >= 0:
            self.detener()
            return True
        return False

    def aplicar_config(self, temp_min, temp_max):
        """Toma el rango de la base. Ignora valores inválidos. Devuelve True si cambió."""
        try:
            t_min, t_max = float(temp_min), float(temp_max)
        except (TypeError, ValueError):
            return False
        if t_min >= t_max:
            return False
        cambio = (t_min, t_max) != (self.temp_min, self.temp_max)
        self.temp_min, self.temp_max = t_min, t_max
        self.estado = clasificar(self.temperatura, t_min, t_max)
        return cambio

    def al_medir(self, temperatura):
        """Guarda la lectura. Devuelve True si cambió el estado (para avisar enseguida)."""
        if temperatura is not None:
            temperatura = round(float(temperatura), 1)
        self.temperatura = temperatura
        anterior = self.estado
        self.estado = clasificar(temperatura, self.temp_min, self.temp_max)
        return self.estado != anterior

    def leds(self, ahora_ms=None):
        """(rojo, verde) encendidos o no, según el estado."""
        if not self.midiendo:
            return False, False
        if self.estado == EN_RANGO:
            return False, True
        if self.estado in (CALIENTE, FRIA):
            return True, False
        if ahora_ms is None:
            ahora_ms = ticks_ms()
        return (ahora_ms // 500) % 2 == 0, False     # sin lectura: rojo parpadea

    def lectura(self):
        """p_lectura de registrar_senal (vista en vivo de la app)."""
        if not self.midiendo:
            return {"midiendo": False}
        if self.temperatura is None:
            return {"midiendo": True, "temperatura_biberon": None,
                    "aviso": "El sensor de temperatura no responde"}
        return {"midiendo": True, "temperatura_biberon": self.temperatura}

    def evento(self, ocurrido_en):
        """Muestra para eventos. None si no se está midiendo o no hay lectura."""
        if not self.midiendo or self.temperatura is None:
            return None
        evento = {"tipo": "temperatura_biberon", "valor": self.temperatura, "unidad": "°C"}
        if ocurrido_en:
            evento["ocurrido_en"] = ocurrido_en
        return evento


class Cola:
    """Eventos que todavía no llegan a la base (en RAM). Si se llena, se pierden
    los más viejos: una muestra de hace media hora ya no sirve para avisar."""

    def __init__(self, maximo=60):
        self.maximo = maximo
        self.elementos = []

    def __len__(self):
        return len(self.elementos)

    def agregar(self, evento):
        if evento is None:
            return
        # Sin hora no se puede reenviar sin duplicar (RNF-17): la pone la base al llegar.
        self.elementos.append(evento)
        while len(self.elementos) > self.maximo:
            self.elementos.pop(0)

    def enviar(self, insertar):
        """Envía en orden. Se detiene en el primer error y conserva lo que falta."""
        while self.elementos:
            insertar(self.elementos[0])
            self.elementos.pop(0)
