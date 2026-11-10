# ============================================================
# imagen.py · EP06 Foto de evidencia en PNG (MicroPython y CPython)
#
# La OV7670 entrega RGB565 (2 bytes por píxel). La base, la galería y
# Telegram necesitan un formato estándar, y la Pico no tiene memoria ni
# velocidad para comprimir en JPEG. Por eso se escribe un PNG RGB de 8 bits
# SIN comprimir (bloques "stored" de deflate, uno por fila):
#   * se escribe fila por fila, así solo se necesita un búfer de una fila;
#   * 154x120 ocupa ~56 KB, por debajo del límite de 150 KB (RNF-05);
#   * Pillow, los navegadores y Telegram lo abren sin problema.
#
# Sin hardware: se prueba en la PC (tests/test_firmware_seguridad.py).
# ============================================================

import struct
from array import array

try:
    import micropython
    _viper = micropython.viper
except (ImportError, AttributeError):   # CPython: el mismo código corre como Python normal
    ptr8 = ptr32 = None                    # solo nombres para las anotaciones de viper

    def _viper(funcion):
        return funcion

_TABLA = None


def crc32_python(datos, crc=0):
    """CRC-32 de PNG/zlib en Python puro (más lento), por si falta binascii.crc32."""
    global _TABLA
    if _TABLA is None:
        _TABLA = array("I", [0] * 256)
        for n in range(256):
            c = n
            for _ in range(8):
                c = (0xEDB88320 ^ (c >> 1)) if c & 1 else (c >> 1)
            _TABLA[n] = c
    crc ^= 0xFFFFFFFF
    for b in datos:
        crc = _TABLA[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


try:
    from binascii import crc32 as _crc32
except ImportError:  # algunas compilaciones de MicroPython no lo traen
    _crc32 = crc32_python

FIRMA_PNG = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- píxeles
# Viper admite máximo 4 argumentos: por eso hay una función por orden de bytes.
@_viper
def _fila_alto_primero(src: ptr8, inicio: int, dst: ptr8, n: int):
    """Convierte n píxeles RGB565 (byte alto primero) a RGB888, desde dst[1]."""
    i = 0
    j = 1                       # dst[0] es el byte de filtro PNG (0 = ninguno)
    while i < n:
        alto = int(src[inicio + 2 * i])
        bajo = int(src[inicio + 2 * i + 1])
        r = alto >> 3
        g = ((alto & 7) << 3) | (bajo >> 5)
        b = bajo & 0x1F
        dst[j] = (r << 3) | (r >> 2)
        dst[j + 1] = (g << 2) | (g >> 4)
        dst[j + 2] = (b << 3) | (b >> 2)
        i += 1
        j += 3


@_viper
def _fila_bajo_primero(src: ptr8, inicio: int, dst: ptr8, n: int):
    """Igual que _fila_alto_primero, para cámaras que mandan el byte bajo primero."""
    i = 0
    j = 1
    while i < n:
        bajo = int(src[inicio + 2 * i])
        alto = int(src[inicio + 2 * i + 1])
        r = alto >> 3
        g = ((alto & 7) << 3) | (bajo >> 5)
        b = bajo & 0x1F
        dst[j] = (r << 3) | (r >> 2)
        dst[j + 1] = (g << 2) | (g >> 4)
        dst[j + 2] = (b << 3) | (b >> 2)
        i += 1
        j += 3


@_viper
def _adler(buf: ptr8, n: int, estado: ptr32):
    """Suma n bytes de buf a adler32 (estado[0] = s1, estado[1] = s2), sin reducir."""
    s1 = int(estado[0])
    s2 = int(estado[1])
    i = 0
    while i < n:            # sin módulo aquí (viper): lo aplica escribir_png después de cada fila
        s1 += int(buf[i])
        s2 += s1
        i += 1
    estado[0] = s1
    estado[1] = s2


def rgb565_a_rgb888(frame, ancho, alto, byte_alto_primero=True):
    """Toda la imagen en RGB888 (solo para pruebas y diagnóstico: usa mucha RAM)."""
    fila = bytearray(1 + 3 * ancho)
    convertir = _fila_alto_primero if byte_alto_primero else _fila_bajo_primero
    salida = bytearray()
    for y in range(alto):
        convertir(frame, y * ancho * 2, fila, ancho)
        salida += fila[1:]
    return bytes(salida)


# ---------------------------------------------------------------- PNG
def _chunk(f, tipo, datos):
    f.write(struct.pack(">I", len(datos)))
    f.write(tipo)
    f.write(datos)
    f.write(struct.pack(">I", _crc32(datos, _crc32(tipo)) & 0xFFFFFFFF))


def tamano_png(ancho, alto):
    """Bytes exactos del archivo, para revisar el espacio libre antes de escribir."""
    fila = 1 + 3 * ancho
    idat = 2 + alto * (5 + fila) + 4
    return len(FIRMA_PNG) + (12 + 13) + (12 + idat) + 12


def escribir_png(f, frame, ancho, alto, byte_alto_primero=True):
    """Escribe en el archivo f (abierto en 'wb') un PNG RGB888 de ancho x alto.

    frame: búfer RGB565 de ancho*alto*2 bytes, filas de arriba hacia abajo."""
    if len(frame) < ancho * alto * 2:
        raise ValueError("El búfer es más chico que la imagen")
    largo_fila = 1 + 3 * ancho
    if largo_fila > 5552:
        raise ValueError("Fila demasiado larga para un bloque")
    convertir = _fila_alto_primero if byte_alto_primero else _fila_bajo_primero
    fila = bytearray(largo_fila)       # fila[0] = 0: filtro "ninguno"
    adler = array("I", [1, 0])

    f.write(FIRMA_PNG)
    _chunk(f, b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0))

    largo_idat = 2 + alto * (5 + largo_fila) + 4
    f.write(struct.pack(">I", largo_idat))
    crc = _crc32(b"IDAT")
    cabecera_zlib = b"\x78\x01"         # deflate, ventana 32 KB, sin compresión
    f.write(b"IDAT")
    f.write(cabecera_zlib)
    crc = _crc32(cabecera_zlib, crc)
    for y in range(alto):
        convertir(frame, y * ancho * 2, fila, ancho)
        # Bloque "stored": BFINAL en la última fila, LEN y NLEN en little endian.
        bloque = struct.pack("<BHH", 1 if y == alto - 1 else 0, largo_fila, largo_fila ^ 0xFFFF)
        f.write(bloque)
        f.write(fila)
        crc = _crc32(fila, _crc32(bloque, crc))
        _adler(fila, largo_fila, adler)
        adler[0] %= 65521
        adler[1] %= 65521
    fin = struct.pack(">I", (adler[1] << 16) | adler[0])
    f.write(fin)
    crc = _crc32(fin, crc)
    f.write(struct.pack(">I", crc & 0xFFFFFFFF))
    _chunk(f, b"IEND", b"")
