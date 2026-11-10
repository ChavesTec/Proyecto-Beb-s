# Firmware del móvil de luces LED (EP05)

MicroPython para el **ESP32** (controlador C de la arquitectura) o una **Raspberry Pi Pico W**.
Adaptado del prototipo USB del compañero (`raspberry movil.py`): conserva sus cinco secuencias,
el cambio de velocidad sin reiniciar (CA-21.1) y el apagado total (CA-20.2), pero ahora trabaja
con Supabase según el contrato de [README_BASE_DATOS.md](../../README_BASE_DATOS.md).

| Archivo | Para qué |
|---|---|
| `main.py` | Arranque: Wi-Fi, hora NTP, hilo de red y bucle de luces |
| `luces.py` | Secuencias y estado (sin red ni hardware: se prueba en la PC) |
| `salidas.py` | Anillo WS2812B (`neopixel`) o LEDs sueltos por PWM |
| `../comun/supabase_micro.py` | Auth, `registrar_senal`, `configuracion` y `comandos` por HTTP (compartido con la seguridad) |
| `config.example.json` | Plantilla de `config.json` (credenciales: **no se sube a Git**) |

## Cómo se comunica

| Qué | Cómo | Cada |
|---|---|---|
| Iniciar sesión | Cuenta del controlador (`controlador-c@ecosistema.test`) | Al arrancar y al vencer el token |
| Su id | `dispositivos?codigo=eq.MOVIL-001` | Al arrancar |
| Encendido, secuencia, velocidad | Lee `configuracion` (`movil_encendido`, `movil_secuencia`, `movil_velocidad`) | 2 s |
| Señal de vida y estado real | `rpc('registrar_senal', {p_dispositivo, p_lectura})` | ~4 s |
| Prueba de luz (HU-07) | Comando `probar_luz` → destello de 2 s → `ejecutado` | 2 s |

`p_lectura` = `{"encendido": bool, "secuencia": n, "velocidad": n}` y, si está apagado, `"motivo"`
(`inicio`, `usuario`, `sin_conexion`). La app muestra esto como «El móvil informa…».

Tabla oficial número ↔ nombre (la misma de `app/config/valores.py`):

| `movil_secuencia` | Secuencia | `movil_velocidad` | Velocidad |
|---|---|---|---|
| 1 | Alternada | 1 | Lenta |
| 2 | Progresiva | 2 | Media |
| 3 | Colores por grupos | 3 | Rápida |
| 4 | Suave (respiración) | | |
| 5 | Ronda | | |

**Horarios (HU-22):** no los maneja la placa ni la PC. Se guardan en la tabla `horarios` desde la
app y pg_cron (`aplicar_horarios()`) cambia `configuracion` al inicio y al fin de cada intervalo.

**Seguridad:** si pasa 10 minutos sin contacto con Supabase, el móvil se apaga (sin red no le
llegaría la orden de apagar de un horario) y retoma lo que diga la base cuando vuelve la conexión.

## Instalación (Thonny o mpremote)

1. Grabar MicroPython en la placa (ESP32 o Pico W).
2. Copiar `config.example.json` como `config.json` y completarlo: Wi-Fi, URL del proyecto, clave
   pública (anon), correo y contraseña de la cuenta del controlador y código del dispositivo.
   `salida`: `"neopixel"` (anillo de 16 en GPIO23) o `"pwm"` (LEDs en `pines_pwm`).
3. Subir a la placa `main.py`, `luces.py`, `salidas.py`, `../comun/supabase_micro.py` y `config.json`
   (todos en la raíz de la placa).
4. Reiniciar: en la app el móvil pasa a «En línea» en unos segundos.

## Pendiente de confirmar con hardware

- Probado en la PC con hardware y red simulados (pruebas unitarias y contra Supabase local), **no
  en una placa real**. Falta verificar `_thread`, `urequests` sobre HTTPS y el anillo WS2812B.
- `urequests` no valida el certificado TLS en la mayoría de las versiones de MicroPython.
- Cambiar los LEDs PWM por el anillo, o al revés, requiere la aprobación del profesor (RNF-11).
- `interfaz movil codigo vs.py` (interfaz USB del compañero) ya no se usa con este firmware: sus
  funciones están en el panel del móvil de la app principal.
