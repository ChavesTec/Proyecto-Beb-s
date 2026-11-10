# Firmware del aparato de seguridad (EP06)

MicroPython para una **Raspberry Pi Pico W** con un sensor ultrasónico **HC-SR04** y una cámara
**OV7670** sin FIFO. Basado en el prototipo `Aparato-seguridad.py` (captura con PIO + DMA), pero
ahora trabaja con Supabase según el contrato de [README_BASE_DATOS.md](../../README_BASE_DATOS.md).

| Archivo | Para qué |
|---|---|
| `main.py` | Arranque, bucle del sensor, Wi-Fi sin bloqueo y el agente que habla con la base |
| `vigilancia.py` | Reglas de armado, intervalo entre fotos y cola en flash (sin hardware: se prueba en la PC) |
| `imagen.py` | RGB565 → PNG sin comprimir, fila por fila (se prueba en la PC) |
| `camara.py` | OV7670: registros por I2C, captura por PIO + DMA, diagnóstico |
| `ultrasonico.py` | HC-SR04 con `machine.time_pulse_us` |
| `../comun/supabase_micro.py` | Auth, `registrar_senal`, `configuracion`, `comandos`, Storage y `eventos` (compartido con el móvil) |
| `config.example.json` | Plantilla de `config.json` (credenciales: **no se sube a Git**) |

## Conexiones

| Pieza | Pin | Pico W |
|---|---|---|
| OV7670 D0..D7 | datos | GP0..GP7 (consecutivos, D0 en GP0) |
| OV7670 PCLK / VSYNC / HREF | sincronía | GP8 / GP9 / GP10 |
| OV7670 XCLK | reloj (~25 MHz por PWM) | GP11 |
| OV7670 SIOD / SIOC | I2C0 (pull-up 4.7 kΩ a 3.3 V) | GP12 / GP13 |
| OV7670 RESET / PWDN | | 3.3 V / GND |
| HC-SR04 TRIG | | GP16 |
| HC-SR04 ECHO | **con divisor de voltaje** (sale a 5 V) | GP15 |
| HC-SR04 VCC | | VBUS (5 V) |

## Cómo se comunica

| Qué | Cómo | Cada |
|---|---|---|
| Iniciar sesión | Cuenta del controlador A (`controlador-a@ecosistema.test`) | Al arrancar y al vencer el token |
| Su id | `dispositivos?codigo=eq.SEGURIDAD-001` | Al arrancar |
| Armado e intervalo | Lee `configuracion` (`seguridad_armada`, `seguridad_intervalo_foto_s`) | 2 s |
| Señal de vida | `rpc('registrar_senal', {p_dispositivo, p_lectura})` | ~4 s |
| Presencia | `insert` en `eventos` (`tipo = 'presencia'`) | Al ocurrir |
| Foto de evidencia | Sube `capturas/<dispositivo_id>/<fecha>-<n>.png` y la cita en `foto_path` | Máx. 1 cada `seguridad_intervalo_foto_s` |
| Foto a pedido | Comando `tomar_foto` → foto + evento → `ejecutado` | 2 s |

`p_lectura` = `{"armada", "camara": "lista"|"sin_camara", "sensor": "ok"|"sin_respuesta",
"presencia", "pendientes", "distancia_cm"}`.

**Reglas:**

- **Desarmada**, no toma fotos ni envía presencias (la base las descartaría, CA-23.2). Un
  `tomar_foto` se marca `fallido` con el motivo.
- **Armada**, cada presencia nueva genera un evento. Si la presencia sigue, se toma como máximo
  una foto cada `seguridad_intervalo_foto_s` segundos (CA-26.3, por defecto 30 s).
- **Sin red**, los eventos y las fotos esperan en `pendientes/` (flash) y se reenvían con su hora
  original (RNF-17). Si la flash se llena, se borran las fotos más viejas, no las nuevas.
- El último armado conocido se guarda en `estado.json`: si arranca sin red, sigue vigilando.

**Formato de la foto:** PNG RGB de 154×120 sin comprimir (~56 KB). La Pico no tiene RAM para
JPEG ni para 640×480 (serían ~600 KB en RGB565, y la Pico tiene 264 KB). El bucket `capturas`
acepta `image/png` desde la migración `20261110000000_capturas_png.sql`.

## Instalación (Thonny o mpremote)

1. Grabar MicroPython 1.23 o superior en la Pico W.
2. Copiar `config.example.json` como `config.json` y completarlo: Wi-Fi, URL del proyecto, clave
   pública (anon), correo y contraseña del controlador A y código del dispositivo.
3. Subir a la raíz de la placa `main.py`, `camara.py`, `ultrasonico.py`, `imagen.py`,
   `vigilancia.py`, `../comun/supabase_micro.py` y `config.json`.
4. Reiniciar: en la app la seguridad pasa a «En línea» en unos segundos.

## Ajustes de la cámara

- **Colores raros** (rojo↔azul, tonos verdosos): poner `"patron_de_prueba": true`. Al detectar
  presencia guarda `prueba_alto_primero.png` y `prueba_bajo_primero.png` con barras de colores
  (no los sube). El que se vea bien dice qué valor poner en `"byte_alto_primero"`.
- **Imagen torcida o negra**: `"diagnostico": true` imprime al arrancar el porcentaje de unos en
  cada línea D0..D7 (una línea sin cambios es un cable suelto) y, con el patrón de prueba, cuántos
  bytes trae cada línea (deben ser 308).

## Pendiente de confirmar con hardware

- Probado en la PC con hardware y red simulados (`tests/test_firmware_seguridad.py`), **no en una
  placa real**: falta verificar `viper`, `binascii.crc32`, `urequests` sobre HTTPS y la memoria
  libre con Wi-Fi y TLS activos (la foto de 56 KB se lee completa para subirla).
- El orden de bytes por defecto (`byte_alto_primero: true`) es el que indica la hoja de datos de
  la OV7670; el prototipo usaba el contrario. Confirmar con el patrón de prueba.
- `urequests` no valida el certificado TLS en la mayoría de las versiones de MicroPython.
