# ============================================================
# hx711.py · Lector del amplificador HX711 (celda de carga) para MicroPython
#
# Conexión (lado del microcontrolador): VCC -> 3V3, GND -> GND, DT -> pin_dt, SCK -> pin_sck.
# Ganancia 128 en el canal A (la que usa la celda TAL220 en E+/E-/A+/A-).
# El HX711 entrega ~10 muestras por segundo (pin RATE sin conectar).
# ============================================================

from machine import Pin, disable_irq, enable_irq

_PULSOS_EXTRA = {128: 1, 32: 2, 64: 3}   # canal y ganancia de la SIGUIENTE lectura


class HX711:
    def __init__(self, pin_dt, pin_sck, ganancia=128):
        self.dt = Pin(pin_dt, Pin.IN)
        self.sck = Pin(pin_sck, Pin.OUT)
        self.sck.value(0)                 # SCK en alto más de 60 us apagaría el chip
        self.extra = _PULSOS_EXTRA[ganancia]

    def listo(self):
        """True cuando hay una muestra nueva (DT baja a 0)."""
        return self.dt.value() == 0

    def leer_crudo(self):
        """Devuelve el valor de 24 bits con signo, o None si no hay muestra o es inválida.

        Los extremos (0x7FFFFF / -0x800000) significan entrada saturada o cable suelto:
        se descartan para que un cable roto nunca parezca un peso real.
        """
        if not self.listo():
            return None
        valor = 0
        irq = disable_irq()               # los 25 pulsos deben ir seguidos
        try:
            for _ in range(24):
                self.sck.value(1)
                valor = (valor << 1) | self.dt.value()
                self.sck.value(0)
            for _ in range(self.extra):
                self.sck.value(1)
                self.sck.value(0)
        finally:
            enable_irq(irq)
        if valor & 0x800000:
            valor -= 1 << 24
        if valor >= 0x7FFFFF or valor <= -0x800000:
            return None
        return valor
