# ============================================================
# buzzer.py · Buzzer propio del colchón (activo o pasivo)
#
# "activo": tiene oscilador interno; basta poner el pin en 1 (zumbido fijo).
# "pasivo": hay que darle una onda; se usa PWM a `frecuencia` Hz.
# ============================================================

from machine import PWM, Pin


class Buzzer:
    def __init__(self, pin, tipo="activo", frecuencia=2500):
        self.tipo = tipo
        self.sonando = False
        if tipo == "pasivo":
            self._pwm = PWM(Pin(pin))
            self._pwm.freq(frecuencia)
            self._pwm.duty_u16(0)
        else:
            self._pin = Pin(pin, Pin.OUT)
            self._pin.value(0)

    def fijar(self, encendido):
        self.sonando = bool(encendido)
        if self.tipo == "pasivo":
            self._pwm.duty_u16(32768 if encendido else 0)
        else:
            self._pin.value(1 if encendido else 0)

    def apagar(self):
        self.fijar(False)
