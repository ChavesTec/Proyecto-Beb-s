"""Corre el firmware de la seguridad (firmware/seguridad) contra Supabase LOCAL.

⚠️ Solo con Supabase local y después de pruebas\preparar_base_local.py. Uso:
    .venv\Scripts\python.exe pruebas\05_probar_firmware_seguridad.py

La cámara se simula (barras roja y azul); el cliente HTTP, la vigilancia, el PNG
y la cola son los mismos archivos que se copian a la Pico W. httpx reemplaza a urequests.
Deja la seguridad ARMADA y dos capturas nuevas en la galería.
"""
import importlib.util
import io
import os
import sys
import tempfile
import time
import types
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")


class _Resp:
    def __init__(self, r):
        self.status_code, self.text = r.status_code, r.text

    def close(self):
        pass


def _request(metodo, url, data=None, headers=None, timeout=None):   # mismo uso que urequests
    return _Resp(httpx.request(metodo, url, content=data, headers=headers, timeout=timeout or 10))


sys.modules["urequests"] = types.SimpleNamespace(request=_request)
sys.modules["network"] = types.SimpleNamespace(STA_IF=0, WLAN=None)
for c in ("firmware/seguridad", "firmware/comun", "pruebas"):
    sys.path.insert(0, str(RAIZ / c))

from PIL import Image  # noqa: E402
from supabase import create_client  # noqa: E402

from local_comun import CUENTA_ADMIN, claves_locales, leer_credenciales  # noqa: E402
from supabase_micro import ClienteSupabase  # noqa: E402
from vigilancia import Cola, Vigilancia  # noqa: E402

spec = importlib.util.spec_from_file_location("seguridad_main", RAIZ / "firmware/seguridad/main.py")
seg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seg)

URL, ANON, _ = claves_locales()
cred = leer_credenciales()
CTRL = "controlador-a@ecosistema.test"
fallas = 0


def ok(nombre, cond):
    global fallas
    print(("ok    " if cond else "FALLA ") + nombre)
    fallas += 0 if cond else 1


admin = create_client(URL, ANON)
admin.auth.sign_in_with_password({"email": CUENTA_ADMIN, "password": cred[CUENTA_ADMIN]})
disp = admin.table("dispositivos").select("id").eq("codigo", "SEGURIDAD-001").single().execute().data["id"]
config = lambda **v: admin.table("configuracion").update(v).eq("dispositivo_id", disp).execute()
config(seguridad_armada=False, seguridad_intervalo_foto_s=30)
capturas_antes = len(admin.table("capturas").select("id").eq("dispositivo_id", disp).execute().data)


class Camara:
    ancho, alto, lista = 154, 120, True

    def __init__(self):
        f = bytearray()
        for y in range(120):
            for x in range(154):
                r, g, b = (255, 0, 0) if y < 60 else (0, 0, 255)
                v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                f += bytes([v >> 8, v & 0xFF])
        self.frame = f

    def capturar(self):
        return True


os.chdir(tempfile.mkdtemp())
cliente = ClienteSupabase(URL, ANON, CTRL, cred[CTRL])
vig = Vigilancia(20)
agente = seg.Agente({"codigo_dispositivo": "SEGURIDAD-001"}, cliente, vig, Cola(espacio_libre=lambda: 10**9),
                    Camara(), seg.guardar_estado)

print("== Arranque y señal")
agente.vuelta_red(0)
fila = admin.table("dispositivos").select("en_linea, ultima_lectura").eq("id", disp).single().execute().data
ok("en línea tras registrar_senal", fila["en_linea"] is True)
ok("ultima_lectura informa desarmada", fila["ultima_lectura"]["armada"] is False)

print("== Comando tomar_foto con la seguridad desarmada")
cmd = admin.table("comandos").insert({"dispositivo_id": disp, "tipo": "tomar_foto"}).execute().data[0]
agente.vuelta_red(1)
c = admin.table("comandos").select("estado, resultado").eq("id", cmd["id"]).single().execute().data
ok("queda fallido con el motivo", c["estado"] == "fallido" and "desarmada" in c["resultado"])
ok("desarmada no envía presencia", vig.al_medir(10, 0) is None)

print("== Armar desde la app")
config(seguridad_armada=True)
agente.vuelta_red(2)
ok("el firmware lee el armado", vig.armada is True and seg.cargar_estado()["armada"] is True)

print("== Presencia con foto")
accion = vig.al_medir(12.0, 1000)
ok("primera presencia pide foto", accion == "foto")
agente.registrar_presencia(accion, 12.0)
agente.enviar_pendientes()
cap = admin.table("v_galeria").select("foto_path, tipo_evento").eq("dispositivo_id", disp) \
    .order("tomada_en", desc=True).limit(1).execute().data[0]
ok("captura creada por el trigger (.png en la carpeta del dispositivo)",
   cap["foto_path"].startswith(disp + "/") and cap["foto_path"].endswith(".png") and cap["tipo_evento"] == "presencia")
alerta = admin.table("alertas").select("foto_path, severidad").eq("foto_path", cap["foto_path"]).execute().data
ok("alerta crítica con la foto (va a Telegram)", alerta and alerta[0]["severidad"] == "critica")
firmada = admin.storage.from_("capturas").create_signed_url(cap["foto_path"], 60)
r = httpx.get(firmada.get("signedURL") or firmada.get("signedUrl"))
img = Image.open(io.BytesIO(r.content))
ok("la app descarga la foto y Pillow la abre", r.status_code == 200 and img.size == (154, 120))
ok("colores correctos", img.getpixel((5, 5)) == (255, 0, 0) and img.getpixel((5, 100)) == (0, 0, 255))
ok("content-type image/png", r.headers.get("content-type") == "image/png")
ok("dentro del intervalo no repite foto", vig.al_medir(12.0, 5000) is None)

print("== Comando tomar_foto armada")
cmd = admin.table("comandos").insert({"dispositivo_id": disp, "tipo": "tomar_foto"}).execute().data[0]
agente.vuelta_red(3)
c = admin.table("comandos").select("estado, resultado").eq("id", cmd["id"]).single().execute().data
ok("queda ejecutado", c["estado"] == "ejecutado")
capturas = admin.table("capturas").select("foto_path").eq("dispositivo_id", disp).execute().data
ok("hay 2 capturas nuevas", len(capturas) == capturas_antes + 2)

print("== Reenvío del buffer (RNF-17)")
evento = {"dispositivo_id": disp, "tipo": "presencia", "descripcion": "reenvío",
          "foto_path": cap["foto_path"], "ocurrido_en": None}
original = admin.table("eventos").select("ocurrido_en").eq("foto_path", cap["foto_path"]).single().execute().data
evento["ocurrido_en"] = original["ocurrido_en"]
try:
    cliente.insertar_evento(evento)
    repetido = True
except Exception as e:
    print("     ", e)
    repetido = False
ok("insertar el mismo evento no da error", repetido)
ok("y no lo duplica", len(admin.table("eventos").select("id").eq("foto_path", cap["foto_path"]).execute().data) == 1)
ok("subir otra vez la misma foto devuelve False", cliente.subir_archivo("capturas", cap["foto_path"], r.content, "image/png") is False)

print("\n%s" % ("TODO BIEN" if not fallas else "%d FALLA(S)" % fallas))
