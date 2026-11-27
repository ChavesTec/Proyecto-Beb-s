"""Firmware del biberón (firmware/biberon) en CPython, con el hardware y la red simulados."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

CARPETA = Path(__file__).resolve().parents[1] / "firmware" / "biberon"
COMUN = CARPETA.parent / "comun"


class _Pin:
    OUT = 1

    def __init__(self, numero, modo=None, value=0):
        self.numero, self.v = numero, value

    def value(self, v=None):
        if v is None:
            return self.v
        self.v = v


class _DS:
    """DS18X20 falso: devuelve las temperaturas de `lecturas` en orden."""
    lecturas = []
    roms = [b"sonda"]

    def __init__(self, bus):
        pass

    def scan(self):
        return list(_DS.roms)

    def convert_temp(self):
        pass

    def read_temp(self, rom):
        valor = _DS.lecturas.pop(0)
        if isinstance(valor, Exception):
            raise valor
        return valor


sys.modules.setdefault("network", types.SimpleNamespace(STA_IF=0, WLAN=None))
sys.modules.setdefault("urequests", types.SimpleNamespace(request=None))
sys.modules["onewire"] = types.SimpleNamespace(OneWire=lambda pin: None)
sys.modules["ds18x20"] = types.SimpleNamespace(DS18X20=_DS)
sys.path.insert(0, str(CARPETA))
sys.path.insert(0, str(COMUN))

# machine solo mientras se importa hardware: las pruebas del móvil ponen su propio módulo.
_previo = sys.modules.get("machine")
sys.modules["machine"] = types.SimpleNamespace(Pin=_Pin)
import hardware  # noqa: E402

if _previo is None:
    del sys.modules["machine"]
else:
    sys.modules["machine"] = _previo
import termometro  # noqa: E402
from termometro import CALIENTE, EN_RANGO, FRIA, SIN_LECTURA, Cola, Termometro  # noqa: E402

_spec = importlib.util.spec_from_file_location("biberon_main", CARPETA / "main.py")
biberon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(biberon)


# ----------------------------------------------------------------- lógica
def test_rango_por_defecto_igual_a_la_base():
    from app.config.valores import COMANDOS_POR_TIPO, PREDETERMINADOS

    defecto = PREDETERMINADOS["biberon"]
    assert (termometro.TEMP_MIN, termometro.TEMP_MAX) == (defecto["temp_min"], defecto["temp_max"])
    assert COMANDOS_POR_TIPO["biberon"] == ("probar_luz",)   # la única orden que atiende


@pytest.mark.parametrize("t, estado", [(34.9, FRIA), (35, EN_RANGO), (37.5, EN_RANGO), (40, EN_RANGO),
                                       (40.1, CALIENTE), (None, SIN_LECTURA)])
def test_clasificar_igual_que_el_trigger(t, estado):
    assert termometro.clasificar(t, 35, 40) == estado


def test_leds_segun_estado():
    t = Termometro()
    t.al_medir(37)
    assert t.leds(0) == (False, True)            # verde
    t.al_medir(45)
    assert t.leds(0) == (True, False)            # rojo
    t.al_medir(20)
    assert t.leds(0) == (True, False)
    t.al_medir(None)
    assert t.leds(0) == (True, False) and t.leds(500) == (False, False)   # rojo parpadea


def test_cambio_de_rango_desde_la_app_reclasifica():
    t = Termometro()
    t.al_medir(38)
    assert t.estado == EN_RANGO
    assert t.aplicar_config("30.00", "37.00") is True     # PostgREST manda numeric como texto o número
    assert t.estado == CALIENTE and t.leds(0) == (True, False)


@pytest.mark.parametrize("t_min, t_max", [(40, 35), (36, 36), (None, 40), ("x", 40)])
def test_rango_invalido_se_ignora(t_min, t_max):
    t = Termometro()
    assert t.aplicar_config(t_min, t_max) is False
    assert (t.temp_min, t.temp_max) == (35, 40)


def test_al_medir_avisa_solo_si_cambia_el_estado():
    t = Termometro()
    assert t.al_medir(37) is True
    assert t.al_medir(37.4) is False
    assert t.al_medir(41) is True


def test_lectura_y_evento():
    t = Termometro()
    assert t.evento("2026-11-27T10:00:00Z") is None
    assert "aviso" in t.lectura()
    t.al_medir(36.66)
    assert t.lectura() == {"temperatura_biberon": 36.7}
    assert t.evento("2026-11-27T10:00:00Z") == {"tipo": "temperatura_biberon", "valor": 36.7, "unidad": "°C",
                                                 "ocurrido_en": "2026-11-27T10:00:00Z"}
    assert "ocurrido_en" not in t.evento(None)


def test_tipo_de_evento_aceptado_por_la_app():
    from app.config.valores import TIPOS_EVENTO

    assert "temperatura_biberon" in TIPOS_EVENTO


def test_cola_conserva_lo_que_falla_y_descarta_lo_mas_viejo():
    c = Cola(maximo=3)
    for i in range(5):
        c.agregar({"valor": i})
    c.agregar(None)
    assert [e["valor"] for e in c.elementos] == [2, 3, 4]
    enviados = []

    def insertar(e):
        if e["valor"] == 3:
            raise OSError("sin red")
        enviados.append(e["valor"])

    with pytest.raises(OSError):
        c.enviar(insertar)
    assert enviados == [2] and [e["valor"] for e in c.elementos] == [3, 4]


# --------------------------------------------------------------- hardware
def test_ds18b20_no_bloquea_y_descarta_lecturas_falsas(monkeypatch):
    reloj = [0]
    monkeypatch.setattr(hardware, "ticks_ms", lambda: reloj[0])
    _DS.lecturas = [36.5, 85, OSError("cable suelto")]
    s = hardware.SensorDS18B20(22)
    assert s.medir() is None           # pidió la conversión
    reloj[0] = 100
    assert s.medir() is None           # todavía convirtiendo
    reloj[0] = 800
    assert s.medir() == 36.5
    reloj[0] = 1600
    assert s.medir() is None           # 85 °C = lectura fallida
    reloj[0] = 2400
    assert s.medir() is None and s.roms == []   # error: vuelve a buscar la sonda


def test_sin_sonda_devuelve_none(monkeypatch):
    monkeypatch.setattr(_DS, "roms", [])
    assert hardware.SensorDS18B20(22).medir() is None


def test_leds_en_los_pines():
    leds = hardware.Leds(15, 14)
    assert (leds.rojo.numero, leds.verde.numero) == (15, 14)
    leds.mostrar(False, True)
    assert (leds.rojo.value(), leds.verde.value()) == (0, 1)
    leds.apagar()
    assert (leds.rojo.value(), leds.verde.value()) == (0, 0)


# ----------------------------------------------------------------- agente
class ClienteFalso:
    def __init__(self, config=None, comandos=None):
        self.config = config or {"temp_min": 35, "temp_max": 40}
        self.comandos = comandos or []
        self.senales, self.eventos, self.marcas = [], [], []
        self.columnas = None
        self.falla_eventos = False

    def iniciar_sesion(self):
        pass

    def id_dispositivo(self, codigo):
        assert codigo == "BIBERON-001"
        return "uuid-bib"

    def leer_config(self, dispositivo_id, columnas):
        self.columnas = columnas
        return self.config

    def comandos_pendientes(self, dispositivo_id):
        pendientes, self.comandos = self.comandos, []
        return pendientes

    def marcar_comando(self, comando_id, estado, resultado=None, ejecutado_en=None):
        self.marcas.append((comando_id, estado, resultado))

    def registrar_senal(self, dispositivo_id, lectura):
        self.senales.append(lectura)

    def insertar_evento(self, evento):
        if self.falla_eventos:
            raise OSError("sin red")
        self.eventos.append(evento)


def _agente(cliente):
    t = Termometro()
    a = biberon.Agente({"codigo_dispositivo": "BIBERON-001"}, t, cliente)
    a.preparar = lambda: (setattr(a, "dispositivo_id", cliente.id_dispositivo("BIBERON-001")), a.aplicar_config())
    return a, t


def test_vuelta_lee_rango_envia_senal_y_muestra():
    cliente = ClienteFalso(config={"temp_min": 30, "temp_max": 38})
    a, t = _agente(cliente)
    t.al_medir(39)
    a.vuelta(0)
    assert cliente.columnas == "temp_min,temp_max"
    assert t.estado == CALIENTE
    assert cliente.senales == [{"temperatura_biberon": 39.0}]
    assert cliente.eventos[0]["tipo"] == "temperatura_biberon"
    assert cliente.eventos[0]["dispositivo_id"] == "uuid-bib"
    a.vuelta(1)
    assert len(cliente.eventos) == 1        # la siguiente muestra espera al minuto


def test_cambio_de_estado_manda_muestra_inmediata():
    cliente = ClienteFalso()
    a, t = _agente(cliente)
    leds = hardware.Leds(15, 14)
    sensor = types.SimpleNamespace(medir=lambda: 37)
    biberon.medir_y_mostrar(t, a, sensor, leds, 0)
    a.vuelta(0)
    assert (leds.rojo.value(), leds.verde.value()) == (0, 1)
    sensor.medir = lambda: 42
    biberon.medir_y_mostrar(t, a, sensor, leds, 1000)
    assert (leds.rojo.value(), leds.verde.value()) == (1, 0)
    a.vuelta(1)
    assert [e["valor"] for e in cliente.eventos] == [37.0, 42.0]


def test_sin_red_se_reenvia_despues():
    cliente = ClienteFalso()
    a, t = _agente(cliente)
    t.al_medir(36)
    cliente.falla_eventos = True
    with pytest.raises(OSError):
        a.vuelta(0)
    assert len(a.cola) == 1
    cliente.falla_eventos = False
    a.vuelta(1)
    assert len(a.cola) == 0 and len(cliente.eventos) == 1


def test_comandos():
    cliente = ClienteFalso(comandos=[{"id": 1, "tipo": "probar_luz"}, {"id": 2, "tipo": "tomar_foto"}])
    a, t = _agente(cliente)
    a.vuelta(0)
    assert cliente.marcas[0] == (1, "ejecutado", None)
    assert cliente.marcas[1][:2] == (2, "fallido")
    leds = hardware.Leds(15, 14)
    biberon.pintar(t, a, leds, termometro.ticks_ms())
    assert leds.rojo.value() == leds.verde.value()      # destello: los dos juntos
