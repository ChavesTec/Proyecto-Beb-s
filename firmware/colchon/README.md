# Firmware del colchón inteligente (EP04)

MicroPython para la **Raspberry Pi Pico W** (o un ESP32) con celda de carga **TAL220 de 5 kg**,
amplificador **HX711** y un buzzer propio. Cubre HU-15 a HU-19 trabajando con Supabase según el
contrato de [README_BASE_DATOS.md](../../README_BASE_DATOS.md) ("Modo siesta").

| Archivo | Para qué |
|---|---|
| `main.py` | Arranque: Wi-Fi, hilo de red y bucle principal (peso, alarma, buzzer) |
| `colchon.py` | Lógica local sin red: filtro, snapshot, alarma anti-robo, siesta, cola de eventos |
| `agente.py` | Hilo de red: configuración, comandos, señal de vida y eventos |
| `nube.py` | Lo que el colchón agrega al cliente de Supabase (snapshot, evento, configuración) |
| `hx711.py` | Lector del HX711 (24 bits, ganancia 128) |
| `buzzer.py` | Buzzer activo o pasivo |
| `supabase_micro.py` | Copia de `firmware/movil/supabase_micro.py` con un cambio: `ErrorSupabase.texto` |
| `calibrar.py` | Se corre una vez en Thonny: calcula `calibracion.json` (offset y factor) |
| `probar_sensor.py` | Prueba de hardware sin red: muestra gramos y suena el buzzer |
| `config.example.json` | Plantilla de `config.json` (**no se sube a Git**) |

## Cómo se comunica

| Qué | Cómo | Cada |
|---|---|---|
| Sesión | Cuenta del controlador que maneja el colchón | Al arrancar y al vencer el token |
| Su id | `dispositivos?codigo=eq.<codigo_dispositivo>` | Al arrancar |
| Ajustes y estado de siesta | Lee `configuracion` (`siesta_activa`, `peso_minimo_g`, `alarma_caida_pct`) | 2 s |
| Señal de vida | `rpc('registrar_senal')` con `{peso, conectado_cuna, siesta, alarma}` | 5 s |
| Muestra para el historial | `insert` en `eventos` (`peso`, g) | 60 s |
| **HU-15** Activar siesta | Comando `activar_siesta` → promedia el peso → `insert` en `snapshots_peso`. Si la base lo rechaza (`No se detecta al bebé`), marca el comando `fallido` con ese texto | Al llegar el comando |
| **HU-16** Alarma | Local: suena el buzzer **sin consultar a la base** (RNF-16) e inserta el evento `alarma_antirrobo` (el trigger crea la alerta crítica) | Al ocurrir |
| **HU-18** Desactivar | Comando `desactivar_siesta` (lo crea el RPC `desactivar_siesta`) o `siesta_activa = false` → apaga buzzer | Al llegar |
| HU-07 Prueba | Comando `probar_buzzer` → suena 1 s | Al llegar |

El firmware **no inserta en `alertas`**: el trigger de la base lo hace al recibir `alarma_antirrobo`
(así no salen dos mensajes de Telegram).

## Reglas de la alarma

- Siesta activa con base `B` y caída `C` % (`alarma_caida_pct`, por defecto 30 %).
- Se dispara si el peso filtrado queda en `B × (1 − C/100)` o menos durante `segundos_confirmacion`
  (2 s por defecto). Una caída breve o menor al umbral no dispara (CA-16.2).
- Una vez disparada **no se apaga sola** (CA-16.3): solo con la desactivación de la siesta.
- Si el sensor deja de responder, **no** se dispara la alarma; `ultima_lectura` trae `aviso`.
- La siesta se guarda en `siesta.json`: si la placa se reinicia, sigue vigilando con el mismo peso base.
- Sin Wi-Fi la alarma suena igual; los eventos quedan en cola y se envían al volver la red
  (conservando su hora original, sin duplicarse).

## Conexión (Pico W)

| Elemento | Pico W |
|---|---|
| HX711 VCC | 3V3 (pin 36) |
| HX711 GND | GND (pin 18) |
| HX711 DT | GP14 (pin 19) |
| HX711 SCK | GP15 (pin 20) |
| Celda: rojo / negro / blanco / verde | E+ / E− / A− / A+ del HX711 |
| Buzzer (con transistor y R 1 kΩ) | GP16 (pin 21), + a VSYS (pin 39), emisor a GND (pin 23) |
| Detección de cuna (divisor 10 kΩ / 20 kΩ desde los 5 V de la cuna) | GP22 (pin 29) |

Los pines se cambian en `config.json` (`pin_dt`, `pin_sck`, `pin_buzzer`, `pin_deteccion_cuna`).
`pin_deteccion_cuna: null` informa siempre «Independiente».

## Instalación (Thonny o mpremote)

1. Grabar MicroPython en la Pico W.
2. Copiar `config.example.json` como `config.json` y completarlo (Wi-Fi, URL, clave anon, cuenta del
   controlador y `codigo_dispositivo` del colchón).
3. Subir a la placa: `main.py`, `colchon.py`, `agente.py`, `nube.py`, `hx711.py`, `buzzer.py`,
   `supabase_micro.py`, `config.json`, `calibrar.py`, `probar_sensor.py`.
4. Correr `probar_sensor.py` y luego `calibrar.py` (una vez). Se crea `calibracion.json`.
5. Reiniciar: en la app el colchón pasa a «En línea» en unos segundos.

## Pruebas

`python -m pytest tests/test_firmware_colchon.py -v` (37 pruebas con hardware y Supabase simulados;
cada una indica el CA que cubre).

## Pendiente de confirmar con hardware

- Probado en la PC con hardware y red simulados, **no en una placa real**. Falta verificar el timing
  del HX711, `_thread` y `urequests` sobre HTTPS en la Pico W.
- `urequests` no valida el certificado TLS en la mayoría de las versiones de MicroPython.
- Los umbrales de la alarma (30 %, 500 g) son los de la base; hay que calibrarlos con la maqueta.
- Un solo TAL220 mide bien si la carga está centrada en la plataforma; recalibrar al cambiar el montaje.
