# ============================================================
# camara.py · Cámara OV7670 (sin FIFO) en Raspberry Pi Pico W
#
# Captura un cuadro RGB565 de 154x120 con PIO + DMA, sin ocupar el CPU.
#
# CONEXIONES
#   OV7670  D0..D7  -> GP0..GP7   (deben ser consecutivos, D0 en GP0)
#   OV7670  PCLK    -> GP8
#   OV7670  VSYNC   -> GP9
#   OV7670  HREF    -> GP10
#   OV7670  XCLK    -> GP11       (la Pico genera el reloj de la cámara)
#   OV7670  SIOD    -> GP12       (SDA, necesita pull-up de 4.7k a 3.3V)
#   OV7670  SIOC    -> GP13       (SCL, necesita pull-up de 4.7k a 3.3V)
#   OV7670  RESET   -> 3.3V
#   OV7670  PWDN    -> GND
#   OV7670  3.3V/GND -> 3V3(OUT) / GND
# ============================================================

import time

import rp2
from machine import I2C, PWM, Pin

PIN_D0 = 0
PIN_PCLK, PIN_VSYNC, PIN_HREF = 8, 9, 10
PIN_XCLK = 11
PIN_SDA, PIN_SCL = 12, 13

# El registro configura QQVGA (160x120), pero con esta ventana (HSTART/HSTOP)
# la cámara entrega 308 bytes por línea, medidos con el patrón de prueba:
# por eso el ancho útil es 154 píxeles.
ANCHO, ALTO = 154, 120
FRAME_BYTES = ANCHO * ALTO * 2          # RGB565 = 2 bytes por píxel
DIR_CAMARA = 0x21                       # dirección I2C (SCCB) de la OV7670

CONFIG_CAMARA = (
    (0x12, 0x14),   # COM7: RGB + formato QVGA
    (0x11, 0x03),   # CLKRC: divide el reloj entre 4 (señal más lenta = más estable en protoboard)
    (0x0C, 0x04),   # COM3: habilita DCW (reducción)
    (0x3E, 0x1A),   # COM14: escalado manual, PCLK dividido
    (0x70, 0x3A),   # SCALING_XSC
    (0x71, 0x35),   # SCALING_YSC
    (0x72, 0x22),   # SCALING_DCWCTR: reduce 1/4 en X e Y
    (0x73, 0xF2),   # SCALING_PCLK_DIV
    (0xA2, 0x02),   # SCALING_PCLK_DELAY
    (0x40, 0xD0),   # COM15: RGB565, rango completo 00-FF
    (0x8C, 0x00),   # RGB444 desactivado
    (0x17, 0x16),   # HSTART
    (0x18, 0x04),   # HSTOP
    (0x32, 0x24),   # HREF
    (0x19, 0x02),   # VSTART
    (0x1A, 0x7A),   # VSTOP
    (0x03, 0x0A),   # VREF
)

# Dirección del FIFO RX de PIO0 SM0 (RXF0 = base de PIO0 + 0x20) y su DREQ.
PIO0_RXF0 = 0x50200020
DREQ_PIO0_RX0 = 4


# Programa PIO: espera el inicio de frame (VSYNC) y luego captura un byte
# en cada flanco de subida de PCLK mientras HREF esté en alto.
# OJO: dentro de una función PIO no se pueden usar variables del programa,
# por eso los números de pin van escritos directamente:
#   VSYNC = GP9, PCLK = GP8. Camara() revisa que coincidan con las constantes.
@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_RIGHT, autopush=True, push_thresh=32)
def pio_captura():
    wait(1, gpio, 9)            # VSYNC sube
    wait(0, gpio, 9)            # VSYNC baja: empieza el frame
    label("inicio")
    wait(1, gpio, 8)            # flanco de subida de PCLK
    jmp(pin, "dato")            # el pin de salto es HREF
    wait(0, gpio, 8)
    jmp("inicio")
    label("dato")
    in_(pins, 8)                # leer D0..D7
    wait(0, gpio, 8)
    jmp("inicio")


class Camara:
    def __init__(self):
        if (PIN_VSYNC, PIN_PCLK) != (9, 8):
            raise ValueError("pio_captura tiene VSYNC=GP9 y PCLK=GP8 escritos a mano: actualícelo")
        Pin(PIN_PCLK, Pin.IN)
        Pin(PIN_VSYNC, Pin.IN)
        Pin(PIN_HREF, Pin.IN)
        for n in range(8):      # D0..D7 como entradas con pull-up
            Pin(PIN_D0 + n, Pin.IN, Pin.PULL_UP)
        self.i2c = I2C(0, sda=Pin(PIN_SDA), scl=Pin(PIN_SCL), freq=100_000)
        self.ancho, self.alto = ANCHO, ALTO
        self.frame = bytearray(FRAME_BYTES)     # búfer reservado una sola vez
        self.xclk = None
        self.lista = False

    def _escribir(self, reg, val):
        self.i2c.writeto_mem(DIR_CAMARA, reg, bytes([val]))

    def iniciar(self, patron_de_prueba=False):
        # Reloj de la cámara. Con 125 MHz de sistema el PWM da ~25 MHz (125/5),
        # dentro del rango de la OV7670 (10-48 MHz).
        self.xclk = PWM(Pin(PIN_XCLK))
        self.xclk.freq(24_000_000)
        self.xclk.duty_u16(32768)
        time.sleep_ms(100)

        if DIR_CAMARA not in self.i2c.scan():
            raise RuntimeError("No se detecta la cámara por I2C (revisa SDA/SCL, pull-ups y alimentación)")

        self._escribir(0x12, 0x80)      # reset por software
        time.sleep_ms(100)
        for reg, val in CONFIG_CAMARA:
            self._escribir(reg, val)
        if patron_de_prueba:
            # test_pattern[1:0] = 10 -> barras de 8 colores (bit 7 de SCALING_YSC).
            # Con el bit 7 de SCALING_XSC también encendido saldría "fade to gray".
            self._escribir(0x71, 0x35 | 0x80)
        time.sleep_ms(300)

        # Descartar unos frames para que se estabilicen exposición y balance de blancos.
        for _ in range(3):
            self.capturar()
        self.lista = True

    def capturar(self, espera_ms=2000):
        """Captura un frame completo en self.frame. Devuelve True si salió bien."""
        sm = rp2.StateMachine(0, pio_captura, freq=125_000_000,
                              in_base=Pin(PIN_D0), jmp_pin=Pin(PIN_HREF))
        dma = rp2.DMA()
        try:
            ctrl = dma.pack_ctrl(size=2, inc_read=False, inc_write=True, treq_sel=DREQ_PIO0_RX0)
            dma.config(read=PIO0_RXF0, write=self.frame, count=FRAME_BYTES // 4,
                       ctrl=ctrl, trigger=True)
            sm.active(1)
            t0 = time.ticks_ms()
            while dma.active():
                if time.ticks_diff(time.ticks_ms(), t0) > espera_ms:
                    break
            ok = not dma.active()
            if not ok:
                dma.active(False)
            return ok
        finally:
            sm.active(0)
            dma.close()

    # ------------------------------------------------------------ diagnóstico
    def diagnostico(self, patron_de_prueba=False):
        """Captura un frame y mide qué tanto cambia cada línea de datos (D0..D7)."""
        if not self.capturar():
            print("Diagnóstico: no llegó imagen (revisa XCLK, PCLK, VSYNC y HREF)")
            return
        unos = [0] * 8
        for b in self.frame:
            for bit in range(8):
                if b & (1 << bit):
                    unos[bit] += 1
        total = len(self.frame)
        print("Diagnóstico: porcentaje de '1' en cada línea de datos")
        for bit in range(8):
            pct = unos[bit] * 100 // total
            aviso = "   <-- SIN CAMBIOS, revisa este cable" if pct < 2 or pct > 98 else ""
            print("  D%d: %d%%%s" % (bit, pct, aviso))
        print("Primeros bytes:", [hex(x) for x in self.frame[:16]])
        if patron_de_prueba:
            self.medir_linea()

    def medir_linea(self):
        """Con el patrón de prueba todas las líneas son parecidas; busca cada cuántos bytes se repite."""
        frame = self.frame
        muestras = range(0, 12000, 31)
        mejor_p, mejor_score = 0, -1
        for p in range(100, 1400):
            coincide = 0
            for i in muestras:
                d = frame[i] - frame[i + p]
                if -12 <= d <= 12:
                    coincide += 1
            if coincide > mejor_score:
                mejor_score = coincide
                mejor_p = p
        pct = mejor_score * 100 // len(muestras)
        print("Longitud de línea detectada: %d bytes (%d píxeles), coincidencia %d%%" % (mejor_p, mejor_p // 2, pct))
        print("El código espera %d bytes (%d píxeles) por línea" % (ANCHO * 2, ANCHO))
