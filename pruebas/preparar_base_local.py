"""Prepara Supabase LOCAL con datos de prueba para ver la app funcionando.

⚠️ Solo con `supabase start`. Uso, desde la raíz del proyecto:
    .venv\\Scripts\\python.exe pruebas\\preparar_base_local.py

Hace, y se puede repetir sin duplicar lo principal:
  1. Crea (o actualiza) las 4 cuentas que pide supabase/seed.sql con contraseñas al
     azar, guardadas en pruebas/.credenciales_locales.json (fuera de Git).
  2. Ejecuta supabase/seed.sql: 6 dispositivos, el perfil «Bebé de prueba» y asignaciones.
  3. Agrega un segundo perfil (gemelos), historial de 24 h, alertas, una foto de
     evidencia, horarios, tomas y recordatorios.
  4. Crea .env con la URL y la clave pública local si todavía no existe.
Después, `pruebas\\simular_dispositivos.py` mantiene los dispositivos «en línea».
"""
from __future__ import annotations

import json
import random
import secrets
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

from postgrest.types import CountMethod
from supabase import create_client

from local_comun import (ARCHIVO_CREDENCIALES, CONTROLADORES, CUENTA_ADMIN, RAIZ, claves_locales, foto_jpeg)

sys.stdout.reconfigure(encoding="utf-8")
URL, ANON, SERVICIO = claves_locales()
servicio = create_client(URL, SERVICIO)


def paso(texto):
    print(f"• {texto}")


# 1. Cuentas ---------------------------------------------------------------------
credenciales = json.loads(ARCHIVO_CREDENCIALES.read_text(encoding="utf-8")) if ARCHIVO_CREDENCIALES.exists() else {}
existentes = {u.email: u.id for u in servicio.auth.admin.list_users()}
for correo in [CUENTA_ADMIN, *CONTROLADORES]:
    clave = credenciales.get(correo) or secrets.token_urlsafe(12)
    credenciales[correo] = clave
    if correo in existentes:
        servicio.auth.admin.update_user_by_id(existentes[correo], {"password": clave})
    else:
        servicio.auth.admin.create_user({"email": correo, "password": clave, "email_confirm": True})
ARCHIVO_CREDENCIALES.write_text(json.dumps(credenciales, indent=2), encoding="utf-8")
paso(f"4 cuentas listas; contraseñas en {ARCHIVO_CREDENCIALES.relative_to(RAIZ)}")

# 2. seed.sql ----------------------------------------------------------------------
subprocess.run(["docker", "cp", str(RAIZ / "supabase" / "seed.sql"), "supabase_db_proyecto-bebes:/tmp/seed.sql"], check=True)
r = subprocess.run(["docker", "exec", "-e", "PGPASSWORD=postgres", "supabase_db_proyecto-bebes", "psql", "-U",
                    "supabase_admin", "-h", "localhost", "-d", "postgres", "-q", "-v", "ON_ERROR_STOP=1",
                    "-f", "/tmp/seed.sql"], capture_output=True, text=True)
if r.returncode != 0:
    sys.exit("seed.sql falló:\n" + r.stderr)
paso("seed.sql ejecutado: 6 dispositivos asignados a «Bebé de prueba»")


def sesion(correo):
    c = create_client(URL, ANON)
    c.auth.sign_in_with_password({"email": correo, "password": credenciales[correo]})
    return c


admin = sesion(CUENTA_ADMIN)
admin_id = existentes.get(CUENTA_ADMIN) or admin.auth.get_user().user.id
ctrl = {correo: sesion(correo) for correo in CONTROLADORES}
dispositivos = {d["codigo"]: d for d in admin.table("dispositivos").select("id, codigo, tipo, perfil_id").execute().data}
ids = {codigo: d["id"] for codigo, d in dispositivos.items()}
controlador_de = {codigo: ctrl[correo] for correo, codigos in CONTROLADORES.items() for codigo in codigos}
perfil = dispositivos["CUNA-001"]["perfil_id"]

# 3. Datos de ejemplo ------------------------------------------------------------------
# Segundo perfil (gemelos), sin dispositivos: muestra el selector de perfiles.
if not admin.table("perfiles_bebe").select("id").eq("nombre", "Mateo (gemelo)").is_("eliminado_en", "null").execute().data:
    admin.table("perfiles_bebe").insert({"propietario_id": admin_id, "nombre": "Mateo (gemelo)",
                                         "fecha_nacimiento": "2026-01-15"}).execute()
admin.table("perfiles_bebe").update({"nombre": "Sofía"}).eq("id", perfil).execute()
paso("Perfiles: «Sofía» (con los 6 dispositivos) y «Mateo (gemelo)»")

# Ventana de movimiento todo el día y un horario del móvil por la noche.
def horario(codigo, tipo, dias, inicio, fin, secuencia=None):
    existe = admin.table("horarios").select("id").eq("dispositivo_id", ids[codigo]).eq("tipo", tipo) \
        .eq("hora_inicio", inicio).execute().data
    if not existe:
        datos = {"dispositivo_id": ids[codigo], "tipo": tipo, "dias": dias, "hora_inicio": inicio,
                 "hora_fin": fin, "activo": True}
        if secuencia:
            datos["secuencia"] = secuencia
        admin.table("horarios").insert(datos).execute()


horario("CUNA-001", "movimiento", [0, 1, 2, 3, 4, 5, 6], "00:00", "23:59")
horario("MOVIL-001", "movil", [0, 1, 2, 3, 4, 5, 6], "19:30", "20:15", 4)
horario("SEGURIDAD-001", "seguridad", [1, 2, 3, 4, 5], "22:00", "06:00")
paso("Horarios: vigilancia de movimiento todo el día, móvil 19:30–20:15 y seguridad nocturna L–V")

# Historial de las últimas 24 h, como lo mandaría cada controlador (una muestra cada 30 min).
ahora = datetime.now(timezone.utc).replace(second=0, microsecond=0)
random.seed(7)
filas = {codigo: [] for codigo in ("CUNA-001", "BIBERON-001", "COLCHON-001")}
for i in range(48, 0, -1):
    momento = (ahora - timedelta(minutes=30 * i)).isoformat()
    filas["CUNA-001"] += [
        {"dispositivo_id": ids["CUNA-001"], "tipo": "temperatura", "valor": round(random.uniform(20, 24.5), 1),
         "unidad": "°C", "ocurrido_en": momento},
        {"dispositivo_id": ids["CUNA-001"], "tipo": "humedad", "valor": round(random.uniform(44, 58), 1),
         "unidad": "%", "ocurrido_en": momento}]
    if i % 6 == 0:
        filas["BIBERON-001"].append({"dispositivo_id": ids["BIBERON-001"], "tipo": "temperatura_biberon",
                                     "valor": round(random.uniform(35.5, 39), 1), "unidad": "°C", "ocurrido_en": momento})
    if i % 4 == 0:
        filas["COLCHON-001"].append({"dispositivo_id": ids["COLCHON-001"], "tipo": "peso",
                                     "valor": round(random.uniform(4050, 4150)), "unidad": "g", "ocurrido_en": momento})
for codigo, lote in filas.items():
    controlador_de[codigo].table("eventos").upsert(lote, on_conflict="dispositivo_id,ocurrido_en,tipo",
                                                   ignore_duplicates=True).execute()

# Lecturas fuera de rango: las alertas las crea el trigger de eventos (no se insertan a mano).
reciente = lambda minutos: (ahora - timedelta(minutes=minutos)).isoformat()
eventos_alerta = [
    ("CUNA-001", {"tipo": "temperatura", "valor": 17.2, "unidad": "°C", "ocurrido_en": reciente(25)}),
    ("CUNA-001", {"tipo": "movimiento", "descripcion": "Movimiento en la cuna", "ocurrido_en": reciente(12)}),
    ("BIBERON-001", {"tipo": "temperatura_biberon", "valor": 43.5, "unidad": "°C", "ocurrido_en": reciente(40)}),
    ("JUGUETE-001", {"tipo": "juguete_acierto", "descripcion": "Acierto en el botón 3", "ocurrido_en": reciente(8)}),
    ("JUGUETE-001", {"tipo": "juguete_acierto", "descripcion": "Acierto en el botón 1", "ocurrido_en": reciente(7)}),
]
for codigo, evento in eventos_alerta:
    controlador_de[codigo].table("eventos").upsert({"dispositivo_id": ids[codigo], **evento},
                                                   on_conflict="dispositivo_id,ocurrido_en,tipo",
                                                   ignore_duplicates=True).execute()
paso("Historial de 24 h (cuna, biberón, colchón) y lecturas fuera de rango que generan alertas")

# Foto de evidencia: seguridad armada + presencia con foto (flujo 4).
admin.table("configuracion").update({"seguridad_armada": True}).eq("dispositivo_id", ids["SEGURIDAD-001"]).execute()
# El controlador solo puede subir fotos nuevas (sin sobrescribir): nombre único.
ruta = f"{ids['SEGURIDAD-001']}/prueba-{secrets.token_hex(4)}.jpg"
controlador_de["SEGURIDAD-001"].storage.from_("capturas").upload(ruta, foto_jpeg("Foto de prueba · presencia"),
                                                                {"content-type": "image/jpeg"})
controlador_de["SEGURIDAD-001"].table("eventos").upsert(
    {"dispositivo_id": ids["SEGURIDAD-001"], "tipo": "presencia", "foto_path": ruta, "ocurrido_en": reciente(3)},
    on_conflict="dispositivo_id,ocurrido_en,tipo", ignore_duplicates=True).execute()
paso("Seguridad armada y una captura de presencia con foto en la galería")

# Alimentación: dos tomas terminadas y dos recordatorios.
if not admin.table("tomas").select("id").eq("perfil_id", perfil).execute().data:
    for horas, minutos, ml in ((5, 18, 120), (2, 22, 90)):
        inicio = ahora - timedelta(hours=horas)
        admin.table("tomas").insert({"perfil_id": perfil, "dispositivo_id": ids["BIBERON-001"], "inicio": inicio.isoformat(),
                                     "fin": (inicio + timedelta(minutes=minutos)).isoformat(), "cantidad_ml": ml}).execute()
if not admin.table("recordatorios").select("id").eq("perfil_id", perfil).execute().data:
    admin.table("recordatorios").insert({"perfil_id": perfil, "tipo": "intervalo", "intervalo_min": 180}).execute()
    admin.table("recordatorios").insert({"perfil_id": perfil, "tipo": "hora_fija", "hora": "07:00"}).execute()
paso("Alimentación: 2 tomas registradas y 2 recordatorios")

# Ajustes: luz nocturna al 25 % para ver el valor guardado.
admin.table("configuracion").update({"luz_intensidad": 25}).eq("dispositivo_id", ids["CUNA-001"]).execute()

# 4. .env ---------------------------------------------------------------------------------
env = RAIZ / ".env"
if env.exists():
    paso(".env ya existía: no se modificó")
else:
    env.write_text(f"SUPABASE_URL={URL}\nSUPABASE_ANON_KEY={ANON}\nTELEGRAM_BOT_USUARIO=ecosistema_bebe_g1_bot\n",
                   encoding="utf-8")
    paso(".env creado con la URL y la clave pública de Supabase local")

alertas = admin.table("alertas").select("id", count=CountMethod.exact).execute().count
print(f"\nListo: {len(ids)} dispositivos, {alertas} alertas. Inicie sesión con {CUENTA_ADMIN}.")
