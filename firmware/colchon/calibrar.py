# ============================================================
# calibrar.py · Calibración de la celda TAL220 + HX711 (se corre UNA vez en Thonny)
#
# Qué hace: mide el valor crudo con el colchón VACÍO (offset) y con un peso conocido
# (factor = cuentas por gramo) y los guarda en calibracion.json.
# Hay que repetirla si se cambia la forma de montar la celda.
#
# Antes de correrla: cambie PESO_CONOCIDO_G por lo que realmente va a poner
# (una pesa, una botella de agua de 1 L = ~1000 g pesada en una báscula de cocina).
# Use un peso de 1000 a 3000 g y colóquelo en el centro de la plataforma.
# ============================================================

import json
import time

from hx711 import HX711

PIN_DT = 14
PIN_SCK = 15
PESO_CONOCIDO_G = 1000


def promedio_crudo(hx, n=30):
    suma, cuenta = 0, 0
    while cuenta < n:
        v = hx.leer_crudo()
        if v is not None:
            suma += v
            cuenta += 1
        time.sleep_ms(20)
    return suma / n


hx = HX711(PIN_DT, PIN_SCK)
print("1) Deje el colchón VACÍO (sin nada encima). Midiendo en 5 s...")
time.sleep(5)
offset = promedio_crudo(hx)
print("   offset =", offset)

print("2) Ponga ahora %d g encima. Midiendo en 10 s..." % PESO_CONOCIDO_G)
time.sleep(10)
con_peso = promedio_crudo(hx)
factor = (con_peso - offset) / PESO_CONOCIDO_G
print("   con peso =", con_peso, " factor =", factor)

if abs(factor) < 1:
    print("ERROR: casi no cambió la lectura. Revise cables y que la celda esté bien montada.")
else:
    if factor < 0:
        print("Aviso: el factor salió NEGATIVO (A+ y A- invertidos). Funciona igual, "
              "pero puede intercambiar los cables blanco y verde.")
    with open("calibracion.json", "w") as f:
        json.dump({"offset": offset, "factor": factor}, f)
    print("Listo: calibracion.json guardado. Quite el peso y corra probar_sensor.py")
