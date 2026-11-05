# ============================================================
# salidas.py · Hardware de los LEDs del móvil (MicroPython)
#
#   SalidaNeoPixel: anillo WS2812B (arquitectura: 16 LEDs en GPIO23 del ESP32).
#   SalidaPWM:      LEDs sueltos por PWM (prototipo del compañero: GPIO 2..7).
# Ambas reciben una lista de brillos 0-100, uno por LED.
# ============================================================

from machine import PWM, Pin

# Colores suaves por grupo para el anillo (R, G, B), sin azul intenso.
COLORES_SUAVES = [(255, 120, 60), (255, 200, 80), (120, 220, 140), (110, 170, 255)]


class SalidaPWM:
    def __init__(self, pines, brillo_maximo=80, frecuencia=1000):
        self.cantidad = len(pines)
        self.brillo_maximo = brillo_maximo
        self.leds = []
        for numero in pines:
            pwm = PWM(Pin(numero))
            pwm.freq(frecuencia)
            pwm.duty_u16(0)
            self.leds.append(pwm)

    def escribir(self, cuadro):
        for led, porcentaje in zip(self.leds, cuadro):
            led.duty_u16(porcentaje * self.brillo_maximo * 65535 // 10000)

    def apagar(self):
        for led in self.leds:
            led.duty_u16(0)


class SalidaNeoPixel:
    def __init__(self, pin, cantidad=16, brillo_maximo=30, grupos=3):
        import neopixel

        self.cantidad = cantidad
        self.brillo_maximo = brillo_maximo   # % (el anillo a 30 % ya ilumina bastante)
        self.np = neopixel.NeoPixel(Pin(pin, Pin.OUT), cantidad)
        tamano = max(1, cantidad // grupos)
        self.colores = [COLORES_SUAVES[min(i // tamano, len(COLORES_SUAVES) - 1)] for i in range(cantidad)]

    def escribir(self, cuadro):
        for i, porcentaje in enumerate(cuadro):
            factor = porcentaje * self.brillo_maximo
            r, g, b = self.colores[i]
            self.np[i] = (r * factor // 10000, g * factor // 10000, b * factor // 10000)
        self.np.write()

    def apagar(self):
        for i in range(self.cantidad):
            self.np[i] = (0, 0, 0)
        self.np.write()
