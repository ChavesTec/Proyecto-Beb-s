# ============================================================
# salidas.py · Hardware del juguete (MicroPython)
# Autor: Javier Solano (JS)
#
#   5 pulsadores  -> entradas con pull-up interno (presionado = 0) y antirrebote.
#   5 LEDs        -> salidas digitales (GPIO -> resistencia 220 ohm -> LED -> GND).
#   Buzzer pasivo -> PWM: la frecuencia es la nota y el ciclo de trabajo el volumen.
#
# Los pines se eligen en config.json. Valores por defecto para la Pico W:
#   botones GP10..GP14, LEDs GP16..GP20, buzzer GP15.
# No chocan con el móvil de luces (GP2..GP7) por si después comparten placa, ni
# con los pines internos del Wi-Fi de la Pico W (GP23, GP24, GP25, GP29).
# ============================================================

import time

from machine import PWM, Pin

_diferencia = getattr(time, "ticks_diff", lambda a, b: a - b)

ANTIRREBOTE_MS = 40
DUTY_MAXIMO = 32768   # 50 % de ciclo: el sonido más fuerte de un piezo


class HardwareJuguete:
    def __init__(self, pines_botones, pines_leds, pin_buzzer, antirrebote_ms=ANTIRREBOTE_MS):
        if len(pines_botones) != len(pines_leds):
            raise ValueError("Debe haber un LED por cada botón")
        self.cantidad = len(pines_botones)
        self.antirrebote_ms = antirrebote_ms
        self.botones = [Pin(p, Pin.IN, Pin.PULL_UP) for p in pines_botones]
        self.leds = [Pin(p, Pin.OUT, value=0) for p in pines_leds]
        self.buzzer = PWM(Pin(pin_buzzer))
        self.buzzer.duty_u16(0)
        # Antirrebote: último valor leído, cuándo cambió y valor estable (1 = suelto).
        self._crudo = [1] * self.cantidad
        self._t_cambio = [0] * self.cantidad
        self._estable = [1] * self.cantidad

    # ------------------------------------------------------------ botones
    def leer_pulsaciones(self, ahora_ms):
        """Índices de los botones que se acaban de presionar (flanco 1 -> 0, ya estable).

        Mantener un botón presionado cuenta una sola vez.
        """
        presionados = []
        for i, boton in enumerate(self.botones):
            valor = boton.value()
            if valor != self._crudo[i]:
                self._crudo[i] = valor
                self._t_cambio[i] = ahora_ms
            elif valor != self._estable[i] and _diferencia(ahora_ms, self._t_cambio[i]) >= self.antirrebote_ms:
                self._estable[i] = valor
                if valor == 0:
                    presionados.append(i)
        return presionados

    # --------------------------------------------------------------- LEDs
    def mostrar_led(self, indice):
        """Enciende solo el LED indicado (None = todos apagados)."""
        for i, led in enumerate(self.leds):
            led.value(1 if i == indice else 0)

    def todos_leds(self, encendidos):
        for led in self.leds:
            led.value(1 if encendidos else 0)

    # ------------------------------------------------------------- buzzer
    def tono(self, frecuencia, volumen):
        """volumen 0-100. Curva cuadrática: el oído percibe mejor los cambios bajos."""
        if volumen <= 0 or frecuencia <= 0:
            self.silencio()
            return
        self.buzzer.freq(int(frecuencia))
        self.buzzer.duty_u16(DUTY_MAXIMO * volumen * volumen // 10000)

    def silencio(self):
        self.buzzer.duty_u16(0)

    def apagar(self):
        """Pase lo que pase: LEDs apagados y buzzer en silencio."""
        self.todos_leds(False)
        self.silencio()
