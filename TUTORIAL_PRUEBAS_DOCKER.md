# Tutorial: probar la base de datos en Docker Desktop

Este tutorial levanta **Supabase completo en tu computadora**: PostgreSQL, Auth,
API, Storage, Realtime y el panel Studio. No toca el proyecto oficial ni necesita
una cuenta de Supabase.

| Parte | Qué prueba | Tiempo |
|---|---|---|
| 1 a 3 | Preparar y levantar Supabase | 10 a 15 min la primera vez |
| 4 | Lógica de la base de datos, 135 verificaciones | 1 min |
| 5 | Auth, API, Storage, Realtime y pg_cron, 43 verificaciones | 3 min |
| 6 | Semilla y un flujo a mano en Studio | 10 min |
| 7 | Convivencia con la migración de Telegram | 3 min |
| 8 | Apagar y limpiar | 1 min |

**No se prueba aquí** el envío real a Telegram: su trigger todavía no existe y
necesita el token del bot. Las alertas quedan guardadas con estado `pendiente`.

---

## 1. Requisitos

Necesitas **Docker Desktop**, **Node.js** y **Python 3.10 o superior**. Abre
Docker Desktop, espera a que indique que está corriendo y comprueba en PowerShell:

```powershell
docker version --format "{{.Server.Version}}"
```

```powershell
node -v
```

```powershell
python --version
```

Supabase descarga cerca de una docena de imágenes, así que deja varios GB de disco libres.
Sus 10 contenedores usan cerca de 1,5 GB de RAM: **antes de probar, cierra los navegadores y programas que no necesites**. Con la RAM agotada aparecen errores de tiempo de espera.

---

## 2. Preparar la carpeta

Descomprime el zip en una carpeta, por ejemplo `Desktop\proyecto-bebes`. Abre
PowerShell ahí. **Todos los comandos siguientes se ejecutan desde esa carpeta.**
Debe verse así:

```
README_BASE_DATOS.md
TUTORIAL_PRUEBAS_DOCKER.md
pruebas\
supabase\
  config.toml
  seed.sql
  migrations\
```

Instala el cliente de Python en un entorno aislado:

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r pruebas\requirements.txt
```

---

## 3. Levantar Supabase

```powershell
npx -y supabase@3.0.0 start
```

Al terminar, debes ver estas líneas y luego las URL del proyecto:

```
Applying migration 20261101000000_esquema_base.sql...
Applying migration 20261101000100_funciones_y_triggers.sql...
Applying migration 20261101000200_seguridad_rls.sql...
Applying migration 20261101000300_storage_y_realtime.sql...
Applying migration 20261101000400_tareas_programadas.sql...
Seeding data from supabase/seed.sql...
```

Si una migración tiene un error, se detiene aquí y lo indica.

En Docker Desktop → **Containers** aparece un grupo `supabase_..._proyecto-bebes`
con los servicios en verde. Todo queda en estos puertos:

| Servicio | Dirección |
|---|---|
| Studio (panel) | http://127.0.0.1:44323 |
| API | http://127.0.0.1:44321 |
| PostgreSQL | `127.0.0.1:44322` |

> Supabase usa por defecto los puertos 54321 a 54329, pero Windows suele reservar
> esa zona y aparece el error `Ports are not available ... forbidden by its access
> permissions`. Por eso `config.toml` los mueve a 443xx. Solución de problemas al final.

---

## 4. Probar la lógica de la base de datos

Copia las pruebas al contenedor y ejecútalas:

```powershell
docker cp pruebas\02_verificar_base_datos.sql supabase_db_proyecto-bebes:/tmp/pruebas.sql
```

```powershell
docker exec -e PGPASSWORD=postgres supabase_db_proyecto-bebes psql -U supabase_admin -h localhost -d postgres -f /tmp/pruebas.sql
```

**Resultado esperado:** una línea `ok` por verificación y al final:

```
135 pruebas, 0 fallas
```

Revisa umbrales, ventanas de movimiento, modo siesta, reasignación de perfiles,
RLS, horarios, recordatorios y retención. Todo se deshace con `ROLLBACK`, así que
puedes repetirlo cuantas veces quieras.

---

## 5. Probar los servicios de verdad

Esta prueba hace lo mismo que harán la app y los controladores: inicia sesión con
Auth, usa la API, sube archivos y se suscribe a Realtime.

```powershell
.\.venv\Scripts\python.exe pruebas\03_probar_servicios.py
```

Tarda de 2 a 3 minutos, porque espera a que `pg_cron` detecte un dispositivo sin señal.

**Resultado esperado:** todas las líneas con `ok` y al final:

```
43 pruebas, 0 fallas
```

| Sección | Qué comprueba |
|---|---|
| Auth | Registro, contraseña de 8 caracteres, correo repetido, credenciales incorrectas |
| Dispositivos | Reclamar por código, código de otra cuenta, acceso compartido |
| Lecturas y alertas | Lectura → trigger → alerta, y que cada quien vea solo lo suyo |
| Modo siesta | Peso mínimo, alarma con % perdido, quién la desactivó |
| Storage | Rechazo de fotos de más de 150 KB y MP3 de más de 5 MB, URLs firmadas por permiso |
| Realtime | El dispositivo recibe el comando y otro usuario no |
| pg_cron | El dispositivo pasa a "fuera de línea" y se crea la alerta |

Esta prueba deja datos en la base local. Para volver a empezar limpio:

```powershell
npx -y supabase@3.0.0 db reset
```

---

## 6. Ver un flujo a mano en Studio

La parte 5 deja datos de prueba. Si la ejecutaste, limpia la base primero; si no,
verás más de los 6 dispositivos de la semilla:

```powershell
npx -y supabase@3.0.0 db reset
```

Abre http://127.0.0.1:44323.

### Cargar la semilla

1. Ve a **Authentication → Users → Add user → Create new user** y crea estas
   cuatro cuentas con **Auto confirm user?** marcado. La contraseña debe tener
   **8 caracteres o más**. Con menos, Studio solo dice `API error happened while
   trying to communicate with the server`:
   - `admin@ecosistema.test`
   - `controlador-a@ecosistema.test`
   - `controlador-b@ecosistema.test`
   - `controlador-c@ecosistema.test`
2. Ve a **SQL Editor**, pega el contenido de `supabase\seed.sql` y presiona **Run**.
3. En **Table Editor → dispositivos** deben aparecer 6 dispositivos asignados a
   "Bebé de prueba".

### Disparar una alerta

En **SQL Editor**, simula una lectura de 15 °C:

```sql
insert into public.eventos (dispositivo_id, tipo, valor, unidad)
select id, 'temperatura', 15, '°C' from public.dispositivos where codigo = 'CUNA-001';
```

Revisa la alerta:

```sql
select tipo, severidad, mensaje, estado from public.alertas order by id desc limit 1;
```

Debe salir `temperatura_baja`, con un mensaje como *"Temperatura baja en la cuna de
Bebé de prueba: 15.0 °C (mínimo 18.0 °C)"* y estado `pendiente`.

Si repites el `insert`, **no** aparece otra alerta: se repite cada 10 minutos (CA-09.2).

### Ver el historial

```sql
select fecha_hora, perfil, dispositivo, tipo, valor, unidad, descripcion
from public.v_historial order by ocurrido_en desc limit 50;
```

> El SQL Editor corre como administrador y **se salta el RLS**. Ver todas las filas
> aquí es normal. El RLS se prueba en las partes 4 y 5.

---

## 7. Probar junto con la migración de Telegram

Las dos migraciones de Telegram (`20261101120000_notificaciones_telegram.sql` y
`20261104000000_telegram_envio.sql`) ya están en `supabase\migrations\`, así que
`supabase start` las aplica junto con las demás. Para reconstruir la base desde cero
(solo la local):

```powershell
npx -y supabase@3.0.0 db reset
```

Luego repite las partes 4 y 5 (deben dar el mismo resultado) y ejecuta las pruebas de
Telegram igual que la parte 4:

```powershell
docker cp pruebas\04_verificar_telegram.sql supabase_db_proyecto-bebes:/tmp/telegram.sql
```

```powershell
docker exec -e PGPASSWORD=postgres supabase_db_proyecto-bebes psql -U supabase_admin -h localhost -d postgres -f /tmp/telegram.sql
```

Sin el Vault configurado, las alertas quedan `pendiente`: el envío real necesita los
pasos de la sección Telegram de README.md.

---

## 8. Apagar y limpiar

Apagar conservando los datos:

```powershell
npx -y supabase@3.0.0 stop
```

Apagar y borrar los datos locales:

```powershell
npx -y supabase@3.0.0 stop --no-backup
```

Esto no afecta otros contenedores. Para liberar espacio, borra después las imágenes
`public.ecr.aws/supabase/*` en Docker Desktop → **Images**.

---

## Solución de problemas

| Problema | Qué hacer |
|---|---|
| `Ports are not available` o `forbidden by its access permissions` | Ver los rangos reservados con `netsh interface ipv4 show excludedportrange protocol=tcp` y, si 443xx cae en uno, cambiar los `port` en `supabase\config.toml` |
| `Cannot connect to the Docker daemon` | Docker Desktop no ha terminado de arrancar |
| `No such container: supabase_db_proyecto-bebes` | Supabase no está corriendo, o se cambió `project_id` en `config.toml` |
| `No encontré Supabase local` | Ejecutar la parte 3 |
| La parte 5 dice `La API local no responde con estabilidad`, o salen `httpx.ReadTimeout` o `504 Gateway Timeout` | Lo más probable es que a Windows le falte RAM y esté enviando a disco la memoria de Docker. En el Administrador de tareas → Rendimiento → Memoria, revisa cuánta hay disponible. Cierra navegadores y otros programas, apaga los contenedores que no uses y repite. No apunta a un error de la base de datos |
| Sale `FALLA La app recibe la alerta nueva` | Repite la parte 5. Pasó una vez y no se reprodujo en 97 entregas medidas aparte, sin causa confirmada. Si se repite, anota cuántas filas indica el mensaje: con 0 el problema es el trigger, y con 1 o más es la entrega de Realtime |
| Studio dice `Failed to create user: API error happened while trying to communicate with the server` | Usa una contraseña de 8 caracteres o más. Si ya la usas, ve a Authentication → Users y revisa que ese correo no exista ya. Para ver el motivo real: `docker logs --tail 20 supabase_auth_proyecto-bebes` |
| Una prueba de la parte 5 falla por datos repetidos | Ejecutar `npx -y supabase@3.0.0 db reset` y repetir |
| Una migración falla al arrancar | Corregirla y ejecutar `npx -y supabase@3.0.0 db reset`, que reconstruye la base desde cero |
| Algo quedó en mal estado | `npx -y supabase@3.0.0 stop --no-backup` y volver a la parte 3 |
