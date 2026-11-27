# ============================================================
# hardware.py · Sonda DS18B20 y LEDs del biberón (MicroPython)
#
# DS18B20 (1 hilo) en GPIO22. Necesita una resistencia de 4.7 kΩ entre DATA y
# 3V3 (algunos módulos ya la traen).
# LEDs rojo y verde, cada uno con su resistencia (220-330 Ω) a GND.
# Botón entre su pin y GND (usa la pull-up interna: no lleva resistencia).
# ============================================================

from machine import Pin

from termometro import ticks_diff, ticks_ms

CONVERSION_MS = 750        # conversión a 12 bits


class SensorDS18B20:
    """Lectura sin bloquear: pide la conversión y la recoge 750 ms después,
    para que los LEDs sigan parpadeando mientras tanto."""

    def __init__(self, pin):
        import ds18x20
        import onewire

        self.ds = ds18x20.DS18X20(onewire.OneWire(Pin(pin)))
        self.roms = []
        self.pedida = None      # ticks_ms de la conversión en curso
        self.ultima = None

    def _pedir(self):
        if not self.roms:
            self.roms = self.ds.scan()
            if not self.roms:
                return
        self.ds.convert_temp()
        self.pedida = ticks_ms()

    def medir(self):
        """Última temperatura en °C, o None si la sonda no responde."""
        try:
            if self.pedida is None:
                self._pedir()
                return self.ultima
            if ticks_diff(ticks_ms(), self.pedida) < CONVERSION_MS:
                return self.ultima
            t = self.ds.read_temp(self.roms[0])
            self.pedida = None
            # 85 °C es el valor de arranque del DS18B20 (lectura fallida); fuera de -55..125 es basura.
            self.ultima = t if (t is not None and t != 85 and -55 <= t <= 125) else None
            self._pedir()
        except Exception:
            self.roms, self.pedida, self.ultima = [], None, None   # se vuelve a buscar la sonda
        return self.ultima


class Pulsador:
    """Botón entre el pin y GND, con la resistencia pull-up interna."""

    def __init__(self, pin):
        self.pin = Pin(pin, Pin.IN, Pin.PULL_UP)

    def presionado(self):
        return self.pin.value() == 0


class Leds:
    def __init__(self, pin_rojo, pin_verde):
        self.rojo = Pin(pin_rojo, Pin.OUT, value=0)
        self.verde = Pin(pin_verde, Pin.OUT, value=0)

    def mostrar(self, rojo, verde):
        self.rojo.value(1 if rojo else 0)
        self.verde.value(1 if verde else 0)

    def apagar(self):
        self.mostrar(False, False)
