# ============================================================
# prueba_cableado.py · Prueba de hardware del juguete (MicroPython, Pico W)
# Autor: Javier Solano (JS)
#
# Revisa el cableado SIN Wi-Fi ni Supabase:
#   1. Enciende los LEDs 1 a 5, uno por uno.
#   2. Toca la melodía de recompensa en el buzzer.
#   3. Avisa si algún botón parece "siempre presionado".
#   4. Espera: cada botón que presiones se muestra en la consola y enciende su LED.
# Para terminar: botón Stop de Thonny (o Ctrl + C).
#
# Correrlo desde Thonny con "Run" (F5). NO guardarlo en la placa como main.py.
# Pines: los mismos de config.example.json del firmware.
# ============================================================

import time

from machine import PWM, Pin

PINES_BOTONES = [10, 11, 12, 13, 14]
PINES_LEDS = [16, 17, 18, 19, 20]
PIN_BUZZER = 15
MELODIA = [(523, 110), (659, 110), (784, 110), (0, 40), (1047, 260)]
VOLUMEN_DUTY = 16384   # 25 % de ciclo: se oye bien sin ser estridente

botones = [Pin(p, Pin.IN, Pin.PULL_UP) for p in PINES_BOTONES]
leds = [Pin(p, Pin.OUT, value=0) for p in PINES_LEDS]
buzzer = PWM(Pin(PIN_BUZZER))
buzzer.duty_u16(0)


def apagar_todo():
    for led in leds:
        led.value(0)
    buzzer.duty_u16(0)


def melodia():
    for frecuencia, duracion in MELODIA:
        if frecuencia:
            buzzer.freq(frecuencia)
            buzzer.duty_u16(VOLUMEN_DUTY)
        else:
            buzzer.duty_u16(0)
        time.sleep_ms(duracion)
    buzzer.duty_u16(0)


def paso_1_leds():
    print("\n--- PASO 1: LEDs ---")
    for i, led in enumerate(leds):
        print("LED %d (GP%d) encendido... ¿lo ves?" % (i + 1, PINES_LEDS[i]))
        led.value(1)
        time.sleep_ms(1200)
        led.value(0)
    print("Ahora los 5 juntos.")
    for led in leds:
        led.value(1)
    time.sleep_ms(1500)
    apagar_todo()
    print("Si alguno no encendió: revisa su pata larga (hacia la resistencia), la")
    print("resistencia y que su pata corta llegue al riel de tierra.")


def paso_2_buzzer():
    print("\n--- PASO 2: buzzer (GP%d) ---" % PIN_BUZZER)
    print("Debería sonar Do-Mi-Sol-Do.")
    melodia()
    time.sleep_ms(400)
    print("Si no sonó: revisa la resistencia de 100 ohm, el (+) del buzzer y que el (-)")
    print("llegue a tierra. Si solo hizo 'clic' o un pitido plano, puede ser un buzzer activo.")


def paso_3_botones_pegados():
    print("\n--- PASO 3: botones sin presionar ---")
    pegados = [i for i, b in enumerate(botones) if b.value() == 0]
    if not pegados:
        print("OK: ningún botón marca 'presionado' sin tocarlo.")
    for i in pegados:
        print("OJO: el botón %d (GP%d) marca PRESIONADO sin tocarlo." % (i + 1, PINES_BOTONES[i]))
        print("     Probablemente usa dos patas del mismo lado: usa patas en diagonal.")


def paso_4_botones():
    print("\n--- PASO 4: presiona cada botón (Stop para terminar) ---")
    anterior = [b.value() for b in botones]
    vistos = set()
    while True:
        for i, b in enumerate(botones):
            valor = b.value()
            if valor != anterior[i]:
                time.sleep_ms(30)              # antirrebote simple
                valor = b.value()
            if valor == 0 and anterior[i] == 1:
                vistos.add(i)
                print("Botón %d (GP%d) presionado -> se enciende el LED %d (GP%d)"
                      % (i + 1, PINES_BOTONES[i], i + 1, PINES_LEDS[i]))
                leds[i].value(1)
                if len(vistos) == len(botones):
                    print("   Ya probaste los 5 botones.")
            elif valor == 1 and anterior[i] == 0:
                leds[i].value(0)
            anterior[i] = valor
        time.sleep_ms(10)


try:
    print("Prueba de cableado del juguete")
    paso_1_leds()
    paso_2_buzzer()
    paso_3_botones_pegados()
    paso_4_botones()
except KeyboardInterrupt:
    print("\nPrueba terminada.")
finally:
    apagar_todo()
