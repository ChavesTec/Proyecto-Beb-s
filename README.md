# Ecosistema de dispositivos para bebés · Aplicación de escritorio

Aplicación de escritorio en **Python + Tkinter** para administrar la cuna, el colchón,
el móvil de luces, la seguridad de la habitación, el juguete interactivo y el biberón.
Trabaja sobre la base Supabase descrita en [README_BASE_DATOS.md](README_BASE_DATOS.md):
Auth, PostgREST, Realtime y Storage privado, con RLS como frontera de seguridad.

El estado real de cada función (verificada, sin verificar contra servicios reales,
pendiente o fuera de alcance) está en [IMPLEMENTACION_ESTADO.md](IMPLEMENTACION_ESTADO.md).

---

## Requisitos

- Windows 10+ o Raspberry Pi OS, **Python 3.10 o superior** con Tkinter
  (en Raspberry Pi OS: `sudo apt install python3-tk`).
- Un proyecto Supabase con las migraciones de `supabase/migrations/` aplicadas,
  o Supabase local con Docker (ver [TUTORIAL_PRUEBAS_DOCKER.md](TUTORIAL_PRUEBAS_DOCKER.md)).

## Instalación

Desde la raíz del repositorio:

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

En Raspberry Pi OS / Linux use `.venv/bin/python` en lugar de `.venv\Scripts\python.exe`.
Con [uv](https://docs.astral.sh/uv/) también sirve: `uv venv .venv` y
`uv pip install --python .venv/Scripts/python.exe -r requirements.txt`.

Dependencias (`requirements.txt`): `supabase==2.33.0` (la misma versión que usan las
pruebas de `pruebas/`), `python-dotenv`, `tzdata` (zona `America/Costa_Rica` en Windows),
`Pillow` (miniaturas JPEG de la galería) y `pytest`.

## Configuración (`.env`)

Copie `.env.example` como `.env` y complete:

```env
SUPABASE_URL=https://<su-proyecto>.supabase.co
SUPABASE_ANON_KEY=<clave pública anon/publishable>
TELEGRAM_BOT_USUARIO=ecosistema_bebe_g1_bot
```

- Solo la **URL** y la **clave pública** (Dashboard → Project Settings → API).
  La app rechaza al arrancar una clave `service_role` o `sb_secret_…`.
- Para Supabase local: `SUPABASE_URL=http://127.0.0.1:44321` y la `ANON_KEY` que imprime
  `npx -y supabase@3.0.0 status`. Un proyecto remoto debe usar HTTPS.
- `.env` está en `.gitignore`. Nunca suba contraseñas, la clave `service_role` ni el token del bot.
- Si falta la configuración, la app muestra una pantalla que explica cómo completarla:
  nunca simula una conexión ni muestra datos de demostración.

## Ejecución

```bash
.venv\Scripts\python.exe -m app.main
```

La sesión vive solo en memoria: no se guardan contraseñas ni tokens en disco y al cerrar
la app hay que volver a iniciar sesión.

## Pruebas

Pruebas de la aplicación (no necesitan Supabase ni credenciales; usan dobles del SDK):

```bash
.venv\Scripts\python.exe -m pytest
```

Cubren: validación de correo y contraseña de 8 caracteres, mensaje único ante credenciales
incorrectas, sesión expirada, filtrado por perfil/tipo y permisos, reasignación sin tocar el
historial, regla de 60 s sin señal, rangos de temperatura/humedad y error `23514`, estados de
comandos, que la app nunca inserte en `alertas` ni en `eventos`, paginación de 50 y filtros
de fecha, CSV (columnas, UTF-8 con BOM, comas, saltos de línea y tildes, sin archivo vacío),
URLs firmadas del bucket privado, configuración faltante, errores de red/RLS/RPC faltante,
resultados de hilos entregados al hilo de Tkinter y degradación/cierre de Realtime.

Pruebas contra Supabase **local** (⚠️ nunca contra producción; crean datos de prueba):

| Archivo | Qué prueba |
|---|---|
| `pruebas/02_verificar_base_datos.sql` | Lógica SQL de las 5 migraciones base (135 verificaciones) |
| `pruebas/03_probar_servicios.py` | Auth, API, Storage, Realtime y pg_cron reales (43 verificaciones) |
| `pruebas/04_verificar_telegram.sql` | Código de vinculación, límites, permisos y reintentos de la migración nueva; al final, la consulta de latencia |

Cómo correrlas: [TUTORIAL_PRUEBAS_DOCKER.md](TUTORIAL_PRUEBAS_DOCKER.md) (la 04 se ejecuta igual que la 02).

---

## Arquitectura

```
app/
├── main.py                    Punto de entrada (python -m app.main)
├── errores.py                 Traducción única de errores del SDK a mensajes en español
├── config/                    .env y validación · zona America/Costa_Rica · valores documentados
├── infrastructure/
│   ├── supabase_client.py     Cliente oficial, Auth y sesión en memoria
│   └── realtime.py            Realtime en un hilo propio (asyncio) con reconexión
├── repositories/              Acceso tipado a tablas, vistas, RPC y Storage
├── services/
│   ├── dominio.py             Reglas puras (conexión, rangos, comandos, horarios, MP3, ml…)
│   ├── contexto.py            Fachada de servicios e instantánea de la sesión
│   └── exportacion.py         CSV del historial
└── ui/
    ├── aplicacion.py          Ventana, navegación, encabezado, polling y Realtime
    ├── tareas.py              Ejecutor: red en hilos, resultados por queue.Queue + after()
    ├── acceso.py              Inicio de sesión, registro y configuración faltante
    └── pantallas/             Panel, dispositivos, detalle y paneles por tipo, perfiles,
                               alertas, historial, galería, alimentación, cuenta/Telegram
supabase/
├── migrations/                5 migraciones base + Telegram (20261101120000) + envío (20261104000000)
└── functions/                 enviar-alerta · telegram-webhook · _shared/telegram.ts
tests/                         Pruebas unitarias con dobles del SDK
```

Decisiones:

- **La UI nunca espera a la red.** Toda llamada a Supabase corre en un `ThreadPoolExecutor`;
  el resultado vuelve al hilo de Tkinter por una `queue.Queue` que se vacía con `root.after`.
  Ningún hilo secundario ni callback de Realtime toca widgets.
- **Realtime** (solo existe asíncrono en `supabase-py` 2.x) corre en un hilo con su bucle
  `asyncio`, con la clave pública y el JWT del usuario (se renueva al refrescarse la sesión).
  Se suscribe a las tablas publicadas: `dispositivos`, `configuracion`, `comandos` y `alertas`.
  Si se pierde, el encabezado muestra «En vivo: degradado», la app consulta cada 10 s y,
  al reconectar, recarga todo para reconciliar. Con Realtime activo se reconcilia cada 30 s.
- **Dos estados distintos**: «Supabase: conectado / sin conexión» (la app) y la insignia
  de cada dispositivo «En línea / Fuera de línea / Sin datos» (su señal de vida).
  Fuera de línea = más de 60 s desde `ultima_senal_en` o `en_linea = false`.
- **RLS manda.** La UI deshabilita controles sin permiso, pero toda escritura la valida la
  base. Un `update` que vuelve con 0 filas se informa como falta de permiso, no como éxito.
- **Nada se inventa.** Una orden queda «Pendiente» hasta que el dispositivo la marca; los
  valores de `ultima_lectura` se muestran tal cual llegan; sin datos se dice «sin datos».
- **Sin alertas duplicadas.** La app no inserta en `eventos` ni en `alertas`: las alertas
  las crean los triggers de la base.

## Contrato con la base que usa la app

| Función | Cómo |
|---|---|
| Registro / inicio / cierre | Supabase Auth (`usuarios` la llena el trigger) |
| Perfiles | `perfiles_bebe` con `eliminado_en is null`; `insert`/`update`; `rpc eliminar_perfil`, `rpc compartir_perfil` |
| Accesos compartidos | `acceso_perfil`: ver, alternar `puede_controlar`, quitar |
| Dispositivos | `rpc registrar_dispositivo`; `update dispositivos set perfil_id / nombre` |
| Ajustes | `update configuracion` (solo columnas con GRANT) |
| Órdenes | `insert comandos` (`activar_siesta`, `audio_reproducir`, `audio_detener`, `probar_luz`, `probar_buzzer`, `tomar_foto`) |
| Siesta | `rpc desactivar_siesta`; snapshot en `snapshots_peso` |
| Horarios | `horarios` (`movil`, `seguridad`, `movimiento`); los traslapes los rechaza la base |
| Historial / CSV | `v_historial`, `order ocurrido_en desc`, `range` de 50 |
| Galería | `v_galeria` + `create_signed_url` (120 s) del bucket privado `capturas` |
| Audios | Storage `audios/<usuario>/<archivo>.mp3` + tabla `audios` |
| Alimentación | `tomas` (inicio lo pone la base) y `recordatorios` |
| Telegram | `usuarios.telegram_chat_id`; `rpc generar_codigo_telegram`, `rpc desvincular_telegram` |

---

## Telegram: qué se completó y qué configurar

Estado previo: la migración `20261101120000_notificaciones_telegram.sql` (tablas
`codigos_telegram` y `alerta_envios`) y una versión de prueba de `enviar-alerta` estaban en
`SPRINT 3/supabase/`. Se movieron a `supabase/migrations/` y `supabase/functions/enviar-alerta/`
(como pedía README_BASE_DATOS.md, paso 3) y se completó:

- **`20261104000000_telegram_envio.sql`** (aditiva):
  `generar_codigo_telegram()` (6 dígitos con bytes aleatorios criptográficos, vigencia
  10 min, uno por usuario), `vincular_telegram()` (solo `service_role`; máximo 5 códigos
  fallidos por chat cada 10 min; un chat no puede quedar en dos cuentas),
  `desvincular_telegram()`, trigger `alertas_enviar_telegram` con `pg_net`, tarea pg_cron
  `reintentar-alertas` (cada minuto, alertas pendientes/fallidas de las últimas 24 h, hasta
  30 intentos) y la vista `v_latencia_telegram` (solo `service_role`).
  Si falla algo del envío, la alerta **se guarda igual** (RNF-17).
- **`enviar-alerta`** ahora recibe `{ alerta_id }`, envía a todos los usuarios con acceso al
  perfil y chat vinculado, con foto por URL firmada si existe, registra cada envío en
  `alerta_envios` (sin duplicados, con toma atómica) y marca la alerta `enviada`, `fallida`
  o `sin_destinatarios`. Se retiró el modo de prueba `{chat_id, texto}` porque permitía
  enviar mensajes arbitrarios por el bot.
- **`telegram-webhook`** (nueva): vincula el chat que envía `/start 123456` al dueño del código.

Pasos en el proyecto Supabase (requieren la consola o la CLI y **autorización del equipo**;
no se ejecutaron desde aquí):

1. Activar `pg_net` (Database → Extensions) si no lo crea la migración.
2. Aplicar las migraciones (`supabase db push` o SQL Editor), incluida la nueva.
3. Elegir dos secretos aleatorios largos: `ALERTAS` y `WEBHOOK`.
4. Secretos de Edge Functions (`supabase secrets set …` o Dashboard):
   `TELEGRAM_BOT_TOKEN`, `ALERTAS_WEBHOOK_SECRETO=<ALERTAS>`, `TELEGRAM_WEBHOOK_SECRETO=<WEBHOOK>`.
5. Vault (SQL Editor):
   ```sql
   select vault.create_secret('https://<ref>.supabase.co/functions/v1', 'telegram_funciones_url');
   select vault.create_secret('<ALERTAS>', 'telegram_alertas_secreto');
   ```
6. Desplegar: `supabase functions deploy enviar-alerta` y `supabase functions deploy telegram-webhook`
   (`supabase/config.toml` las declara con `verify_jwt = false`: cada una valida su secreto).
7. Registrar el webhook del bot (una vez):
   `https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<ref>.supabase.co/functions/v1/telegram-webhook&secret_token=<WEBHOOK>`
8. Medir latencia (RNF-01: anti-robo ≤ 10 s, demás ≤ 20 s) con la consulta al final de
   `pruebas/04_verificar_telegram.sql` tras 10 envíos cronometrados por tipo.

En la app: «Cuenta y Telegram» → «Generar código» → enviar `/start <código>` al bot →
«Comprobar vinculación». Mientras `usuarios.telegram_chat_id` sea `NULL`, la app muestra
«No recibirás alertas por Telegram».

## Otros pasos en la consola de Supabase

- Authentication → Providers → Email: longitud mínima de contraseña **8** (la app también la valida).
- Decidir si se exige confirmación por correo (la app la soporta: avisa «Revise su correo»).
- Crear las cuentas de los controladores y ejecutar `supabase/seed.sql` (ver README_BASE_DATOS.md).

## Limitaciones conocidas

Ver [IMPLEMENTACION_ESTADO.md](IMPLEMENTACION_ESTADO.md). Las principales: no hay firmware
en el repositorio (lo que muestra la app depende de lo que los controladores escriban), la
voz en vivo (HU-12) no está implementada, y nada se ha verificado todavía contra un
Supabase real ni contra Telegram desde este entorno.
