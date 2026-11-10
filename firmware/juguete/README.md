# Firmware del juguete interactivo (EP07 · HU-29, HU-30, HU-31)

Responsable: **Javier Solano (JS)** · MicroPython para la **Raspberry Pi Pico W**
(también funciona en un ESP32 cambiando los pines en `config.json`).

El juguete enciende el LED de uno de los 5 botones al azar. Si el bebé presiona ese
botón suena una melodía de recompensa y empieza otra ronda; si presiona otro, no pasa
nada; si se acaba el tiempo, empieza otra ronda. Las rondas son **locales**, como dice
la arquitectura: empiezan solas al encender el juguete y siguen aunque no haya internet.

| Archivo | Para qué |
|---|---|
| `juego.py` | Lógica del juego, sin red ni hardware (se prueba en la PC) |
| `salidas.py` | Botones con antirrebote, LEDs y buzzer pasivo con volumen |
| `main.py` | Arranque: Wi-Fi, hora NTP, juego en el 2.º núcleo y red en el principal |
| `supabase_micro.py` | Cliente de Supabase del móvil (LM) + `insertar_evento` y `leer_config` por columnas |
| `config.example.json` | Plantilla de `config.json` (credenciales: **no se sube a Git**) |

Pruebas: `tests/test_firmware_juguete.py` (27 pruebas con hardware y red simulados).

## Criterios de aceptación

| Criterio | Dónde se cumple |
|---|---|
| CA-29.1 Se enciende el LED de 1 de los 5 botones al azar | `Juego._iniciar_ronda` (no repite el mismo botón dos veces seguidas) |
| CA-30.1 Acierto → recompensa sonora y ronda nueva | `Juego._acierto` y `_avanzar_melodia` |
| CA-30.2 Botón incorrecto → sin sonido y el LED sigue | `Juego.actualizar` (cuenta el fallo y no hace nada más) |
| CA-30.3 Sin acierto en el tiempo → ronda nueva | `Juego.actualizar` (pausa de 0,7 s y otra ronda) |
| CA-31.1 Un tiempo nuevo se usa desde la siguiente ronda | `Juego.aplicar_config` guarda el valor; `_iniciar_ronda` lo aplica |

La app (panel del juguete de LM) ya muestra el botón iluminado, los aciertos y permite
cambiar el tiempo por ronda y el volumen.

## Conexiones (Pico W, valores por defecto)

| Componente | Pines | Conexión |
|---|---|---|
| 5 pulsadores | GP10, GP11, GP12, GP13, GP14 | Un lado al GPIO, el otro a **GND** (pull-up interno, no lleva resistencia) |
| 5 LEDs | GP16, GP17, GP18, GP19, GP20 | GPIO → resistencia **220 Ω** → ánodo (pata larga); cátodo → **GND** |
| Buzzer pasivo | GP15 | GPIO → resistencia 100 Ω → (+) del buzzer; (−) → **GND** |

El botón 1 es el de GP10 y su LED el de GP16, y así en orden. Estos pines no chocan con
los del móvil de luces (GP2–GP7) ni con los del Wi-Fi de la Pico W (GP23, 24, 25, 29).
En el ESP32 de la arquitectura serían botones 32, 33, 25, 26, 27; LEDs 16, 17, 18, 19, 21;
buzzer 22.

## Cómo se comunica con la base

| Qué | Cómo | Cada |
|---|---|---|
| Iniciar sesión | Cuenta del controlador (`controlador-c@ecosistema.test`) | Al arrancar |
| Su id | `dispositivos?codigo=eq.JUGUETE-001` | Al arrancar |
| Tiempo por ronda y volumen | Lee `configuracion` (`juguete_tiempo_ronda_s`, `juguete_volumen`) | 2 s |
| Vista en vivo | `registrar_senal` con `{"boton_activo", "ronda", "aciertos", "fallos", "tiempo_ronda_s", "volumen"}` | 5 s, y enseguida si cambia la ronda |
| Acierto | `eventos` tipo `juguete_acierto`: `valor` = segundos que tardó, `unidad` = `s`, `descripcion` = botón | Al ocurrir |
| Pruebas (HU-07) | Comandos `probar_luz` (5 LEDs, 2 s) y `probar_buzzer` (melodía) | 2 s |

Sin internet, los aciertos se guardan (hasta 50) y se envían al volver, con su hora
original y sin duplicarse (RNF-17).

## Instalación (Thonny)

1. Grabar MicroPython para **Pico W** (archivo `.uf2` de micropython.org).
2. Copiar `config.example.json` como `config.json` y completar: Wi-Fi (2,4 GHz), URL del
   proyecto, clave **publishable**, contraseña de `controlador-c` y, si cambiaste el
   cableado, los pines.
3. Subir a la placa `main.py`, `juego.py`, `salidas.py`, `supabase_micro.py` y `config.json`.
4. Reiniciar. En la app, el juguete pasa a «En línea» y se ve qué botón está iluminado.

## Pendiente

- Probar en la placa real contra el proyecto oficial (hecho solo con hardware simulado).
- La arquitectura pone móvil, juguete y biberón en **una sola placa** (controlador C).
  Este firmware corre solo; para juntarlos hay que hacer un `main.py` común. Este
  `supabase_micro.py` puede reemplazar al del móvil sin cambiar su código.
- `urequests` no valida el certificado TLS en la mayoría de las versiones de MicroPython.
