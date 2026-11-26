# ============================================================
# probar_sensor.py · Prueba rápida de hardware en Thonny (sin Wi-Fi ni Supabase)
#
# Muestra el peso en gramos cada segundo y hace sonar el buzzer 1 s al empezar.
# Sirve para comprobar: cables de la celda, calibración y buzzer.
# Detener: botón Stop de Thonny.
# ============================================================

import json
import time

from buzzer import Buzzer
from colchon import Balanza
from hx711 import HX711

PIN_DT, PIN_SCK, PIN_BUZZER, TIPO_BUZZER = 14, 15, 16, "activo"   # "pasivo" si es de los que no suenan solos

try:
    cal = json.load(open("calibracion.json"))
except Exception:
    cal = {"offset": 0, "factor": 1.0}
    print("Sin calibracion.json: los números NO son gramos. Corra calibrar.py")

balanza = Balanza(HX711(PIN_DT, PIN_SCK), cal["offset"], cal["factor"])
bz = Buzzer(PIN_BUZZER, TIPO_BUZZER)

print("Buzzer 1 s...")
bz.fijar(True)
time.sleep(1)
bz.apagar()

try:
    while True:
        suma, n = 0, 0
        fin = time.ticks_add(time.ticks_ms(), 1000)
        while time.ticks_diff(fin, time.ticks_ms()) > 0:
            g = balanza.tomar()
            if g is not None:
                suma, n = suma + g, n + 1
            time.sleep_ms(20)
        print("Peso: %7.1f g" % (suma / n) if n else "Sin lectura del HX711 (revise DT/SCK/VCC/GND)")
finally:
    bz.apagar()
