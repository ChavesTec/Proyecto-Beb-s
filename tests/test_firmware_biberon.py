"""Firmware del biberón (firmware/biberon) en CPython, con el hardware y la red simulados."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

CARPETA = Path(__file__).resolve().parents[1] / "firmware" / "biberon"
COMUN = CARPETA.parent / "comun"


class _Pin:
    IN, OUT, PULL_UP = 0, 1, 2

    def __init__(self, numero, modo=None, pull=None, value=0):
        self.numero, self.modo, self.pull = numero, modo, pull
        self.v = 1 if pull == _Pin.PULL_UP else value

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
from termometro import CALIENTE, EN_RANGO, FRIA, SIN_LECTURA, Boton, Cola, Termometro  # noqa: E402

_spec = importlib.util.spec_from_file_location("biberon_main", CARPETA / "main.py")
biberon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(biberon)


def _midiendo():
    t = Termometro()
    t.alternar(0, 600_000)
    return t


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
    t = _midiendo()
    t.al_medir(37)
    assert t.leds(0) == (False, True)            # verde
    t.al_medir(45)
    assert t.leds(0) == (True, False)            # rojo
    t.al_medir(20)
    assert t.leds(0) == (True, False)
    t.al_medir(None)
    assert t.leds(0) == (True, False) and t.leds(500) == (False, False)   # rojo parpadea


def test_cambio_de_rango_desde_la_app_reclasifica():
    t = _midiendo()
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
    t = _midiendo()
    assert t.evento("2026-11-27T10:00:00Z") is None
    assert "aviso" in t.lectura()
    t.al_medir(36.66)
    assert t.lectura() == {"midiendo": True, "temperatura_biberon": 36.7}
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


def _agente(cliente, midiendo=True):
    t = _midiendo() if midiendo else Termometro()
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
    assert cliente.senales == [{"midiendo": True, "temperatura_biberon": 39.0}]
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


def test_tras_muchas_fallas_pide_reiniciar_wifi_y_sesion():
    cliente = ClienteFalso()
    a, t = _agente(cliente)
    a.vuelta = lambda contador: (_ for _ in ()).throw(OSError("ECONNRESET"))
    cliente.token = "jwt"
    pedidos = [a.vuelta_segura(i) for i in range(biberon.FALLAS_PARA_RECONECTAR)]
    assert pedidos == [False] * (biberon.FALLAS_PARA_RECONECTAR - 1) + [True]
    assert cliente.token is None and a.fallas == 0


def test_una_vuelta_buena_reinicia_el_contador():
    a, t = _agente(ClienteFalso())
    a.fallas = 5
    assert a.vuelta_segura(0) is False and a.fallas == 0


class _WLAN:
    def __init__(self):
        self.conectada, self.conexiones, self.desconexiones, self.pm = False, 0, 0, None

    def isconnected(self):
        return self.conectada

    def active(self, v=None):
        return True

    def config(self, pm=None):
        self.pm = pm

    def connect(self, ssid, clave):
        self.conexiones += 1

    def disconnect(self):
        self.desconexiones += 1
        self.conectada = False


def test_wifi_reconecta_sin_bloquear_y_sin_ahorro_de_energia(monkeypatch):
    wlan = _WLAN()
    monkeypatch.setattr(biberon.network, "WLAN", lambda modo: wlan, raising=False)
    reloj = [0]
    monkeypatch.setattr(biberon, "ticks_ms", lambda: reloj[0])
    w = biberon.Wifi({"wifi_ssid": "casa", "wifi_clave": "x"}, reintento_s=30)
    assert w.conectado() is False and wlan.conexiones == 1 and wlan.pm == biberon.PM_SIN_AHORRO
    reloj[0] = 10_000
    assert w.conectado() is False and wlan.conexiones == 1      # espera antes de reintentar
    reloj[0] = 31_000
    w.conectado()
    assert wlan.conexiones == 2
    wlan.conectada = True
    assert w.conectado() is True
    w.reiniciar()
    assert wlan.desconexiones == 1
    w.conectado()
    assert wlan.conexiones == 3                                  # reintenta enseguida


def test_bucle_leds_sobrevive_a_un_error_y_apaga_al_salir(monkeypatch):
    a, t = _agente(ClienteFalso())
    leds = hardware.Leds(15, 14)
    vueltas = [0]

    def medir():
        vueltas[0] += 1
        if vueltas[0] == 1:
            raise OSError("onewire")
        if vueltas[0] == 3:
            a.activo = False
        return 37

    monkeypatch.setattr(biberon.time, "sleep_ms", lambda ms: None, raising=False)
    pulsador = types.SimpleNamespace(presionado=lambda: False)
    biberon.bucle_leds(t, a, types.SimpleNamespace(medir=medir), leds, Boton(), pulsador, 600_000)
    assert vueltas[0] == 3 and (leds.rojo.value(), leds.verde.value()) == (0, 0)


# ------------------------------------------------------------------ botón
def test_boton_cuenta_cada_pulsacion_una_vez_y_filtra_rebotes():
    b = Boton(bloqueo_ms=300)
    lecturas = [(False, 0), (True, 50), (True, 100), (False, 150), (True, 200), (False, 250),
                (True, 400), (False, 450), (True, 800)]
    assert [b.pulsado(p, ms) for p, ms in lecturas] == [False, True, False, False, False, False,
                                                       True, False, True]


def test_sin_medir_leds_apagados_y_no_manda_temperaturas():
    t = Termometro()
    t.al_medir(45)
    assert t.leds(0) == (False, False)
    assert t.lectura() == {"midiendo": False}
    assert t.evento("2026-11-27T10:00:00Z") is None


def test_medicion_empieza_se_detiene_y_vence():
    t = Termometro()
    assert t.alternar(1000, 5000) is True and t.midiendo
    assert t.vencio(5999) is False
    assert t.vencio(6000) is True and not t.midiendo
    t.alternar(0, 5000)
    assert t.alternar(100, 5000) is False and not t.midiendo     # segunda pulsación detiene


def test_pulsar_el_boton_manda_la_primera_muestra_enseguida():
    cliente = ClienteFalso()
    a, t = _agente(cliente, midiendo=False)
    leds = hardware.Leds(15, 14)
    sensor = types.SimpleNamespace(medir=lambda: 30)
    boton, pulsador = Boton(), hardware.Pulsador(13)
    assert pulsador.pin.numero == 13 and pulsador.pin.pull == _Pin.PULL_UP
    biberon.medir_y_mostrar(t, a, sensor, leds, 0)
    a.vuelta(0)
    assert cliente.eventos == [] and cliente.senales == [{"midiendo": False}]
    assert (leds.rojo.value(), leds.verde.value()) == (0, 0)

    pulsador.pin.value(0)                                       # se pulsa (a GND)
    biberon.atender_boton(t, a, boton, pulsador, 1000, 600_000)
    biberon.medir_y_mostrar(t, a, sensor, leds, 1000)
    assert (leds.rojo.value(), leds.verde.value()) == (1, 0)    # 30 °C: demasiado fría
    a.vuelta(1)
    assert [e["valor"] for e in cliente.eventos] == [30.0]

    pulsador.pin.value(1)
    biberon.atender_boton(t, a, boton, pulsador, 601_000, 600_000)   # pasaron los 10 min
    assert not t.midiendo
    biberon.medir_y_mostrar(t, a, sensor, leds, 601_000)
    assert (leds.rojo.value(), leds.verde.value()) == (0, 0)
    a.ultima_muestra = -100_000
    a.vuelta(2)
    assert len(cliente.eventos) == 1                            # ya no manda muestras
