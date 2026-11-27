# Firmware del termómetro del biberón (EP08)

MicroPython para una **Raspberry Pi Pico W** (o un ESP32) con una sonda **DS18B20** y dos LEDs.
Los LEDs muestran al instante si la leche está dentro del rango seguro, y el aparato manda la
temperatura a Supabase según el contrato de [README_BASE_DATOS.md](../../README_BASE_DATOS.md).

| Archivo | Para qué |
|---|---|
| `main.py` | Arranque, bucle de LEDs y el agente (hilo de red) que habla con la base |
| `termometro.py` | Rango, estado de los LEDs y cola de muestras (sin hardware: se prueba en la PC) |
| `hardware.py` | DS18B20 (lectura sin bloquear) y LEDs |
| `../comun/supabase_micro.py` | Auth, `registrar_senal`, `configuracion`, `comandos` y `eventos` (compartido) |
| `config.example.json` | Plantilla de `config.json` (credenciales: **no se sube a Git**) |

## Conexiones

| Pieza | Pin | Nota |
|---|---|---|
| DS18B20 DATA | **GP22** | Resistencia de **4.7 kΩ entre DATA y 3V3** (si el módulo no la trae) |
| DS18B20 VCC / GND | 3V3 / GND | |
| LED verde | **GP14** | Con resistencia de 220–330 Ω a GND |
| LED rojo | **GP15** | Con resistencia de 220–330 Ω a GND |

## Qué muestran los LEDs

| LED | Significa |
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
| Vista en vivo | `rpc('registrar_senal')` con `{"temperatura_biberon": t}` (o `aviso` si falla la sonda) | ~4 s |
| Historial y alertas | `insert` en `eventos` (`tipo = 'temperatura_biberon'`, °C) | 1 min, y enseguida al entrar o salir del rango |
| Probar luz | Comando `probar_luz` → destello → `ejecutado`. Otra orden → `fallido` | 2 s |

Las alertas «Demasiado caliente» y «Demasiado fría» (y su envío por Telegram) las crea el trigger
de la base al recibir el evento, y las repite cada `alerta_repeticion_min`. El aparato **no**
inserta en `alertas`. Sin red, las muestras esperan en una cola en RAM (hasta 60) y se reenvían
con su `ocurrido_en` original (RNF-17).

## Instalación (Thonny o mpremote)

1. Grabar MicroPython en la placa. Los módulos `onewire` y `ds18x20` ya vienen incluidos.
2. Copiar `config.example.json` como `config.json` y completarlo: Wi-Fi, URL del proyecto, clave
   pública (anon) y contraseña de la cuenta del controlador C. Los pines ya vienen puestos
   (GP22, GP14 y GP15).
3. Subir a la raíz de la placa `main.py`, `termometro.py`, `hardware.py`,
   `../comun/supabase_micro.py` y `config.json`.
4. Reiniciar. En la app, el biberón pasa a «En línea» y el panel muestra la temperatura de la leche.

```powershell
mpremote cp firmware/biberon/main.py firmware/biberon/termometro.py firmware/biberon/hardware.py firmware/comun/supabase_micro.py firmware/biberon/config.json :
```

## Pendiente de confirmar con hardware

- Probado en la PC con hardware y red simulados (`tests/test_firmware_biberon.py`), **no en una
  placa real ni contra Supabase**.
- El controlador C de la arquitectura es un ESP32 que también maneja el móvil y el juguete. Este
  firmware corre solo en su placa; si se junta con los otros en un ESP32, hay que unir los bucles.
- `urequests` no valida el certificado TLS en la mayoría de las versiones de MicroPython.
