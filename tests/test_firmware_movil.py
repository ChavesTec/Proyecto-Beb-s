"""Firmware del móvil (firmware/movil) en CPython, con el hardware simulado."""
import sys
import time
import types
from pathlib import Path

import pytest

CARPETA = Path(__file__).resolve().parents[1] / "firmware" / "movil"


class _PWM:
    def __init__(self, pin):
        self.valor = 0

    def freq(self, f):
        pass

    def duty_u16(self, v):
        self.valor = v


class _NeoPixel(list):
    def __init__(self, pin, n):
        super().__init__([(0, 0, 0)] * n)
        self.escrituras = 0

    def write(self):
        self.escrituras += 1


class _Pin:
    OUT = 1

    def __init__(self, *a, **k):
        pass


sys.modules.setdefault("machine", types.SimpleNamespace(PWM=_PWM, Pin=_Pin))
sys.modules.setdefault("neopixel", types.SimpleNamespace(NeoPixel=_NeoPixel))
sys.modules.setdefault("urequests", types.SimpleNamespace(request=None))  # cada prueba lo reemplaza
sys.path.insert(0, str(CARPETA))

import luces  # noqa: E402
import salidas  # noqa: E402
import supabase_micro  # noqa: E402


class SalidaFalsa:
    def __init__(self, n=6):
        self.cantidad = n
        self.cuadros = []
        self.apagados = 0

    def escribir(self, cuadro):
        self.cuadros.append(list(cuadro))

    def apagar(self):
        self.apagados += 1
        self.cuadros.append([0] * self.cantidad)


def test_tabla_de_secuencias_igual_a_la_app():
    from app.config.valores import SECUENCIAS_MOVIL, VELOCIDADES_MOVIL

    assert set(luces.NUMERO_A_SECUENCIA) == set(SECUENCIAS_MOVIL)
    assert set(luces.NUMERO_A_VELOCIDAD) == set(VELOCIDADES_MOVIL)
    assert set(luces.NUMERO_A_SECUENCIA.values()) == set(luces.SECUENCIAS)


@pytest.mark.parametrize("n", [6, 16])
@pytest.mark.parametrize("nombre", list(luces.SECUENCIAS))
def test_cada_cuadro_tiene_un_brillo_por_led(nombre, n):
    funcion = luces.SECUENCIAS[nombre][2]
    for paso in range(luces.pasos_de(nombre, n)):
        cuadro = funcion(paso, n)
        assert len(cuadro) == n and all(0 <= b <= 100 for b in cuadro)


def test_progresiva_termina_apagada_y_ronda_recorre():
    n = 6
    assert luces.cuadro_progresiva(2 * n - 1, n) == [0] * n
    assert [luces.cuadro_ronda(p, n).index(100) for p in range(n)] == list(range(n))


def test_grupos_de_color_cubren_todos_los_leds():
    for n in (6, 16):
        grupos = luces.grupos_de_color(n)
        assert sorted(i for g in grupos for i in g) == list(range(n))


def test_encender_desde_la_base_y_apagar_todo():
    salida = SalidaFalsa()
    movil = luces.MovilLed(salida)
    assert movil.aplicar_config(True, 5, 2) is True
    movil.actualizar()
    assert salida.cuadros[-1] == [100, 0, 0, 0, 0, 0]       # ronda, paso 0
    movil.aplicar_config(False, 5, 2)
    assert salida.cuadros[-1] == [0] * 6 and movil.lectura()["encendido"] is False   # CA-20.2


def test_cambiar_velocidad_no_reinicia_la_secuencia():
    movil = luces.MovilLed(SalidaFalsa())
    movil.aplicar_config(True, 5, 2)
    movil.actualizar()
    movil.paso = 3
    movil.aplicar_config(True, 5, 3)          # CA-21.1
    assert movil.paso == 3 and movil.velocidad == "rapida"
    movil.aplicar_config(True, 1, 3)          # cambiar de secuencia sí empieza de cero
    assert movil.paso == 0


def test_intervalo_respeta_el_minimo():
    movil = luces.MovilLed(SalidaFalsa())
    movil.aplicar_config(True, 4, 3)          # suave, rápida
    assert movil._intervalo_ms() >= luces.SECUENCIAS["suave"][1]


def test_valores_desconocidos_no_rompen_y_se_informan():
    movil = luces.MovilLed(SalidaFalsa())
    movil.aplicar_config(True, 99, 7)
    lectura = movil.lectura()
    assert lectura["secuencia"] == 1 and lectura["velocidad"] == 2 and lectura["aviso"] == "secuencia_desconocida"


def test_sin_conexion_apaga_y_lo_informa():
    movil = luces.MovilLed(SalidaFalsa())
    movil.aplicar_config(True, 1, 2)
    movil.apagar_sin_conexion()
    assert movil.lectura() == {"encendido": False, "secuencia": 1, "velocidad": 2, "motivo": "sin_conexion"}
    movil.aplicar_config(True, 1, 2)          # vuelve la red y la base dice encendido
    assert movil.lectura()["encendido"] is True


def test_destello_de_prueba_y_vuelta_al_estado_anterior():
    salida = SalidaFalsa()
    movil = luces.MovilLed(salida)
    movil.destello(50)
    assert salida.cuadros[-1] == [100] * 6
    time.sleep(0.08)
    movil.actualizar()
    assert salida.cuadros[-1] == [0] * 6      # estaba apagado: vuelve a apagado


def test_salidas_pwm_y_neopixel():
    pwm = salidas.SalidaPWM([2, 3], brillo_maximo=80)
    pwm.escribir([100, 50])
    assert [l.valor for l in pwm.leds] == [52428, 26214]
    pwm.apagar()
    assert [l.valor for l in pwm.leds] == [0, 0]
    anillo = salidas.SalidaNeoPixel(23, 16, brillo_maximo=30)
    anillo.escribir([100] + [0] * 15)
    assert anillo.np[0] != (0, 0, 0) and max(anillo.np[0]) <= 255 * 30 // 100 and anillo.np[1] == (0, 0, 0)


# ------------------------------------------------------------ cliente HTTP
class _Respuesta:
    def __init__(self, estado, texto):
        self.status_code, self.text = estado, texto

    def close(self):
        pass


def test_cliente_reintenta_con_401_y_no_expone_la_clave(monkeypatch):
    llamadas = []
    respuestas = iter([
        _Respuesta(200, '{"access_token": "t1", "refresh_token": "r1", "expires_in": 3600}'),
        _Respuesta(401, '{"message": "JWT expired"}'),
        _Respuesta(200, '{"access_token": "t2", "refresh_token": "r2", "expires_in": 3600}'),
        _Respuesta(200, '[{"id": "d1", "codigo": "MOVIL-001"}]'),
    ])

    def pedir(metodo, url, data=None, headers=None, timeout=None):
        llamadas.append((metodo, url, data, dict(headers)))
        return next(respuestas)

    monkeypatch.setattr(supabase_micro.requests, "request", pedir, raising=False)
    c = supabase_micro.ClienteSupabase("http://x", "anon", "ctrl@x", "secreta")
    c.iniciar_sesion()
    assert c.id_dispositivo("MOVIL-001") == "d1"
    assert "grant_type=refresh_token" in llamadas[2][1]          # renovó con el refresh token
    assert llamadas[3][3]["Authorization"] == "Bearer t2"
    assert all("secreta" not in str(e) for e in (c.__dict__.get("token"), c.__dict__.get("refresco")))


def test_codificar_url():
    assert supabase_micro._codificar("MOVIL-001") == "MOVIL-001"
    assert supabase_micro._codificar("A B&ñ") == "A%20B%26%C3%B1"
