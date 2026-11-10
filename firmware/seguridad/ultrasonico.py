# ============================================================
# ultrasonico.py · Sensor de presencia HC-SR04 (MicroPython)
#
#   TRIG -> GP16
#   ECHO -> GP15  ¡con divisor de voltaje! (ECHO sale a 5 V y la Pico
#                 tolera 3.3 V: p. ej. 1 kΩ en serie y 2 kΩ a GND)
#   VCC  -> VBUS (5 V)
# ============================================================

import time

from machine import Pin, time_pulse_us

from vigilancia import FUERA_DE_RANGO   # el sensor responde pero no hay nada a su alcance
ESPERA_US = 30000          # ~5 m de ida y vuelta; el HC-SR04 deja ECHO ~38 ms sin objeto


class Ultrasonico:
    def __init__(self, pin_trig=16, pin_echo=15):
        self.trig = Pin(pin_trig, Pin.OUT)
        self.echo = Pin(pin_echo, Pin.IN)
        self.trig(0)

    def medir(self):
        """Distancia en cm.
        None           -> el sensor no respondió (cableado o alimentación)
        FUERA_DE_RANGO -> el sensor funciona pero no hay nada al frente"""
        # Si ECHO sigue en alto por la medición anterior, se espera a que baje:
        # de lo contrario time_pulse_us empezaría a contar de inmediato.
        inicio = time.ticks_us()
        while self.echo() == 1:
            if time.ticks_diff(time.ticks_us(), inicio) > 50000:
                return None
        self.trig(0)
        time.sleep_us(2)
        self.trig(1)
        time.sleep_us(10)
        self.trig(0)
        duracion = time_pulse_us(self.echo, 1, ESPERA_US)
        if duracion == -2:          # ECHO nunca subió
            return None
        if duracion == -1:          # ECHO quedó en alto: nada a la vista
            return FUERA_DE_RANGO
        return duracion / 58        # µs -> cm (ida y vuelta a ~343 m/s)
