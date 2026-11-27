# Firmware del termómetro del biberón (EP08)

MicroPython para una **Raspberry Pi Pico W** (o un ESP32) con una sonda **DS18B20**, dos LEDs y
un botón. Al pulsar el botón empieza la medición: los LEDs muestran al instante si la leche está
dentro del rango seguro, y el aparato manda la temperatura a Supabase según el contrato de [README_BASE_DATOS.md](../../README_BASE_DATOS.md).

| Archivo | Para qué |
|---|---|
| `main.py` | Arranque, bucle de LEDs y el agente (hilo de red) que habla con la base |
| `termometro.py` | Rango, medición con el botón, estado de los LEDs y cola de muestras (sin hardware: se prueba en la PC) |
| `hardware.py` | DS18B20 (lectura sin bloquear), LEDs y botón |
| `../comun/supabase_micro.py` | Auth, `registrar_senal`, `configuracion`, `comandos` y `eventos` (compartido) |
| `config.example.json` | Plantilla de `config.json` (credenciales: **no se sube a Git**) |

## Conexiones

| Pieza | Pin | Nota |
|---|---|---|
| DS18B20 DATA | **GP22** | Resistencia de **4.7 kΩ entre DATA y 3V3** (si el módulo no la trae) |
| DS18B20 VCC / GND | 3V3 / GND | |
| LED verde | **GP14** | Con resistencia de 220–330 Ω a GND |
| LED rojo | **GP15** | Con resistencia de 220–330 Ω a GND |
| Botón | **GP13** y GND | Sin resistencia: usa la pull-up interna |

## Medición con el botón

1. **Pulsar** el botón: empieza la medición. Los LEDs se encienden y la primera temperatura va a la
   base enseguida.
2. Mientras mide, manda una muestra cada minuto y otra al momento si la leche entra o sale del rango.
3. Termina sola a los `minutos_medicion` (**10** por defecto, en `config.json`), o antes si se
   **vuelve a pulsar** el botón.
4. Sin medir, los LEDs están apagados y no se envían temperaturas. La señal de vida sigue cada
   ~4 s con `{"midiendo": false}`, así que en la app el biberón aparece «En línea».

Si se pulsa con la leche aún fría, llega enseguida la alerta «Demasiado fría». Es lo esperado, y
el trigger no la repite hasta pasados `alerta_repeticion_min`.

## Qué muestran los LEDs

| LED | Significa (solo mientras mide) |
|---|---|
| Verde fijo | La leche está entre `temp_min` y `temp_max` (los bordes cuentan como dentro) |
| Rojo fijo | Demasiado caliente (> máximo) o demasiado fría (< mínimo) |
| Rojo parpadeando | La sonda no responde (cable suelto, falta la resistencia de 4.7 kΩ…) |
| Los dos parpadeando 2 s | Orden «Probar luz» desde la app (HU-07) |

Los LEDs los decide la placa con el **último rango que leyó de la base**, así que siguen
funcionando sin Wi-Fi. Antes del primer contacto usa 35–40 °C, el mismo rango por defecto que la
base (`crear_configuracion()`, CA-33.1).

## Cómo se comunica

| Qué | Cómo | Cada |
|---|---|---|
| Iniciar sesión | Cuenta del controlador C (`controlador-c@ecosistema.test`) | Al arrancar y al vencer el token |
| Su id | `dispositivos?codigo=eq.BIBERON-001` | Al arrancar |
| Rango seguro | Lee `configuracion` (`temp_min`, `temp_max`), que la app cambia en el panel del biberón | 2 s |
| Vista en vivo | `rpc('registrar_senal')` con `{"midiendo": true, "temperatura_biberon": t}` (o `aviso` si falla la sonda). Sin medir: `{"midiendo": false}` | ~4 s, siempre |
| Historial y alertas | `insert` en `eventos` (`tipo = 'temperatura_biberon'`, °C) | Solo mientras mide: al empezar, cada minuto y al entrar o salir del rango |
| Probar luz | Comando `probar_luz` → destello → `ejecutado`. Otra orden → `fallido` | 2 s |

Las alertas «Demasiado caliente» y «Demasiado fría» (y su envío por Telegram) las crea el trigger
de la base al recibir el evento, y las repite cada `alerta_repeticion_min`. El aparato **no**
inserta en `alertas`. Sin red, las muestras esperan en una cola en RAM (hasta 60) y se reenvían
con su `ocurrido_en` original (RNF-17).

## Instalación (Thonny o mpremote)

1. Grabar MicroPython en la placa. Los módulos `onewire` y `ds18x20` ya vienen incluidos.
2. Copiar `config.example.json` como `config.json` y completarlo: Wi-Fi, URL del proyecto, clave
   pública (anon) y contraseña de la cuenta del controlador C. Los pines ya vienen puestos
   (GP22, GP14, GP15 y GP13).
3. Subir a la raíz de la placa `main.py`, `termometro.py`, `hardware.py`,
   `../comun/supabase_micro.py` y `config.json`.
4. Reiniciar. En la app, el biberón pasa a «En línea» y el panel muestra la temperatura de la leche.

```powershell
mpremote cp firmware/biberon/main.py firmware/biberon/termometro.py firmware/biberon/hardware.py firmware/comun/supabase_micro.py firmware/biberon/config.json :
```

## Núcleos y conexión

| Núcleo (Pico W) | Qué hace |
|---|---|
| 0 (bucle principal) | Wi-Fi y Supabase |
| 1 (`_thread`) | Botón, sonda DS18B20 y LEDs, cada 50 ms |

La red va en el **núcleo 0** porque el chip Wi-Fi (CYW43) y la pila lwIP se atienden desde ahí.
La primera versión hacía lo contrario y la placa se desconectaba al rato. Además, para que la
conexión aguante:

- Se apaga el ahorro de energía del Wi-Fi (`wlan.config(pm=0xa11140)`).
- Cada vuelta de red empieza con `gc.collect()`: cada petición HTTPS deja basura en la RAM.
- Si se cae el Wi-Fi, reintenta cada 30 s sin bloquear. Si hay 10 errores seguidos (~20 s) aunque
  la placa crea estar conectada, fuerza una conexión nueva y una sesión nueva.

Si se vuelve a desconectar, en la consola de Thonny aparecen líneas `red: <error> · memoria
libre: <bytes>` y `wifi: …`. Si la memoria libre baja con el tiempo, es la RAM. Si aparece
`wifi: reconectando` seguido, es la señal del router.

## Pendiente de confirmar con hardware

- Primera prueba en la placa: se conectó, encendió el rojo a 24 °C y llegó la alerta por Telegram,
  pero se desconectó al rato. Falta confirmar que el cambio de núcleos lo resuelve.
- El controlador C de la arquitectura es un ESP32 que también maneja el móvil y el juguete. Este
  firmware corre solo en su placa; si se junta con los otros en un ESP32, hay que unir los bucles.
- `urequests` no valida el certificado TLS en la mayoría de las versiones de MicroPython.
