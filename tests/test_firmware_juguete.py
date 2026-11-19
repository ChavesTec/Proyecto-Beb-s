"""Firmware del juguete (firmware/juguete) en CPython, con el hardware y la red simulados.

Cubre HU-29 (CA-29.1), HU-30 (CA-30.1, 30.2, 30.3), HU-31 (CA-31.1) y el contrato
con la base (registrar_senal, eventos juguete_acierto, comandos de prueba).
Los módulos se cargan con nombres propios para no chocar con firmware/movil.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

CARPETA = Path(__file__).resolve().parents[1] / "firmware" / "juguete"


# ------------------------------------------------------------ dobles de hardware
class _PinFalso:
    IN, OUT, PULL_UP = 0, 1, 2

    def __init__(self, numero, modo=None, pull=None, value=None):
        self.numero = numero
        self._valor = 1 if value is None else value

    def value(self, v=None):
        if v is None:
            return self._valor
        self._valor = v


class _PWMFalso:
    def __init__(self, pin):
        self.frecuencia = 0
        self.duty = 0

    def freq(self, f):
        self.frecuencia = f

    def duty_u16(self, d):
        self.duty = d


def _cargar(nombre_archivo, nombre_modulo, modulos_temporales=None):
    """Carga un archivo del juguete con un nombre único y dependencias temporales."""
    anteriores = {}
    for clave, valor in (modulos_temporales or {}).items():
        anteriores[clave] = sys.modules.get(clave)
        sys.modules[clave] = valor
    try:
        spec = importlib.util.spec_from_file_location(nombre_modulo, CARPETA / nombre_archivo)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo
    finally:
        for clave, valor in anteriores.items():
            if valor is None:
                sys.modules.pop(clave, None)
            else:
                sys.modules[clave] = valor


MACHINE = types.SimpleNamespace(Pin=_PinFalso, PWM=_PWMFalso)
juego_mod = _cargar("juego.py", "juguete_juego")
salidas_mod = _cargar("salidas.py", "juguete_salidas", {"machine": MACHINE})
cliente_mod = _cargar("supabase_micro.py", "juguete_supabase_micro",
                      {"urequests": types.SimpleNamespace(request=None)})


class HardwareFalso:
    def __init__(self):
        self.led = None
        self.todos = False
        self.tonos = []
        self.sonando = False

    def mostrar_led(self, indice):
        self.led, self.todos = indice, False

    def todos_leds(self, encendidos):
        self.todos, self.led = encendidos, None

    def tono(self, frecuencia, volumen):
        self.tonos.append((frecuencia, volumen))
        self.sonando = True

    def silencio(self):
        self.sonando = False

    def apagar(self):
        self.mostrar_led(None)
        self.silencio()


class Reloj:
    def __init__(self):
        self.ms = 0

    def __call__(self):
        return self.ms

    def avanzar(self, ms):
        self.ms += ms


def azar_fijo(*valores):
    seq = list(valores)
    return lambda a, b: seq.pop(0) if seq else a


def nuevo_juego(*azar):
    hw, reloj = HardwareFalso(), Reloj()
    j = juego_mod.Juego(hw, reloj=reloj, azar=azar_fijo(*azar), reloj_epoch=lambda: 1793_000_000)
    return j, hw, reloj


def correr(j, reloj, ms, paso=5, pulsaciones=None):
    for _ in range(ms // paso):
        reloj.avanzar(paso)
        j.actualizar(pulsaciones or [])


def primera_ronda(j, reloj):
    correr(j, reloj, juego_mod.PAUSA_ENTRE_RONDAS_MS + 5)
    assert j.estado == "ronda"


# ------------------------------------------------------------------- HU-29 / HU-30
def test_ca_29_1_al_encender_se_ilumina_un_boton_al_azar():
    j, hw, reloj = nuevo_juego(3)
    assert hw.led is None                    # al arrancar, todo apagado
    primera_ronda(j, reloj)
    assert hw.led == 3 and j.objetivo == 3 and j.ronda == 1
    assert j.lectura()["boton_activo"] == 4  # la app numera 1..5


def test_ca_30_1_acierto_suena_recompensa_y_empieza_otra_ronda():
    j, hw, reloj = nuevo_juego(2, 0)
    primera_ronda(j, reloj)
    reloj.avanzar(1500)
    j.actualizar([2])
    assert j.estado == "recompensa" and hw.led is None and hw.sonando
    assert j.aciertos == 1
    correr(j, reloj, 1000)                    # la melodía dura ~630 ms
    assert j.estado == "ronda" and j.ronda == 2 and hw.led == 0
    assert [f for f, _ in hw.tonos] == [523, 659, 784, 1047]


def test_ca_30_2_boton_incorrecto_no_suena_y_el_led_sigue():
    j, hw, reloj = nuevo_juego(1)
    primera_ronda(j, reloj)
    j.actualizar([0, 4])
    assert j.estado == "ronda" and hw.led == 1 and not hw.tonos
    assert j.fallos == 2 and j.aciertos == 0


def test_ca_30_3_sin_acierto_empieza_otra_ronda():
    j, hw, reloj = nuevo_juego(4, 2)
    primera_ronda(j, reloj)
    correr(j, reloj, 10_000)                  # 10 s por defecto
    assert j.estado == "pausa" and hw.led is None and not hw.tonos
    correr(j, reloj, juego_mod.PAUSA_ENTRE_RONDAS_MS + 5)
    assert j.estado == "ronda" and j.ronda == 2 and hw.led == 2


def test_no_repite_el_mismo_boton_dos_rondas_seguidas():
    j, hw, reloj = nuevo_juego(3, 3, 2)       # el azar vuelve a dar 3: se corre 2 lugares
    primera_ronda(j, reloj)
    correr(j, reloj, 10_000 + juego_mod.PAUSA_ENTRE_RONDAS_MS + 10)
    assert j.objetivo == 0                    # (3 + 2) % 5


# --------------------------------------------------------------------------- HU-31
def test_ca_31_1_el_tiempo_nuevo_se_usa_desde_la_siguiente_ronda():
    j, hw, reloj = nuevo_juego(0, 1)
    primera_ronda(j, reloj)
    assert j.aplicar_config(15, 50) is True
    assert j.tiempo_ronda_s == 10             # la ronda en curso no cambia
    correr(j, reloj, 10_000 + juego_mod.PAUSA_ENTRE_RONDAS_MS + 10)
    assert j.ronda == 2 and j.tiempo_ronda_s == 15
    correr(j, reloj, 14_000)
    assert j.estado == "ronda"                # a los 14 s sigue la misma ronda
    correr(j, reloj, 1_005)
    assert j.estado == "pausa"


def test_volumen_se_aplica_al_sonido_y_cero_silencia():
    j, hw, reloj = nuevo_juego(0, 1, 2)
    j.aplicar_config(10, 80)
    primera_ronda(j, reloj)
    j.actualizar([0])
    assert hw.tonos[0] == (523, 80)
    correr(j, reloj, 1000)
    j.aplicar_config(10, 0)
    j.actualizar([j.objetivo])
    correr(j, reloj, 1000)
    assert len(hw.tonos) == 4                 # con volumen 0 no se agregó ningún tono


@pytest.mark.parametrize("tiempo, volumen, esperado", [
    (0, -5, (1, 0)), (9999, 500, (300, 100)), ("x", None, (10, 50)), ("12", "30", (12, 30)),
])
def test_config_invalida_se_acota(tiempo, volumen, esperado):
    j, _, _ = nuevo_juego()
    j.aplicar_config(tiempo, volumen)
    assert (j._tiempo_pendiente_s, j.volumen) == esperado


# ------------------------------------------------------------- aciertos y lectura
def test_aciertos_pendientes_y_reintento():
    j, hw, reloj = nuevo_juego(4)
    primera_ronda(j, reloj)
    reloj.avanzar(2340)
    j.actualizar([4])
    lista = j.tomar_aciertos()
    assert lista == [{"boton": 5, "reaccion_s": 2.3, "epoch": 1793_000_000}]
    assert j.tomar_aciertos() == []
    j.devolver_aciertos(lista)
    assert j.tomar_aciertos() == lista


def test_buffer_de_aciertos_tiene_tope():
    j, _, _ = nuevo_juego()
    j.devolver_aciertos([{"n": i} for i in range(80)])
    assert len(j.tomar_aciertos()) == juego_mod.MAXIMO_ACIERTOS_GUARDADOS


def test_lectura_sin_ronda_no_inventa_boton():
    j, _, _ = nuevo_juego()
    assert j.lectura()["boton_activo"] is None


def test_pruebas_de_la_app():
    j, hw, reloj = nuevo_juego(1, 2)
    primera_ronda(j, reloj)
    j.probar_luz(2000)
    assert hw.todos and j.lectura()["boton_activo"] is None
    correr(j, reloj, 2005)
    assert j.estado == "ronda" and hw.led == 2
    j.probar_buzzer()
    assert j.estado == "recompensa" and hw.tonos


# ------------------------------------------------------------------ hardware real
def test_antirrebote_y_flanco():
    hw = salidas_mod.HardwareJuguete([10, 11, 12, 13, 14], [16, 17, 18, 19, 20], 15)
    b = hw.botones[2]
    b.value(0)
    assert hw.leer_pulsaciones(0) == []       # recién cambió
    assert hw.leer_pulsaciones(20) == []      # aún rebotando
    assert hw.leer_pulsaciones(45) == [2]     # estable: una pulsación
    assert hw.leer_pulsaciones(500) == []     # mantenerlo no cuenta otra vez
    b.value(1)
    hw.leer_pulsaciones(510)
    hw.leer_pulsaciones(560)
    b.value(0)
    hw.leer_pulsaciones(600)
    assert hw.leer_pulsaciones(650) == [2]    # soltar y volver a presionar sí cuenta


def test_rebote_corto_no_cuenta():
    hw = salidas_mod.HardwareJuguete([10, 11, 12, 13, 14], [16, 17, 18, 19, 20], 15)
    b = hw.botones[0]
    b.value(0)
    hw.leer_pulsaciones(0)
    b.value(1)
    hw.leer_pulsaciones(10)
    assert hw.leer_pulsaciones(100) == []


def test_leds_y_buzzer():
    hw = salidas_mod.HardwareJuguete([10, 11, 12, 13, 14], [16, 17, 18, 19, 20], 15)
    hw.mostrar_led(3)
    assert [l.value() for l in hw.leds] == [0, 0, 0, 1, 0]
    hw.tono(523, 100)
    assert hw.buzzer.frecuencia == 523 and hw.buzzer.duty == salidas_mod.DUTY_MAXIMO
    hw.tono(523, 50)
    assert hw.buzzer.duty == salidas_mod.DUTY_MAXIMO // 4
    hw.tono(523, 0)
    assert hw.buzzer.duty == 0
    hw.apagar()
    assert [l.value() for l in hw.leds] == [0] * 5


def test_un_led_por_boton():
    with pytest.raises(ValueError):
        salidas_mod.HardwareJuguete([10, 11], [16], 15)


# ------------------------------------------------------------- cliente de Supabase
class _Respuesta:
    def __init__(self, estado=200, texto=""):
        self.status_code, self.text = estado, texto

    def close(self):
        pass


def _cliente_con(respuestas, llamadas):
    def request(metodo, url, data=None, headers=None, timeout=None):
        llamadas.append((metodo, url, json.loads(data) if data else None, headers))
        return respuestas.pop(0)
    cliente_mod.requests = types.SimpleNamespace(request=request)
    c = cliente_mod.ClienteSupabase("https://x.supabase.co", "pub", "c@x", "clave")
    c.token, c.vence = "tok", 10**12
    return c


def test_insertar_evento_sin_duplicados():
    llamadas = []
    c = _cliente_con([_Respuesta(201)], llamadas)
    c.insertar_evento("dev-1", "juguete_acierto", valor=2.3, unidad="s",
                      descripcion="Acierto en el botón 5", ocurrido_en="2026-11-09T20:00:00Z")
    metodo, url, cuerpo, encabezados = llamadas[0]
    assert metodo == "POST" and url.endswith("/rest/v1/eventos?on_conflict=dispositivo_id,ocurrido_en,tipo")
    assert encabezados["Prefer"] == "resolution=ignore-duplicates,return=minimal"
    assert cuerpo == {"dispositivo_id": "dev-1", "tipo": "juguete_acierto", "valor": 2.3, "unidad": "s",
                      "descripcion": "Acierto en el botón 5", "ocurrido_en": "2026-11-09T20:00:00Z"}


def test_insertar_evento_sin_hora_la_pone_la_base():
    llamadas = []
    c = _cliente_con([_Respuesta(201)], llamadas)
    c.insertar_evento("dev-1", "juguete_acierto", valor=1.0)
    assert "ocurrido_en" not in llamadas[0][2]


def test_leer_config_del_juguete_y_compatibilidad_con_el_movil():
    llamadas = []
    c = _cliente_con([_Respuesta(200, '[{"juguete_tiempo_ronda_s": 15, "juguete_volumen": 40}]'),
                      _Respuesta(200, '[{"movil_encendido": true}]')], llamadas)
    assert c.leer_config("dev-1", "juguete_tiempo_ronda_s,juguete_volumen") == {
        "juguete_tiempo_ronda_s": 15, "juguete_volumen": 40}
    assert "select=juguete_tiempo_ronda_s,juguete_volumen&dispositivo_id=eq.dev-1" in llamadas[0][1]
    c.leer_config("dev-1")                    # llamada del móvil, sin cambios
    assert "select=movil_encendido,movil_secuencia,movil_velocidad" in llamadas[1][1]


# ------------------------------------------------------------------ agente de red
class ClienteFalso:
    def __init__(self, falla_eventos=False):
        self.eventos, self.senales, self.marcados = [], [], []
        self.comandos = []
        self.falla_eventos = falla_eventos
        self.config = {"juguete_tiempo_ronda_s": 15, "juguete_volumen": 30}

    def leer_config(self, dispositivo_id, columnas):
        assert columnas == "juguete_tiempo_ronda_s,juguete_volumen"
        return self.config

    def comandos_pendientes(self, dispositivo_id):
        lista, self.comandos = self.comandos, []
        return lista

    def marcar_comando(self, cid, estado, resultado=None, ejecutado_en=None):
        self.marcados.append((cid, estado, resultado))

    def insertar_evento(self, dispositivo_id, tipo, **datos):
        if self.falla_eventos:
            raise OSError("sin red")
        self.eventos.append((tipo, datos))

    def registrar_senal(self, dispositivo_id, lectura):
        self.senales.append(lectura)


def _agente(cliente):
    main = _cargar("main.py", "juguete_main", {
        "network": types.SimpleNamespace(WLAN=None, STA_IF=0),
        "juego": juego_mod,
        "supabase_micro": types.SimpleNamespace(ClienteSupabase=lambda *a: cliente),
    })
    j, hw, reloj = nuevo_juego(2, 4)
    agente = main.Agente({"supabase_url": "u", "supabase_anon_key": "k", "correo_controlador": "c",
                          "clave_controlador": "p", "codigo_dispositivo": "JUGUETE-001"}, j)
    agente.dispositivo_id = "dev-1"
    return main, agente, j, reloj


def test_agente_aplica_config_envia_aciertos_y_senal():
    cliente = ClienteFalso()
    main, agente, j, reloj = _agente(cliente)
    agente.vuelta()
    assert j._tiempo_pendiente_s == 15 and j.volumen == 30
    assert cliente.senales[-1]["boton_activo"] is None
    primera_ronda(j, reloj)
    reloj.avanzar(1000)
    j.actualizar([2])
    agente.enviar_aciertos()
    tipo, datos = cliente.eventos[0]
    assert tipo == "juguete_acierto" and datos["valor"] == 1.0 and datos["unidad"] == "s"
    assert datos["descripcion"] == "Acierto en el botón 3"
    assert datos["ocurrido_en"] == main.iso_utc(1793_000_000)


def test_agente_sin_red_conserva_los_aciertos():
    cliente = ClienteFalso(falla_eventos=True)
    _, agente, j, reloj = _agente(cliente)
    primera_ronda(j, reloj)
    j.actualizar([2])
    with pytest.raises(OSError):
        agente.enviar_aciertos()
    assert len(j.tomar_aciertos()) == 1       # vuelve a la cola para el siguiente intento


def test_agente_comandos():
    cliente = ClienteFalso()
    _, agente, j, reloj = _agente(cliente)
    cliente.comandos = [{"id": 1, "tipo": "probar_luz"}, {"id": 2, "tipo": "probar_buzzer"},
                        {"id": 3, "tipo": "activar_siesta"}]
    agente.atender_comandos()
    assert [(c, e) for c, e, _ in cliente.marcados] == [(1, "ejecutado"), (2, "ejecutado"), (3, "fallido")]


def test_senal_inmediata_al_cambiar_la_ronda_pero_no_en_rafaga(monkeypatch):
    cliente = ClienteFalso()
    main, agente, j, reloj = _agente(cliente)
    reloj_red = Reloj()
    monkeypatch.setattr(main, "ticks_ms", reloj_red)
    agente.senal()
    assert len(cliente.senales) == 1
    primera_ronda(j, reloj)                   # cambia la versión
    agente.senal()
    assert len(cliente.senales) == 1          # menos de 1 s desde la anterior
    reloj_red.avanzar(1000)
    agente.senal()
    assert len(cliente.senales) == 2 and cliente.senales[-1]["boton_activo"] == 3
    reloj_red.avanzar(1000)
    agente.senal()
    assert len(cliente.senales) == 2          # sin cambios: espera los 5 s
    reloj_red.avanzar(4000)
    agente.senal()
    assert len(cliente.senales) == 3


def test_iso_utc_sin_reloj_no_inventa_fecha():
    main = _cargar("main.py", "juguete_main2", {
        "network": types.SimpleNamespace(), "juego": juego_mod,
        "supabase_micro": types.SimpleNamespace(ClienteSupabase=None)})
    assert main.iso_utc(0) is None
    assert main.iso_utc(1793_000_000).startswith("2026-")
