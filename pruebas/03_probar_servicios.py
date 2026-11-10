"""Pruebas de punta a punta contra Supabase local (Auth, API, Storage, Realtime y pg_cron).

⚠️ SOLO con `supabase start`: crea cuentas y datos de prueba, y se niega a correr
contra una URL que no sea local.

Uso, desde la raíz del proyecto y con Supabase local ya corriendo:
    python pruebas/03_probar_servicios.py

Toma de 2 a 3 minutos, porque espera a que pg_cron detecte un dispositivo sin señal.
"""
import asyncio
import subprocess
import sys
import time
import uuid

import httpx
from supabase import AClientOptions, ClientOptions, acreate_client, create_client

sys.stdout.reconfigure(encoding="utf-8")

# Las claves locales no son secretas, pero así no hay que copiarlas a mano.
estado_local = subprocess.run("npx -y supabase@3.0.0 status -o env", shell=True, capture_output=True, text=True)
variables = dict(
    linea.split("=", 1) for linea in estado_local.stdout.splitlines() if "=" in linea
)
try:
    URL, ANON, SERVICIO = (variables[v].strip('"') for v in ("API_URL", "ANON_KEY", "SERVICE_ROLE_KEY"))
except KeyError:
    sys.exit("No encontré Supabase local. Ejecute primero: npx -y supabase@3.0.0 start")

if "127.0.0.1" not in URL and "localhost" not in URL:
    sys.exit("Estas pruebas solo corren contra Supabase local.")

# supabase-py le da solo 5 s a Auth. En Docker Desktop hay picos de varios segundos
# entre Windows y los contenedores, y eso no es lo que se quiere probar aquí.
LIMITE_S = 60


def nuevo_cliente(clave=None):
    # Un httpx.Client por cliente: compartirlo mezclaría los JWT de cada sesión.
    return create_client(URL, clave or ANON, options=ClientOptions(httpx_client=httpx.Client(timeout=LIMITE_S)))


def esperar_api():
    """Espera a que la API responda rápido tres veces seguidas."""
    seguidas = 0
    limite = time.time() + 90
    while seguidas < 3 and time.time() < limite:
        inicio = time.time()
        try:
            respuesta = httpx.get(f"{URL}/auth/v1/health", headers={"apikey": ANON}, timeout=LIMITE_S)
            rapida = respuesta.status_code == 200 and time.time() - inicio < 2
        except httpx.HTTPError:
            rapida = False
        seguidas = seguidas + 1 if rapida else 0
        time.sleep(0.5)
    if seguidas < 3:
        sys.exit("La API local no responde con estabilidad. Revise si Windows tiene RAM libre, cierre programas y repita.")


esperar_api()

CLAVE = "clave-de-prueba-123"
SUFIJO = uuid.uuid4().hex[:8]
resultados = []


def ok(nombre, condicion, detalle=""):
    resultados.append(bool(condicion))
    print(f"{'ok   ' if condicion else 'FALLA'} {nombre}" + (f" -> {detalle}" if not condicion and detalle else ""))


def falla(nombre, funcion, texto):
    """La llamada debe fallar con un error que contenga el texto."""
    try:
        respuesta = funcion()
    except Exception as error:  # Cada cliente de supabase-py tiene su propia excepción.
        ok(nombre, texto.lower() in str(error).lower(), str(error))
        return
    ok(nombre, False, f"no falló: {respuesta}")


def correo(nombre):
    return f"{nombre}-{SUFIJO}@ecosistema.test"


def cliente(nombre):
    """Sesión de un usuario ya creado, igual que en la app o en un controlador."""
    c = nuevo_cliente()
    c.auth.sign_in_with_password({"email": correo(nombre), "password": CLAVE})
    return c


servicio = nuevo_cliente(SERVICIO)


def crear_cuenta(nombre, rol=None):
    atributos = {"email": correo(nombre), "password": CLAVE, "email_confirm": True}
    if rol:
        atributos["app_metadata"] = {"rol": rol}
    return servicio.auth.admin.create_user(atributos).user.id


# ------------------------------------------------------------------ Auth (EP01)
print("\n== Auth (HU-01, HU-02)")
publico = nuevo_cliente()
registro = publico.auth.sign_up({"email": correo("ana"), "password": CLAVE})
ana_id = registro.user.id
ok("CA-01.1 se crea la cuenta", ana_id is not None)

ana = cliente("ana")
fila = ana.table("usuarios").select("rol, correo").eq("id", ana_id).single().execute().data
ok("CA-01.1 queda con rol administrador", fila["rol"] == "administrador")

falla("CA-01.1 contraseña de menos de 8 caracteres",
      lambda: nuevo_cliente().auth.sign_up({"email": correo("corta"), "password": "1234567"}),
      "8")


def repetir_registro():
    r = nuevo_cliente().auth.sign_up({"email": correo("ana"), "password": CLAVE})
    return r


falla("CA-01.2 correo ya registrado", repetir_registro, "already registered")
falla("CA-02.2 contraseña incorrecta",
      lambda: nuevo_cliente().auth.sign_in_with_password({"email": correo("ana"), "password": "mala-clave-123"}),
      "invalid login credentials")
falla("CA-02.2 correo inexistente da el mismo error",
      lambda: nuevo_cliente().auth.sign_in_with_password({"email": correo("nadie"), "password": CLAVE}),
      "invalid login credentials")

salida = cliente("ana")
salida.auth.sign_out()
falla("CA-02.3 al cerrar sesión ya no lee datos",
      lambda: salida.table("usuarios").select("id").execute(), "permission denied")
falla("anon no lee tablas", lambda: nuevo_cliente().table("usuarios").select("id").execute(), "permission denied")

beto_id = crear_cuenta("beto")
carla_id = crear_cuenta("carla")
beto = cliente("beto")
carla = cliente("carla")

# ------------------------------------------------------------------- Provisión
print("\n== Dispositivos (HU-04, HU-05)")
ctrl_a_id = crear_cuenta("ctrl-a", "dispositivo")
ctrl_b_id = crear_cuenta("ctrl-b", "dispositivo")
codigos = {t: f"{t.upper()}-{SUFIJO}" for t in ("cuna", "seguridad", "colchon")}
falla("Un usuario no da de alta dispositivos",
      lambda: ana.rpc("provisionar_dispositivo",
                      {"p_codigo": "X", "p_tipo": "cuna", "p_credencial": ana_id}).execute(),
      "permission denied")
cuna_id = servicio.rpc("provisionar_dispositivo",
                       {"p_codigo": codigos["cuna"], "p_tipo": "cuna", "p_credencial": ctrl_a_id}).execute().data
seguridad_id = servicio.rpc("provisionar_dispositivo",
                            {"p_codigo": codigos["seguridad"], "p_tipo": "seguridad", "p_credencial": ctrl_a_id}).execute().data
colchon_id = servicio.rpc("provisionar_dispositivo",
                          {"p_codigo": codigos["colchon"], "p_tipo": "colchon", "p_credencial": ctrl_b_id}).execute().data

ok("Un controlador provisionado no queda en usuarios",
   not servicio.table("usuarios").select("id").eq("id", ctrl_a_id).execute().data)

for tipo, codigo in codigos.items():
    ana.rpc("registrar_dispositivo", {"p_codigo": codigo, "p_nombre": tipo.capitalize()}).execute()
falla("CA-04.2 código de otra cuenta",
      lambda: beto.rpc("registrar_dispositivo", {"p_codigo": codigos["cuna"]}).execute(), "otra cuenta")

perfil = ana.table("perfiles_bebe").insert(
    {"propietario_id": ana_id, "nombre": "Sofía", "fecha_nacimiento": "2026-01-01"}).execute().data[0]
ana.table("dispositivos").update({"perfil_id": perfil["id"]}).in_("id", [cuna_id, seguridad_id, colchon_id]).execute()
ana.rpc("compartir_perfil", {"p_perfil": perfil["id"], "p_correo": correo("carla"), "p_puede_controlar": False}).execute()

ok("RNF-14 otro usuario no ve dispositivos", not beto.table("dispositivos").select("id").execute().data)
ok("Acceso compartido ve los dispositivos", len(carla.table("dispositivos").select("id").execute().data) == 3)

ctrl_a = cliente("ctrl-a")
ctrl_b = cliente("ctrl-b")
ok("El controlador encuentra sus dispositivos", len(ctrl_a.table("dispositivos").select("id, codigo").execute().data) == 2)

# ------------------------------------------------------------- Lectura y alerta
print("\n== Lecturas y alertas (flujos 1 y 2)")
ctrl_a.rpc("registrar_senal", {"p_dispositivo": cuna_id, "p_lectura": {"temperatura": 15}}).execute()
ok("HU-06 la app ve la cuna en línea",
   ana.table("dispositivos").select("en_linea").eq("id", cuna_id).single().execute().data["en_linea"])

ctrl_a.table("eventos").insert({"dispositivo_id": cuna_id, "tipo": "temperatura", "valor": 15, "unidad": "°C"}).execute()
alertas = ana.table("alertas").select("*").eq("dispositivo_id", cuna_id).execute().data
ok("CA-09.1 la lectura baja crea la alerta", len(alertas) == 1 and alertas[0]["tipo"] == "temperatura_baja")
ok("La alerta queda pendiente para Telegram", alertas and alertas[0]["estado"] == "pendiente")
ok("Quien tiene acceso ve la alerta", len(carla.table("alertas").select("id").execute().data) == 1)
ok("RNF-14 otro usuario no ve alertas", not beto.table("alertas").select("id").execute().data)
falla("RNF-14 credencial ajena no escribe eventos",
      lambda: ctrl_b.table("eventos").insert({"dispositivo_id": cuna_id, "tipo": "peso", "valor": 1}).execute(),
      "row-level security")

historial = ana.table("v_historial").select("*").eq("perfil_id", perfil["id"]).order("ocurrido_en", desc=True).limit(50).execute().data
ok("HU-39 el historial trae los eventos", any(h["tipo"] == "temperatura" for h in historial))

# ------------------------------------------------------------------ Modo siesta
print("\n== Modo siesta (HU-15 a HU-18)")
falla("CA-15.2 sin bebé no activa la siesta",
      lambda: ctrl_b.table("snapshots_peso").insert({"dispositivo_id": colchon_id, "peso_base_g": 100}).execute(),
      "No se detecta al beb")
ctrl_b.table("snapshots_peso").insert({"dispositivo_id": colchon_id, "peso_base_g": 4000}).execute()
ctrl_b.table("eventos").insert({"dispositivo_id": colchon_id, "tipo": "alarma_antirrobo", "valor": 1000, "unidad": "g"}).execute()
alerta = ana.table("alertas").select("*").eq("tipo", "antirrobo").single().execute().data
ok("CA-17.2 alerta crítica con el % perdido", alerta["severidad"] == "critica" and "75.0 %" in alerta["mensaje"], alerta["mensaje"])
falla("CA-18.2 sin permiso de control no desactiva",
      lambda: carla.rpc("desactivar_siesta", {"p_dispositivo": colchon_id}).execute(), "permiso de control")
ana.rpc("desactivar_siesta", {"p_dispositivo": colchon_id}).execute()
alerta = ana.table("alertas").select("desactivada_por").eq("tipo", "antirrobo").single().execute().data
ok("CA-18.2 registra quién la desactivó", alerta["desactivada_por"] == ana_id)

# ---------------------------------------------------------------------- Storage
print("\n== Storage (RNF-05, RNF-23, CA-13)")
JPEG = {"content-type": "image/jpeg"}
MP3 = {"content-type": "audio/mpeg"}
foto = f"{seguridad_id}/evidencia.jpg"
ctrl_a.storage.from_("capturas").upload(foto, b"\xff\xd8" + b"0" * 1000, JPEG)
ok("RNF-05 sube una foto pequeña", True)
falla("RNF-05 rechaza una foto de más de 150 KB",
      lambda: ctrl_a.storage.from_("capturas").upload(f"{seguridad_id}/grande.jpg", b"0" * 160_000, JPEG),
      "exceeded the maximum")
ctrl_a.storage.from_("capturas").upload(f"{seguridad_id}/evidencia.png", b"\x89PNG" + b"0" * 1000,
                                        {"content-type": "image/png"})
ok("Acepta una foto PNG (aparato de seguridad)", True)
falla("Rechaza una foto que no es JPEG ni PNG",
      lambda: ctrl_a.storage.from_("capturas").upload(f"{seguridad_id}/f.gif", b"0" * 10, {"content-type": "image/gif"}),
      "mime type")
falla("RNF-23 un controlador no sube a la carpeta de otro",
      lambda: ctrl_b.storage.from_("capturas").upload(f"{seguridad_id}/intruso.jpg", b"0" * 10, JPEG),
      "row-level security")

ana.table("configuracion").update({"seguridad_armada": True}).eq("dispositivo_id", seguridad_id).execute()
ctrl_a.table("eventos").insert({"dispositivo_id": seguridad_id, "tipo": "presencia", "foto_path": foto}).execute()
alerta = ana.table("alertas").select("foto_path").eq("tipo", "presencia").single().execute().data
ok("CA-27.1 la alerta lleva la foto", alerta["foto_path"] == foto)
ok("HU-28 la galería muestra la captura", ana.table("v_galeria").select("foto_path").execute().data[0]["foto_path"] == foto)

firmada = carla.storage.from_("capturas").create_signed_url(foto, 60)
ok("RNF-23 con acceso al perfil obtiene la URL firmada", firmada.get("signedURL") or firmada.get("signedUrl"))
falla("RNF-23 sin acceso no obtiene la URL firmada",
      lambda: beto.storage.from_("capturas").create_signed_url(foto, 60), "not found")

ana.storage.from_("audios").upload(f"{ana_id}/nana.mp3", b"ID3" + b"0" * 1000, MP3)
ok("CA-13.2 sube un MP3", True)
falla("CA-13.3 rechaza otro formato",
      lambda: ana.storage.from_("audios").upload(f"{ana_id}/n.wav", b"0" * 10, {"content-type": "audio/wav"}),
      "mime type")
falla("CA-13.3 rechaza un MP3 de más de 5 MB",
      lambda: ana.storage.from_("audios").upload(f"{ana_id}/g.mp3", b"0" * (5 * 1024 * 1024 + 1), MP3),
      "exceeded the maximum")


# --------------------------------------------------------------------- Realtime
async def probar_realtime():
    print("\n== Realtime (flujo 3)")

    async def sesion(nombre):
        c = await acreate_client(URL, ANON, options=AClientOptions(httpx_client=httpx.AsyncClient(timeout=LIMITE_S)))
        await c.auth.sign_in_with_password({"email": correo(nombre), "password": CLAVE})
        return c

    controlador = await sesion("ctrl-a")
    intruso = await sesion("beto")
    app = await sesion("ana")

    recibidos, de_intruso, alertas_app = [], [], []
    suscritos = {}

    def estado(nombre):
        def _estado(status, error):
            if getattr(status, "value", str(status)) == "SUBSCRIBED":
                suscritos[nombre] = True
        return _estado

    await (controlador.channel("comandos-ctrl")
           .on_postgres_changes("INSERT", schema="public", table="comandos",
                                filter=f"dispositivo_id=eq.{cuna_id}",
                                callback=lambda p: recibidos.append((time.perf_counter(), p)))
           .subscribe(estado("controlador")))
    await (intruso.channel("comandos-intruso")
           .on_postgres_changes("INSERT", schema="public", table="comandos",
                                callback=lambda p: de_intruso.append(p))
           .subscribe(estado("intruso")))
    await (app.channel("alertas-app")
           .on_postgres_changes("INSERT", schema="public", table="alertas",
                                callback=lambda p: alertas_app.append(p))
           .subscribe(estado("app")))

    for _ in range(40):
        if len(suscritos) == 3:
            break
        await asyncio.sleep(0.25)
    ok("Los tres clientes se suscriben", len(suscritos) == 3, str(suscritos))
    await asyncio.sleep(2)

    inicio = time.perf_counter()
    await app.table("comandos").insert({"dispositivo_id": cuna_id, "tipo": "probar_luz"}).execute()
    await controlador.table("eventos").insert(
        {"dispositivo_id": cuna_id, "tipo": "humedad", "valor": 90, "unidad": "%"}).execute()

    for _ in range(120):  # Hasta 30 s
        if recibidos and alertas_app:
            break
        await asyncio.sleep(0.25)

    ok("Flujo 3 el dispositivo recibe el comando", len(recibidos) == 1)
    if recibidos:
        print(f"      entregado en {recibidos[0][0] - inicio:.2f} s")
    en_base = (await app.table("alertas").select("id").eq("tipo", "humedad_alta").execute()).data
    ok("La app recibe la alerta nueva", len(alertas_app) >= 1,
       f"en 30 s no llegó por Realtime; filas con esa alerta en la base: {len(en_base)}")
    await asyncio.sleep(2)
    ok("RNF-14 otro usuario no recibe el comando", not de_intruso)

    comando = (await controlador.table("comandos").select("id").eq("tipo", "probar_luz").single().execute()).data
    await controlador.table("comandos").update({"estado": "ejecutado"}).eq("id", comando["id"]).execute()
    final = (await app.table("comandos").select("estado").eq("id", comando["id"]).single().execute()).data
    ok("Flujo 3 el comando queda ejecutado", final["estado"] == "ejecutado")

    for c in (controlador, intruso, app):
        await c.remove_all_channels()


asyncio.run(probar_realtime())

# ---------------------------------------------------------------------- pg_cron
print("\n== pg_cron (HU-06): esperando hasta 130 s a que el colchón pase a fuera de línea")
ctrl_b.rpc("registrar_senal", {"p_dispositivo": colchon_id}).execute()
ctrl_b.table("snapshots_peso").insert({"dispositivo_id": colchon_id, "peso_base_g": 4000}).execute()
inicio = time.time()
en_linea = True
while en_linea and time.time() - inicio < 130:
    time.sleep(5)
    en_linea = ana.table("dispositivos").select("en_linea").eq("id", colchon_id).single().execute().data["en_linea"]
ok("CA-06.1 pasa a fuera de línea sin señal", not en_linea)
print(f"      detectado a los {time.time() - inicio:.0f} s")
ok("CA-06.2 alerta porque había siesta activa",
   len(ana.table("alertas").select("id").eq("tipo", "fuera_de_linea").execute().data) == 1)

# -------------------------------------------------------------------- Resultado
print(f"\n{len(resultados)} pruebas, {resultados.count(False)} fallas")
sys.exit(1 if False in resultados else 0)
