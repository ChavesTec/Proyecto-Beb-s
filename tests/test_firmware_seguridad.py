"""Firmware de la seguridad (firmware/seguridad) en CPython, con hardware y red simulados."""
import importlib
import importlib.util
import io
import json
import struct
import sys
import types
import zlib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "firmware" / "seguridad"
COMUN = RAIZ / "firmware" / "comun"

sys.modules.setdefault("urequests", types.SimpleNamespace(request=None))  # cada prueba lo reemplaza
sys.modules.setdefault("network", types.SimpleNamespace(STA_IF=0, WLAN=None))
for carpeta in (CARPETA, COMUN):
    if str(carpeta) not in sys.path:
        sys.path.insert(0, str(carpeta))

import imagen  # noqa: E402
import supabase_micro  # noqa: E402
import vigilancia  # noqa: E402
from vigilancia import FUERA_DE_RANGO, Cola, Vigilancia  # noqa: E402

# firmware/movil también tiene un main.py: este se carga con otro nombre.
_spec = importlib.util.spec_from_file_location("seguridad_main", CARPETA / "main.py")
seg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seg)

ANCHO, ALTO = 154, 120


def rgb565(r, g, b):
    """(r, g, b) de 8 bits -> los 2 bytes RGB565, byte alto primero."""
    v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    return bytes([v >> 8, v & 0xFF])


def cuadro(ancho=ANCHO, alto=ALTO):
    """Mitad superior roja, inferior azul, primera columna verde."""
    datos = bytearray()
    for y in range(alto):
        for x in range(ancho):
            color = (0, 255, 0) if x == 0 else ((255, 0, 0) if y < alto // 2 else (0, 0, 255))
            datos += rgb565(*color)
    return datos


# ============================================================ PNG
def test_png_valido_con_pillow_y_colores_correctos():
    Image = pytest.importorskip("PIL.Image")
    salida = io.BytesIO()
    imagen.escribir_png(salida, cuadro(), ANCHO, ALTO)
    datos = salida.getvalue()
    assert len(datos) == imagen.tamano_png(ANCHO, ALTO)
    assert len(datos) < 150 * 1024                       # RNF-05: cabe en el bucket
    foto = Image.open(io.BytesIO(datos))
    foto.load()                                          # Pillow verifica los CRC de cada chunk
    assert foto.size == (ANCHO, ALTO) and foto.mode == "RGB"
    assert foto.getpixel((10, 5)) == (255, 0, 0)
    assert foto.getpixel((10, ALTO - 5)) == (0, 0, 255)
    assert foto.getpixel((0, 30)) == (0, 255, 0)


def test_png_zlib_y_adler_correctos():
    salida = io.BytesIO()
    imagen.escribir_png(salida, cuadro(8, 4), 8, 4)
    datos = salida.getvalue()
    largo = struct.unpack(">I", datos[33:37])[0]
    assert datos[37:41] == b"IDAT"
    crudo = zlib.decompress(datos[41:41 + largo])        # zlib valida el adler32
    assert len(crudo) == 4 * (1 + 3 * 8) and crudo[0] == 0
    assert zlib.crc32(datos[37:41 + largo]) == struct.unpack(">I", datos[41 + largo:45 + largo])[0]
    assert datos.endswith(b"IEND\xaeB`\x82")


def test_orden_de_bytes():
    alto_primero = bytearray(rgb565(255, 0, 0))
    bajo_primero = bytearray(reversed(alto_primero))
    assert imagen.rgb565_a_rgb888(alto_primero, 1, 1, True) == bytes([255, 0, 0])
    assert imagen.rgb565_a_rgb888(bajo_primero, 1, 1, False) == bytes([255, 0, 0])
    assert imagen.rgb565_a_rgb888(alto_primero, 1, 1, False) != bytes([255, 0, 0])


def test_crc_python_igual_a_zlib():
    for datos in (b"", b"IHDR", bytes(range(256)) * 3):
        assert imagen.crc32_python(datos) == zlib.crc32(datos)
        assert imagen.crc32_python(datos, 12345) == zlib.crc32(datos, 12345)


def test_png_rechaza_buffer_corto():
    with pytest.raises(ValueError):
        imagen.escribir_png(io.BytesIO(), bytearray(10), ANCHO, ALTO)


# ============================================================ vigilancia
def test_desarmada_no_hace_nada():
    v = Vigilancia(20)
    assert v.al_medir(5, 0) is None and v.al_medir(5, 60_000) is None


def test_armada_foto_e_intervalo():
    v = Vigilancia(20)
    v.aplicar_config(True, 30)
    assert v.al_medir(10, 0) == "foto"          # primera presencia: foto
    assert v.al_medir(10, 5_000) is None        # sigue ahí, dentro del intervalo
    assert v.al_medir(FUERA_DE_RANGO, 6_000) is None
    assert v.al_medir(12, 8_000) == "evento"    # presencia nueva, sin foto todavía (CA-26.3)
    assert v.al_medir(12, 29_999) is None
    assert v.al_medir(12, 30_000) == "foto"     # pasó el intervalo


def test_sin_presencia():
    v = Vigilancia(20)
    v.aplicar_config(True, 30)
    for d in (None, FUERA_DE_RANGO, 20, 150):
        assert v.al_medir(d, 0) is None and not v.en_presencia


def test_config_invalida_conserva_el_intervalo():
    v = Vigilancia()
    assert v.aplicar_config(True, 10) is True
    assert v.aplicar_config(True, 10) is False
    v.aplicar_config(True, 0)
    v.aplicar_config(True, None)
    assert v.intervalo_s == 10


# ============================================================ cola
@pytest.fixture
def en_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _foto(cola, nombre, tam=100):
    with open(cola.carpeta + "/" + nombre, "wb") as f:
        f.write(b"x" * tam)
    return nombre


def test_cola_persiste_y_descarta_referencias_rotas(en_tmp):
    cola = Cola(espacio_libre=lambda: 10**9)
    cola.agregar("presencia", "2026-11-09T21:00:00Z", "a", _foto(cola, "a.png"))
    cola.agregar("presencia", "2026-11-09T21:00:05Z", "b", _foto(cola, "b.png"))
    (en_tmp / "pendientes" / "b.png").unlink()
    otra = Cola(espacio_libre=lambda: 10**9)       # como tras un reinicio
    assert [e["descripcion"] for e in otra.elementos] == ["a"]


def test_flash_llena_borra_la_foto_mas_vieja_y_conserva_el_evento(en_tmp):
    libre = {"bytes": 50_000}
    cola = Cola(espacio_libre=lambda: libre["bytes"])
    cola.agregar("presencia", "t1", "vieja", _foto(cola, "vieja.png"))
    cola.agregar("presencia", "t2", "nueva", _foto(cola, "nueva.png"))

    def borrar(ruta, _original=vigilancia.os.remove):
        _original(ruta)
        libre["bytes"] += 40_000

    vigilancia.os.remove, original = borrar, vigilancia.os.remove
    try:
        assert cola.hacer_espacio(56_000) is True
    finally:
        vigilancia.os.remove = original
    assert [e["foto"] for e in cola.elementos] == [None, "nueva.png"]
    assert len(cola) == 2 and not (en_tmp / "pendientes" / "vieja.png").exists()


def test_flash_llena_sin_fotos_que_borrar(en_tmp):
    cola = Cola(espacio_libre=lambda: 0)
    cola.agregar("presencia", "t1", "sin foto")
    assert cola.hacer_espacio(56_000) is False


def test_cola_limita_elementos(en_tmp):
    cola = Cola(espacio_libre=lambda: 10**9, max_elementos=3)
    for i in range(5):
        cola.agregar("presencia", "t%d" % i, str(i), _foto(cola, "%d.png" % i))
    assert [e["descripcion"] for e in cola.elementos] == ["2", "3", "4"]
    assert sorted(p.name for p in (en_tmp / "pendientes").glob("*.png")) == ["2.png", "3.png", "4.png"]


# ============================================================ agente
class ClienteFalso:
    def __init__(self):
        self.config = {"seguridad_armada": True, "seguridad_intervalo_foto_s": 30}
        self.comandos = []
        self.marcados = []
        self.subidas = []
        self.eventos = []
        self.senales = []
        self.falla_evento = False
        self.columnas = None

    def iniciar_sesion(self):
        pass

    def id_dispositivo(self, codigo):
        assert codigo == "SEGURIDAD-001"
        return "d-seg"

    def leer_config(self, dispositivo_id, columnas):
        self.columnas = columnas
        return dict(self.config)

    def comandos_pendientes(self, dispositivo_id):
        pendientes, self.comandos = self.comandos, []
        return pendientes

    def marcar_comando(self, comando_id, estado, resultado=None, ejecutado_en=None):
        self.marcados.append((comando_id, estado, resultado))

    def subir_archivo(self, bucket, ruta, datos, tipo):
        self.subidas.append((bucket, ruta, bytes(datos), tipo))
        return True

    def insertar_evento(self, evento):
        if self.falla_evento:
            raise supabase_micro.ErrorSupabase(503, "sin red")
        self.eventos.append(evento)

    def registrar_senal(self, dispositivo_id, lectura):
        self.senales.append(lectura)


class CamaraFalsa:
    def __init__(self, ok=True):
        self.ancho, self.alto = ANCHO, ALTO
        self.frame = cuadro()
        self.lista = True
        self.ok = ok

    def capturar(self):
        return self.ok


@pytest.fixture
def agente(en_tmp, monkeypatch):
    monkeypatch.setattr(seg, "sincronizar_hora", lambda: True)
    monkeypatch.setattr(seg, "ahora_iso", lambda: "2026-11-09T21:52:49Z")
    guardados = []
    a = seg.Agente({"codigo_dispositivo": "SEGURIDAD-001"}, ClienteFalso(), Vigilancia(20),
                   Cola(espacio_libre=lambda: 10**9), CamaraFalsa(), guardados.append)
    a.guardados = guardados
    return a


def test_arranque_lee_el_armado(agente):
    agente.vuelta_red(0)
    assert agente.dispositivo_id == "d-seg" and agente.vigilancia.armada is True
    assert agente.cliente.columnas == "seguridad_armada,seguridad_intervalo_foto_s"
    assert agente.guardados == [agente.vigilancia]          # se guarda para arrancar sin red
    assert agente.cliente.senales[0]["armada"] is True


def test_presencia_con_foto_llega_a_la_base(agente):
    Image = pytest.importorskip("PIL.Image")
    agente.vuelta_red(1)
    agente.registrar_presencia(agente.vigilancia.al_medir(12.3, 0), 12.3)
    agente.enviar_pendientes()
    bucket, ruta, datos, tipo = agente.cliente.subidas[0]
    assert bucket == "capturas" and tipo == "image/png"
    assert ruta.startswith("d-seg/20261109T215249-") and ruta.endswith(".png")   # carpeta del dispositivo (RNF-23)
    assert Image.open(io.BytesIO(datos)).size == (ANCHO, ALTO)
    assert agente.cliente.eventos == [{"dispositivo_id": "d-seg", "tipo": "presencia", "descripcion": "Presencia a 12 cm",
                                       "foto_path": ruta, "ocurrido_en": "2026-11-09T21:52:49Z"}]
    assert len(agente.cola) == 0 and not list(Path("pendientes").glob("*.png"))


def test_presencia_sin_foto_dentro_del_intervalo(agente):
    agente.vuelta_red(1)
    agente.registrar_presencia("evento", 15)
    agente.enviar_pendientes()
    assert agente.cliente.subidas == [] and agente.cliente.eventos[0]["foto_path"] is None


def test_sin_red_conserva_y_no_vuelve_a_subir_la_foto(agente):
    agente.vuelta_red(1)
    agente.cliente.falla_evento = True
    agente.registrar_presencia("foto", 10)
    with pytest.raises(supabase_micro.ErrorSupabase):
        agente.enviar_pendientes()
    assert len(agente.cola) == 1 and agente.cola.primero()["subida"] is True
    agente.cliente.falla_evento = False
    agente.enviar_pendientes()
    assert len(agente.cliente.subidas) == 1                                  # no la duplica
    assert agente.cliente.eventos[0]["ocurrido_en"] == "2026-11-09T21:52:49Z"   # hora original (RNF-17)


def test_camara_que_falla_registra_el_evento_sin_foto(agente):
    agente.camara.ok = False
    agente.vuelta_red(1)
    assert agente.tomar_foto("presencia", "x") is False
    agente.enviar_pendientes()
    assert agente.cliente.eventos[0]["foto_path"] is None


def test_comando_tomar_foto(agente):
    agente.vuelta_red(1)
    agente.cliente.comandos = [{"id": 7, "tipo": "tomar_foto"}, {"id": 8, "tipo": "probar_luz"}]
    agente.atender_comandos()
    assert agente.cliente.marcados == [(7, "ejecutado", "Foto tomada"),
                                       (8, "fallido", "La seguridad no admite la orden probar_luz")]
    assert agente.cliente.eventos[0]["descripcion"] == "Foto pedida desde la app"
    assert agente.cliente.eventos[0]["foto_path"] == agente.cliente.subidas[0][1]


def test_comando_tomar_foto_desarmada_falla(agente):
    agente.cliente.config["seguridad_armada"] = False
    agente.vuelta_red(1)
    agente.cliente.comandos = [{"id": 9, "tipo": "tomar_foto"}]
    agente.atender_comandos()
    assert agente.cliente.marcados[0][1] == "fallido" and "desarmada" in agente.cliente.marcados[0][2]
    assert agente.cliente.subidas == [] and len(agente.cola) == 0


def test_lectura_para_la_app(agente):
    agente.vuelta_red(1)
    agente.vigilancia.al_medir(42.27, 0)
    assert agente.lectura() == {"armada": True, "camara": "lista", "sensor": "ok", "presencia": False,
                                "pendientes": 0, "distancia_cm": 42.3}
    agente.vigilancia.al_medir(None, 0)
    assert agente.lectura()["sensor"] == "sin_respuesta" and "distancia_cm" not in agente.lectura()


def test_dos_eventos_en_el_mismo_segundo_no_chocan(monkeypatch):
    monkeypatch.setattr(seg.time, "gmtime", lambda: (2026, 11, 9, 21, 52, 49, 0, 313))
    monkeypatch.setattr(seg, "_ultima_hora", [None, 0])
    assert [seg.ahora_iso() for _ in range(3)] == ["2026-11-09T21:52:49.000Z", "2026-11-09T21:52:49.001Z",
                                                   "2026-11-09T21:52:49.002Z"]
    monkeypatch.setattr(seg.time, "gmtime", lambda: (2000, 1, 1, 0, 0, 0, 0, 1))
    assert seg.ahora_iso() is None                                   # reloj sin sincronizar


def test_sello_y_estado(en_tmp):
    assert seg.sello("2026-11-09T21:52:49.001Z") == "20261109T215249001"
    assert seg.sello("2026-11-09T21:52:49Z") == "20261109T215249"
    assert seg.sello(None).startswith("sinhora")
    v = Vigilancia()
    v.aplicar_config(True, 45)
    seg.guardar_estado(v)
    assert seg.cargar_estado() == {"armada": True, "intervalo_s": 45}


# ============================================================ cliente HTTP
class _Respuesta:
    def __init__(self, estado, texto=""):
        self.status_code, self.text = estado, texto

    def close(self):
        pass


@pytest.fixture
def cliente(monkeypatch):
    llamadas, respuestas = [], []

    def pedir(metodo, url, data=None, headers=None, timeout=None):
        llamadas.append((metodo, url, data, dict(headers)))
        return respuestas.pop(0)

    monkeypatch.setattr(supabase_micro.requests, "request", pedir, raising=False)
    c = supabase_micro.ClienteSupabase("http://x", "anon", "ctrl@x", "secreta")
    c.token, c.vence = "t1", 10**12
    return c, llamadas, respuestas


def test_subir_archivo_envia_bytes_crudos(cliente):
    c, llamadas, respuestas = cliente
    respuestas.append(_Respuesta(200, '{"Key": "capturas/d1/f.png"}'))
    assert c.subir_archivo("capturas", "d1/f 1.png", b"\x89PNG", "image/png") is True
    metodo, url, data, enc = llamadas[0]
    assert (metodo, url, data) == ("POST", "http://x/storage/v1/object/capturas/d1/f%201.png", b"\x89PNG")
    assert enc["Content-Type"] == "image/png" and enc["Authorization"] == "Bearer t1"


def test_subir_archivo_repetido_no_es_error(cliente):
    c, _, respuestas = cliente
    respuestas.append(_Respuesta(400, '{"statusCode": "409", "error": "Duplicate", "message": "The resource already exists"}'))
    assert c.subir_archivo("capturas", "d1/f.png", b"x", "image/png") is False
    respuestas.append(_Respuesta(413, '{"error": "Payload too large"}'))
    with pytest.raises(supabase_micro.ErrorSupabase):
        c.subir_archivo("capturas", "d1/f.png", b"x", "image/png")


def test_insertar_evento_ignora_duplicados(cliente):
    c, llamadas, respuestas = cliente
    respuestas.append(_Respuesta(201, ""))
    c.insertar_evento({"dispositivo_id": "d1", "tipo": "presencia"})
    metodo, url, data, enc = llamadas[0]
    assert url == "http://x/rest/v1/eventos?on_conflict=dispositivo_id,ocurrido_en,tipo"
    assert enc["Prefer"] == "resolution=ignore-duplicates,return=minimal"
    assert json.loads(data) == {"dispositivo_id": "d1", "tipo": "presencia"}


def test_leer_config_por_columnas_y_compatible_con_el_movil(cliente):
    c, llamadas, respuestas = cliente
    respuestas += [_Respuesta(200, '[{"seguridad_armada": true}]'), _Respuesta(200, "[]")]
    assert c.leer_config("d1", "seguridad_armada") == {"seguridad_armada": True}
    assert c.leer_config("d1") is None
    assert "select=seguridad_armada&" in llamadas[0][1]
    assert "select=movil_encendido,movil_secuencia,movil_velocidad&" in llamadas[1][1]


# ============================================================ sensor ultrasónico
def test_ultrasonico(monkeypatch):
    duraciones = []

    class Pin:
        OUT, IN = 1, 0

        def __init__(self, n, modo=None):
            self.valor = 0

        def __call__(self, v=None):
            if v is None:
                return 0          # ECHO ya en bajo
            self.valor = v

    maquina = types.SimpleNamespace(Pin=Pin, time_pulse_us=lambda pin, nivel, espera: duraciones.pop(0))
    monkeypatch.setitem(sys.modules, "machine", maquina)
    reloj = types.SimpleNamespace(ticks_us=lambda: 0, ticks_diff=lambda a, b: a - b, sleep_us=lambda us: None)
    sys.modules.pop("ultrasonico", None)
    ultrasonico = importlib.import_module("ultrasonico")
    monkeypatch.setattr(ultrasonico, "time", reloj)
    sensor = ultrasonico.Ultrasonico()
    duraciones += [-2, -1, 1160]
    assert sensor.medir() is None                       # no respondió
    assert sensor.medir() == FUERA_DE_RANGO             # nada al frente
    assert sensor.medir() == pytest.approx(20.0)        # 1160 µs = 20 cm
    sys.modules.pop("ultrasonico", None)


# ============================================================ app
def test_galeria_amplia_las_fotos_pequenas():
    Image = pytest.importorskip("PIL.Image")
    galeria = pytest.importorskip("app.ui.pantallas.galeria")
    assert galeria.ampliada(Image.new("RGB", (154, 120))).size == (616, 480)
    assert galeria.ampliada(Image.new("RGB", (640, 480))).size == (640, 480)


def test_migracion_acepta_png():
    sql = (RAIZ / "supabase" / "migrations" / "20261110000000_capturas_png.sql").read_text(encoding="utf-8")
    assert "'image/png'" in sql and "'image/jpeg'" in sql
