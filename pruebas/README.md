# Base local con datos de prueba

Cómo levantar Supabase en su computadora con datos de ejemplo para ver la app funcionando.
⚠️ Todo esto es **solo para Supabase local**: los scripts se niegan a correr contra otra URL.

## Requisitos

- Docker Desktop abierto y Node.js instalado.
- El entorno de Python del proyecto (`.venv`), creado como indica el [README](../README.md).
  No hace falta tener `python` ni `py` en el PATH: se usa `.venv\Scripts\python.exe`.

## 1. Levantar Supabase

Desde la raíz del repositorio:

```powershell
npx -y supabase@3.0.0 start
```

La primera vez descarga las imágenes (10 a 15 min). Aplica las migraciones de `supabase/migrations/`.

## 2. Cargar los datos de prueba

```powershell
.venv\Scripts\python.exe pruebas\preparar_base_local.py
```

Crea o actualiza:

- Las 4 cuentas de `supabase/seed.sql` (`admin@ecosistema.test` y los tres controladores), con
  contraseñas al azar guardadas en `pruebas\.credenciales_locales.json` (fuera de Git).
- Los 6 dispositivos del seed, asignados al perfil «Sofía», y un segundo perfil, «Mateo (gemelo)».
- 24 h de historial, alertas generadas por la base, una foto en la galería, horarios, tomas y recordatorios.
- `.env` con la URL y la clave pública local, si todavía no existe.

Se puede ejecutar de nuevo cuando quiera (por ejemplo, después de `supabase db reset`).

## 3. Simular los dispositivos

En otra terminal:

```powershell
.venv\Scripts\python.exe pruebas\simular_dispositivos.py
```

Mantiene los 6 dispositivos «En línea»: envía la señal cada 5 s, guarda una muestra por minuto y
responde las órdenes de la app (activar siesta, tomar foto, probar luz…). Se detiene con Ctrl+C;
un minuto después los dispositivos pasan a «Fuera de línea».

## 4. Abrir la app

```powershell
.venv\Scripts\python.exe -m app.main
```

Inicie sesión con `admin@ecosistema.test` y la contraseña de `pruebas\.credenciales_locales.json`.
Studio, el panel web de la base local, está en http://127.0.0.1:44323.

## Apagar

```powershell
npx -y supabase@3.0.0 stop
```

Conserva los datos. Con `--no-backup` se borran.

## Otros archivos de esta carpeta

| Archivo | Para qué |
|---|---|
| `02_verificar_base_datos.sql` | Pruebas de la lógica SQL (ver [TUTORIAL_PRUEBAS_DOCKER.md](../TUTORIAL_PRUEBAS_DOCKER.md)) |
| `03_probar_servicios.py` | Pruebas de Auth, API, Storage, Realtime y pg_cron |
| `04_verificar_telegram.sql` | Pruebas de la vinculación y el envío de Telegram |
| `local_comun.py` | Funciones compartidas por los dos scripts de datos de prueba |

Las pruebas 02 a 04 dejan cuentas y dispositivos propios en la base. No se ven desde
`admin@ecosistema.test`, porque pertenecen a otras cuentas.
