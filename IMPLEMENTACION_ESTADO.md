# Estado de la implementación · app de escritorio y Telegram

Fecha: 2026-11-04 · Rama: `Development`

## Qué se verificó y qué no

| Verificación | Resultado |
|---|---|
| `pytest`: 99 pruebas de la app, con dobles del SDK de Supabase | **99 pasan, 0 fallan** (Python 3.14.7, Windows 11) |
| Prueba de humo de la UI: la app real arranca, intenta iniciar sesión contra un servidor inexistente, recorre las 11 pantallas con datos simulados y cierra sesión | Sin excepciones; «No hay conexión con Supabase» en el login; 0 pantallas privadas tras cerrar sesión |
| Realtime sin servidor | Pasa a «degradado» en unos 9 s y su hilo se detiene sin fugas |
| `pruebas/02`, `pruebas/03`, `pruebas/04` contra Supabase local | **No ejecutadas por falta de configuración**: este equipo no tiene Docker ni Node.js |
| Envío real por Telegram y latencias de RNF-01/RNF-02 | **No ejecutados**: falta el token del bot, el despliegue de las funciones y el Vault |
| Edge Functions (TypeScript/Deno) | **No ejecutadas ni compiladas**: no hay Deno ni Supabase CLI en este equipo |

Nada se ejecutó contra el proyecto remoto ni contra producción: no se hizo `db push`,
no se desplegaron funciones y no se cambiaron ajustes.

## Leyenda

- ✅ **Implementada y verificada** (pruebas unitarias o prueba de humo; sin servicios reales).
- 🟡 **Implementada, sin verificar contra servicios reales** (Supabase, hardware o Telegram).
- ⏳ **Pendiente por una dependencia externa.**
- ⛔ **Fuera del alcance actual.**

## Por historia

| HU | Función | Estado | Notas |
|---|---|---|---|
| HU-01 | Registro, contraseña ≥ 8, «El correo ya está registrado» | ✅ validación · 🟡 Auth | Con confirmación por correo activa se detecta el correo repetido (usuario sin identidades) y se avisa que revise el correo |
| HU-02 | Inicio y cierre de sesión, mensaje único «Correo o contraseña incorrectos» | ✅ · 🟡 Auth | Al cerrar sesión se destruyen todas las pantallas privadas; el JWT vencido devuelve al inicio de sesión |
| HU-03 | Crear, editar, seleccionar, eliminar (RPC) y compartir perfiles | 🟡 | Confirmación antes de eliminar. La lista de accesos muestra identificadores, no correos: RLS de `usuarios` solo deja ver la propia fila |
| HU-04 | Registrar dispositivo con código (`registrar_dispositivo`) | 🟡 | Errores de la RPC traducidos y probados |
| HU-05 | Asignar, quitar o reasignar perfil | ✅ consulta · 🟡 RLS | Solo `update dispositivos.perfil_id`; el historial no se toca (lo garantiza la base) |
| HU-06 | En línea / fuera de línea (60 s) / sin datos | ✅ | Advertencia roja si el colchón en siesta o la seguridad armada quedan fuera de línea, e indica si la base ya registró la alerta |
| HU-07 | App local, lecturas, controles de prueba | 🟡 | Botones «Probar luz», «Probar buzzer» y «Tomar foto» según el hardware descrito. El firmware que los ejecuta no está en el repositorio |
| HU-08 | Temperatura y humedad | 🟡 | De `ultima_lectura`; si no viene, último evento del historial con su antigüedad |
| HU-09 | Umbrales con validación mín < máx y `23514` | ✅ validación · 🟡 | Muestra si los valores son los predeterminados o los guardados |
| HU-10 | Ventana de movimiento | 🟡 | Horarios tipo `movimiento`; aviso de que sin ventana no se registra movimiento |
| HU-11 | Luz nocturna 0–100 % | 🟡 | `configuracion.luz_intensidad`; la cuna la lee al reiniciar (firmware) |
| HU-12 | Hablar al bebé | ⛔ / ⏳ | No hay firmware de la cuna ni canal de audio en vivo en el repositorio. No se muestra un botón decorativo |
| HU-13 | Audios MP3 ≤ 5 MB, reproducir y detener | ✅ validación · 🟡 | Parámetros de `audio_reproducir` propuestos (`audio_id`, `archivo_path`, `nombre`): confirmar con el firmware |
| HU-14 | «Conectado a la cuna» / «Independiente» | 🟡 | Clave `conectado_cuna` de `ultima_lectura`, confirmada por el contrato |
| HU-15 | Activar siesta con snapshot | 🟡 | Comando `activar_siesta`; si falla se muestra el `resultado` exacto (p. ej. «No se detecta al bebé») |
| HU-16 | Alarma anti-robo | ⏳ hardware | Suena localmente en el colchón; la app solo la muestra |
| HU-17 | Alerta anti-robo por Telegram | 🟡 código · ⏳ configuración | Ver Telegram |
| HU-18 | Desactivar siesta, quién y cuándo | 🟡 | RPC `desactivar_siesta`; muestra «usted» u «otro usuario» (RLS no deja leer correos ajenos) |
| HU-19 | Colchón independiente | ⏳ hardware | Sin cambios en la app |
| HU-20 | Encender/apagar móvil y elegir secuencia | 🟡 | Secuencias 1–6 como número: el firmware define cuántas hay |
| HU-21 | Tres velocidades | 🟡 | No reiniciar la secuencia depende del firmware |
| HU-22 | Horarios del móvil, rechazo de traslapes | 🟡 | El traslape lo rechaza la base (`23P01`) y se muestra su mensaje |
| HU-23 | Armar/desarmar y horario | 🟡 | Botón grande con confirmación al desarmar |
| HU-24/25 | Puerta y presencia | 🟡 | Se muestran los eventos que la base guardó (solo con seguridad armada) |
| HU-26 | Foto de evidencia, intervalo | 🟡 | Intervalo editable; la captura la hace el controlador |
| HU-27 | Alerta silenciosa con foto | 🟡 código · ⏳ configuración | `enviar-alerta` usa `sendPhoto` con URL firmada de 5 min |
| HU-28 | Galería, orden descendente, «No hay capturas para el rango seleccionado» | 🟡 | Miniaturas por URL firmada de 120 s; nunca URLs públicas (probado) |
| HU-29/30 | Rondas y recompensa | ⏳ firmware | La base no define una orden para iniciar rondas: la app no la inventa. Muestra `boton_activo` si el firmware lo envía y los `juguete_acierto` registrados |
| HU-31 | Tiempo por ronda y volumen | 🟡 | `configuracion` |
| HU-32/33 | Temperatura del biberón y rango | 🟡 | «Demasiado caliente / fría» según la lectura y las alertas de la base |
| HU-34 | Cronómetro de toma | 🟡 | El inicio lo fija la base; la parada no puede quedar antes del inicio aunque el reloj del PC vaya atrasado |
| HU-35 | Cantidad en ml (rechaza vacío o negativo) | ✅ validación · 🟡 | Solo para tomas finalizadas |
| HU-36 | Recordatorios por intervalo u hora fija | 🟡 | La app muestra cuándo la base creó el aviso; la entrega se ve en «Alertas» |
| HU-37 | Vincular Telegram con código, aviso «No recibirás alertas por Telegram» | ✅ aviso · 🟡 código · ⏳ configuración | RPC y webhook nuevos |
| HU-38 | Envío automático, estado, reintentos | 🟡 código · ⏳ configuración | Trigger + `pg_net` + pg_cron; reintento hasta 24 h / 30 intentos |
| HU-39 | Historial con filtros, 50 por página, «No hay registros para el rango seleccionado» | ✅ consulta · 🟡 | Fechas en días de Costa Rica convertidas a UTC |
| HU-40 | CSV UTF-8 con las 7 columnas | ✅ | Exporta todas las páginas del filtro aplicado; UTF-8 con BOM; sin archivo si no hay datos |

## Discrepancias encontradas en la documentación

1. **README_TELEGRAM.md** pide a los dispositivos «insertar una fila en `alertas`»; README_BASE_DATOS.md
   y *En resumen* dicen que no, porque el trigger de `eventos` ya la crea. Se siguió el contrato de la
   base: la app no inserta en `alertas` ni en `eventos`.
2. **README_TELEGRAM.md** pide «Verify JWT activado» para `enviar-alerta`. Como ahora la llama la base
   con `pg_net`, las dos funciones validan un secreto compartido y se declaran con `verify_jwt = false`.
3. **Realtime** publica solo `dispositivos`, `configuracion`, `comandos` y `alertas`. `eventos`, `capturas`,
   `tomas` y `snapshots_peso` se consultan al abrir cada pantalla y con polling. No se cambió la publicación.
4. **`ultima_lectura`** es JSON libre: solo `conectado_cuna` está en el contrato. La app reconoce nombres
   razonables (`temperatura`, `humedad`, `peso`, `boton_activo`…) y muestra cualquier otra clave tal cual.
5. **Reintentos «hasta enviarse» (CA-38.3)**: se limitaron a 24 h y 30 intentos para no reenviar avisos
   viejos sin fin. Ajustable en `reintentar_alertas()`.
6. El SRS menciona un «Tiempo de retención 90 días [a confirmar]»; la base ya purga a los 90 días.

## Pendiente

- Aplicar las migraciones en el proyecto oficial y configurar Telegram (pasos en README.md). Requiere autorización.
- Correr `pruebas/02`, `03` y `04` en Supabase local con Docker y la app contra esa base.
- Confirmar con los firmwares: claves de `ultima_lectura`, parámetros de `audio_reproducir`, número de secuencias del móvil.
- HU-12 (voz): firmware de la cuna y canal de audio.
- Borrado de fotos de más de 90 días (Edge Function aparte, ya señalado en README_BASE_DATOS.md).
