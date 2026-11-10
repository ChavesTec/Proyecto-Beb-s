# HC-SR04 + OV7670 en Raspberry Pi Pico W (MicroPython 1.23 o superior)
#
# Cuando el sensor ultrasónico detecta algo a menos de DISTANCIA_DISPARO cm,
# la cámara OV7670 toma una foto (160x120, RGB565) y la guarda como .bmp
# en la memoria flash de la Pico.
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
#   HC-SR04 TRIG    -> GP16
#   HC-SR04 ECHO    -> GP15  (¡con divisor de voltaje! ECHO sale a 5V y la Pico tolera 3.3V)

import machine, time, struct, os, rp2, micropython
from machine import Pin, I2C, PWM

# ---------------- Configuración ----------------
DISTANCIA_DISPARO = 20      # cm
PAUSA_TRAS_FOTO = 3         # segundos de espera después de cada foto
PATRON_DE_PRUEBA = False    # True = la cámara genera barras de colores (sirve para depurar)
DIAGNOSTICO = False          # True = al arrancar, mide cada línea de datos de la cámara
INTERCAMBIAR_BYTES = False  # si los colores salen mal (rojo<->azul, tonos raros), prueba cambiarlo a False

PIN_ECHO, PIN_TRIG = 15, 16
PIN_D0 = 0
PIN_PCLK, PIN_VSYNC, PIN_HREF = 8, 9, 10
PIN_XCLK = 11
PIN_SDA, PIN_SCL = 12, 13

ANCHO, ALTO = 154, 120       # ancho medido: la cámara entrega 308 bytes por línea
FRAME_BYTES = ANCHO * ALTO * 2          # RGB565 = 2 bytes por pixel
DIR_CAMARA = 0x21                       # dirección I2C (SCCB) de la OV7670

# ---------------- Sensor ultrasónico ----------------
pinecho = Pin(PIN_ECHO, Pin.IN)
pintrig = Pin(PIN_TRIG, Pin.OUT)

FUERA_DE_RANGO = 999

def read_ultrasonic():
    """Distancia en cm.
    None          -> el sensor no respondió (problema de cableado o alimentación)
    FUERA_DE_RANGO -> el sensor funciona pero no hay nada a su alcance"""
    pintrig(0)
    time.sleep_us(10)
    pintrig(1)
    time.sleep_us(10)
    pintrig(0)

    # el sensor debe subir ECHO en pocos milisegundos; si no, no está respondiendo
    t = time.ticks_us()
    while pinecho() == 0:
        if time.ticks_diff(time.ticks_us(), t) > 30000:
            return None
    toff = time.ticks_us()

    # si ECHO se queda en alto demasiado tiempo, no hay objeto a la vista
    while pinecho() == 1:
        if time.ticks_diff(time.ticks_us(), toff) > 30000:
            return FUERA_DE_RANGO
    ton = time.ticks_us()

    return time.ticks_diff(ton, toff) / 58

# ---------------- Cámara OV7670 ----------------
Pin(PIN_PCLK, Pin.IN)
Pin(PIN_VSYNC, Pin.IN)
Pin(PIN_HREF, Pin.IN)
# líneas de datos D0..D7 como entradas con pull-up, igual que en prueba_pines.py
for _n in range(8):
    Pin(PIN_D0 + _n, Pin.IN, Pin.PULL_UP)

i2c = I2C(0, sda=Pin(PIN_SDA), scl=Pin(PIN_SCL), freq=100_000)

# Registros: QQVGA (160x120), salida RGB565
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

def cam_write(reg, val):
    i2c.writeto_mem(DIR_CAMARA, reg, bytes([val]))

# Programa PIO: espera el inicio de frame (VSYNC) y luego captura un byte
# en cada flanco de subida de PCLK mientras HREF esté en alto.
# OJO: dentro de una función PIO no se pueden usar variables del programa,
# por eso los números de pin van escritos directamente:
#   VSYNC = GP9, PCLK = GP8  (si cambias PIN_VSYNC o PIN_PCLK, cámbialos aquí también)
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

frame = bytearray(FRAME_BYTES)      # buffer reservado una sola vez
xclk = None

def capturar():
    """Captura un frame completo en 'frame'. Devuelve True si salió bien."""
    sm = rp2.StateMachine(0, pio_captura, freq=125_000_000,
                          in_base=Pin(PIN_D0), jmp_pin=Pin(PIN_HREF))
    dma = rp2.DMA()
    ctrl = dma.pack_ctrl(size=2, inc_read=False, inc_write=True, treq_sel=4)  # 4 = RX de PIO0 SM0
    dma.config(read=0x50200020, write=frame, count=FRAME_BYTES // 4,
               ctrl=ctrl, trigger=True)
    sm.active(1)

    t0 = time.ticks_ms()
    while dma.active():
        if time.ticks_diff(time.ticks_ms(), t0) > 2000:
            break
    ok = not dma.active()
    if not ok:
        dma.active(False)
    sm.active(0)
    dma.close()
    return ok

def medir_linea():
    """Con el patrón de prueba todas las líneas son parecidas; busca cada cuántos bytes se repite."""
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

def diagnostico():
    """Captura un frame y mide qué tanto cambia cada línea de datos (D0..D7)."""
    if not capturar():
        print("Diagnóstico: no llegó imagen (revisa XCLK, PCLK, VSYNC y HREF)")
        return
    unos = [0] * 8
    for b in frame:
        for bit in range(8):
            if b & (1 << bit):
                unos[bit] += 1
    total = len(frame)
    print("Diagnóstico: porcentaje de '1' en cada línea de datos")
    for bit in range(8):
        pct = unos[bit] * 100 // total
        aviso = "   <-- SIN CAMBIOS, revisa este cable" if pct < 2 or pct > 98 else ""
        print("  D%d: %d%%%s" % (bit, pct, aviso))
    print("Primeros bytes:", [hex(x) for x in frame[:16]])
    if PATRON_DE_PRUEBA:
        medir_linea()

def iniciar_camara():
    global xclk
    # reloj de la cámara (~25 MHz)
    xclk = PWM(Pin(PIN_XCLK))
    xclk.freq(24_000_000)
    xclk.duty_u16(32768)
    time.sleep_ms(100)

    if DIR_CAMARA not in i2c.scan():
        raise RuntimeError("No se detecta la cámara por I2C (revisa SDA/SCL, pull-ups y alimentación)")

    cam_write(0x12, 0x80)           # reset por software
    time.sleep_ms(100)
    for reg, val in CONFIG_CAMARA:
        cam_write(reg, val)
    if PATRON_DE_PRUEBA:
        cam_write(0x70, 0x3A | 0x80)
        cam_write(0x71, 0x35 | 0x80)
    time.sleep_ms(300)

    # descartar unos frames para que se estabilicen exposición y balance de blancos
    for _ in range(3):
        capturar()

@micropython.viper
def intercambiar_bytes(src: ptr8, dst: ptr8, n: int):
    # La cámara envía cada pixel con el byte alto primero; el BMP lo quiere al revés.
    i = 0
    while i < n:
        dst[i] = src[i + 1]
        dst[i + 1] = src[i]
        i += 2

def guardar_bmp(ruta, intercambiar=INTERCAMBIAR_BYTES):
    if intercambiar:
        sw = bytearray(FRAME_BYTES)
        intercambiar_bytes(frame, sw, FRAME_BYTES)
        mv = memoryview(sw)
    else:
        mv = memoryview(frame)
    offset = 14 + 40 + 12
    with open(ruta, "wb") as f:
        f.write(struct.pack("<2sIHHI", b"BM", offset + FRAME_BYTES, 0, 0, offset))
        f.write(struct.pack("<IiiHHIIiiII", 40, ANCHO, ALTO, 1, 16, 3, FRAME_BYTES, 2835, 2835, 0, 0))
        f.write(struct.pack("<III", 0xF800, 0x07E0, 0x001F))   # máscaras RGB565
        fila = ANCHO * 2
        for y in range(ALTO - 1, -1, -1):                      # el BMP se guarda de abajo hacia arriba
            f.write(mv[y * fila:(y + 1) * fila])

def siguiente_nombre():
    existentes = os.listdir()
    n = 0
    while "foto_%d.bmp" % n in existentes:
        n += 1
    return "foto_%d.bmp" % n

def tomar_foto():
    st = os.statvfs("/")
    libre = st[0] * st[3]
    if libre < FRAME_BYTES + 20000:
        print("Memoria llena, borra fotos antiguas")
        return
    if not capturar():
        print("Error: la cámara no envió imagen (revisa VSYNC/PCLK/HREF/XCLK)")
        return
    if PATRON_DE_PRUEBA:
        n = 0
        while "prueba_%d_a.bmp" % n in os.listdir():
            n += 1
        guardar_bmp("prueba_%d_a.bmp" % n, True)
        guardar_bmp("prueba_%d_b.bmp" % n, False)
        print("Guardadas: prueba_%d_a.bmp (bytes intercambiados) y prueba_%d_b.bmp (sin intercambiar)" % (n, n))
        return
    nombre = siguiente_nombre()
    guardar_bmp(nombre)
    print("Foto guardada:", nombre)

# ---------------- Programa principal ----------------
camara_ok = False
try:
    iniciar_camara()
    camara_ok = True
    print("Cámara lista")
    if DIAGNOSTICO:
        diagnostico()
except Exception as e:
    print("La cámara falló, el sensor sigue funcionando sin ella:", e)

print("Listo")

while True:
    distance = read_ultrasonic()
    if distance is None:
        print("El sensor NO responde (revisa Vcc a 5V, Trig, Echo y el divisor)")
    elif distance == FUERA_DE_RANGO:
        print("Sensor OK, pero no hay nada al frente")
    else:
        print(f'Distancia medida: {distance} cm')
        if distance < DISTANCIA_DISPARO:
            print("Presencia detectada")
            if camara_ok:
                tomar_foto()
                time.sleep(PAUSA_TRAS_FOTO)
    time.sleep(1)