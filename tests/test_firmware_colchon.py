"""Firmware del colchón (firmware/colchon) en CPython, con hardware y Supabase simulados.

Cada prueba indica el criterio de aceptación (CA) del SRS que cubre.
Ejecutar desde la raíz del repositorio:  python -m pytest tests/test_firmware_colchon.py -v
"""
import json
import sys
import types
from pathlib import Path

import pytest

CARPETA = Path(__file__).resolve().parents[1] / "firmware" / "colchon"


# ------------------------------------------------------------------ hardware falso
class _Pin:
    IN, OUT = 0, 1

    def __init__(self, numero, modo=None, value=None):
        self.numero, self._v = numero, 0
        self.hijos = []

    def value(self, v=None):
        if v is None:
            return self._v
        self._v = v
        for f in self.hijos:
            f(v)


class _PWM:
    def __init__(self, pin):
        self.duty = 0

    def freq(self, f):
        pass

    def duty_u16(self, v):
        self.duty = v


# Los firmwares de otras placas (p. ej. firmware/movil) tienen módulos con el MISMO nombre
# (supabase_micro) y su propio `machine` falso. Para no pisarnos, se importa el del colchón
# con sus stubs y luego se restaura lo que hubiera en sys.modules.
_NOMBRES = ["machine", "urequests", "supabase_micro", "nube", "colchon", "agente", "buzzer", "hx711"]
_previo = {n: sys.modules.pop(n, None) for n in _NOMBRES}
sys.modules["machine"] = types.SimpleNamespace(
    Pin=_Pin, PWM=_PWM, disable_irq=lambda: 0, enable_irq=lambda x: None)
sys.modules["urequests"] = types.SimpleNamespace(request=None)
sys.path.insert(0, str(CARPETA))
try:
    import agente as agente_mod  # noqa: E402
    import buzzer as buzzer_mod  # noqa: E402
    import colchon as colchon_mod  # noqa: E402
    import hx711 as hx711_mod  # noqa: E402
    import nube  # noqa: E402
    import supabase_micro  # noqa: E402
    from nube import ErrorSupabase  # noqa: E402
finally:
    sys.path.remove(str(CARPETA))
    for _n in _NOMBRES:
        sys.modules.pop(_n, None)
        if _previo[_n] is not None:
            sys.modules[_n] = _previo[_n]


class HXFalso:
    """Entrega gramos 1:1 (offset 0, factor 1). None = sin muestra / cable suelto."""

    def __init__(self):
        self.valor = 4000

    def leer_crudo(self):
        return self.valor


class BuzzerFalso:
    def __init__(self):
        self.sonando = False
        self.historial = []

    def fijar(self, e):
        self.sonando = bool(e)
        self.historial.append(bool(e))

    def apagar(self):
        self.fijar(False)


class Mundo:
    """Un colchón con reloj propio: avanza de 100 ms en 100 ms (10 muestras/s, como el HX711)."""

    def __init__(self, tmp, cuna=True):
        self.hx, self.bz, self.t = HXFalso(), BuzzerFalso(), 1000
        self.cuna = cuna
        self.archivo = str(tmp / "siesta.json")
        self.c = colchon_mod.Colchon(colchon_mod.Balanza(self.hx), self.bz, lambda: self.cuna,
                                     archivo=self.archivo, segundos_confirmacion=2)

    def correr(self, segundos, peso=None):
        if peso is not None:
            self.hx.valor = peso
        for _ in range(int(segundos * 10)):
            self.t += 100
            self.c.actualizar(self.t)


class BaseFalsa:
    """Imita lo que la base hace con el colchón (README_BASE_DATOS.md, "Modo siesta")."""

    def __init__(self):
        self.config = {"siesta_activa": False, "peso_minimo_g": 500, "alarma_caida_pct": 30}
        self.comandos, self.snapshots, self.eventos, self.senales = [], [], [], []
        self.caida_red = False

    def _red(self):
        if self.caida_red:
            raise OSError(-2)

    def iniciar_sesion(self):
        self._red()

    def id_dispositivo(self, codigo):
        self._red()
        return "uuid-colchon"

    def leer_config_colchon(self, did):
        self._red()
        return dict(self.config)

    def snapshot_activo(self, did):
        self._red()
        vivos = [s for s in self.snapshots if not s.get("desactivado")]
        return vivos[0]["peso_base_g"] if vivos else None

    def insertar_snapshot(self, did, peso):
        self._red()
        if peso < self.config["peso_minimo_g"]:
            raise ErrorSupabase(400, json.dumps({"code": "23514", "message": "No se detecta al bebé"}))
        if any(not s.get("desactivado") for s in self.snapshots):
            raise ErrorSupabase(409, json.dumps({"code": "23505", "message": "duplicado"}))
        self.snapshots.append({"peso_base_g": round(peso, 2)})
        self.config["siesta_activa"] = True          # lo hace el trigger de la base

    def insertar_evento(self, did, ev):
        self._red()
        clave = (ev.get("ocurrido_en"), ev["tipo"])
        if clave[0] and any((e.get("ocurrido_en"), e["tipo"]) == clave for e in self.eventos):
            return                                   # ignore-duplicates (RNF-17)
        self.eventos.append(dict(ev))

    def comandos_pendientes(self, did):
        self._red()
        return [c for c in self.comandos if c["estado"] == "pendiente"]

    def marcar_comando(self, cid, estado, resultado=None, ejecutado_en=None):
        self._red()
        for c in self.comandos:
            if c["id"] == cid:
                c.update(estado=estado, resultado=resultado)

    def registrar_senal(self, did, lectura):
        self._red()
        self.senales.append(lectura)

    # lo que haría la app
    def pedir(self, tipo):
        c = {"id": len(self.comandos) + 1, "tipo": tipo, "estado": "pendiente", "resultado": None}
        self.comandos.append(c)
        return c

    def desactivar_rpc(self):                        # rpc('desactivar_siesta')
        for s in self.snapshots:
            s["desactivado"] = True
        self.config["siesta_activa"] = False
        return self.pedir("desactivar_siesta")


@pytest.fixture
def m(tmp_path):
    return Mundo(tmp_path)


def montar(m, base=None):
    base = base or BaseFalsa()
    ag = agente_mod.Agente({"codigo_dispositivo": "COLCHON-001"}, m.c, cliente=base)
    return ag, base


def vuelta(m, ag):
    ag.vuelta(m.t)


def poner_bebe_y_siesta(m, ag, base, peso=4000):
    m.correr(3, peso)
    base.pedir("activar_siesta")
    vuelta(m, ag)


# ------------------------------------------------------------------ HX711 y buzzer
def _hx_con_bits(valor_24):
    """HX711 simulado: DT entrega los 24 bits (y luego 1) con cada pulso de SCK."""
    hx = hx711_mod.HX711(14, 15)
    bits = [(valor_24 >> (23 - i)) & 1 for i in range(24)]
    cola = list(bits)
    hx.dt._v = 0                                     # listo

    def al_subir(v):
        if v == 1 and cola:
            hx.dt._v = cola.pop(0)
        elif v == 1:
            hx.dt._v = 1
    hx.sck.hijos.append(al_subir)
    return hx


@pytest.mark.parametrize("crudo, esperado", [(0x000100, 256), (0xFFFFFF, -1), (0xFFFF00, -256)])
def test_hx711_lee_24_bits_con_signo(crudo, esperado):
    assert _hx_con_bits(crudo).leer_crudo() == esperado


@pytest.mark.parametrize("crudo", [0x7FFFFF, 0x800000])
def test_hx711_descarta_entrada_saturada_o_cable_suelto(crudo):
    assert _hx_con_bits(crudo).leer_crudo() is None


def test_hx711_sin_muestra_devuelve_none():
    hx = hx711_mod.HX711(14, 15)
    hx.dt._v = 1                                     # DT alto = aún no hay dato
    assert hx.leer_crudo() is None


def test_buzzer_activo_y_pasivo():
    a = buzzer_mod.Buzzer(16, "activo")
    a.fijar(True)
    assert a._pin.value() == 1
    a.apagar()
    assert a._pin.value() == 0
    p = buzzer_mod.Buzzer(16, "pasivo")
    p.fijar(True)
    assert p._pwm.duty > 0
    p.apagar()
    assert p._pwm.duty == 0


def test_balanza_convierte_a_gramos():
    hx = HXFalso()
    hx.valor = 150000
    assert colchon_mod.Balanza(hx, offset=50000, factor=25.0).tomar() == 4000


# ------------------------------------------------------------------ HU-15
def test_ca_15_1_activar_siesta_guarda_el_promedio_como_snapshot(m):
    ag, base = montar(m)
    m.correr(3, 4000)
    base.pedir("activar_siesta")
    vuelta(m, ag)
    assert base.snapshots[0]["peso_base_g"] == pytest.approx(4000, abs=1)
    assert m.c.siesta and m.c.base == pytest.approx(4000, abs=1)
    assert base.comandos[0]["estado"] == "ejecutado"
    assert "Snapshot" in base.comandos[0]["resultado"]


def test_ca_15_1_el_snapshot_promedia_y_no_toma_una_sola_muestra(m):
    ag, base = montar(m)
    m.correr(1, 3900)
    m.correr(1, 4100)                                # el bebé se mueve: el promedio queda en medio
    base.pedir("activar_siesta")
    vuelta(m, ag)
    assert 3950 < base.snapshots[0]["peso_base_g"] < 4050


def test_ca_15_2_peso_menor_al_minimo_no_activa_y_dice_no_se_detecta_al_bebe(m):
    ag, base = montar(m)
    m.correr(3, 300)
    base.pedir("activar_siesta")
    vuelta(m, ag)
    assert not m.c.siesta
    assert base.comandos[0]["estado"] == "fallido"
    assert base.comandos[0]["resultado"] == "No se detecta al bebé"


def test_activar_sin_sensor_falla_con_mensaje(m):
    ag, base = montar(m)
    m.hx.valor = None                                # nunca hubo muestra válida
    m.correr(1)
    base.pedir("activar_siesta")
    vuelta(m, ag)
    assert base.comandos[0]["estado"] == "fallido"
    assert "sensor" in base.comandos[0]["resultado"].lower()


def test_activar_dos_veces_la_segunda_falla(m):
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base)
    base.pedir("activar_siesta")
    vuelta(m, ag)
    assert base.comandos[1]["estado"] == "fallido"
    assert m.c.siesta


# ------------------------------------------------------------------ HU-16
def test_ca_16_1_caida_significativa_suena_buzzer_y_registra_evento_critico(m):
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base, 4000)
    m.correr(3, 2000)                                # -50 %: sacaron al bebé
    assert m.c.alarma
    assert True in m.bz.historial[-8:]               # el buzzer pitó
    vuelta(m, ag)
    alarmas = [e for e in base.eventos if e["tipo"] == "alarma_antirrobo"]
    assert len(alarmas) == 1 and alarmas[0]["valor"] == pytest.approx(2000, abs=5)
    assert alarmas[0]["unidad"] == "g"


def test_ca_16_1_la_alarma_sale_sin_esperar_a_la_red(m):
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base, 4000)
    base.caida_red = True                            # sin Wi-Fi
    m.correr(3, 2000)
    assert m.c.alarma and True in m.bz.historial[-8:]


def test_ca_16_2_caida_pequena_no_dispara(m):
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base, 4000)
    m.correr(30, 3000)                               # -25 % < 30 %: juguete que se mueve
    assert not m.c.alarma
    assert not any(e["tipo"] == "alarma_antirrobo" for e in base.eventos)


def test_ca_16_2_caida_breve_no_dispara(m):
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base, 4000)
    m.correr(1, 1500)                                # 1 s abajo (< 2 s de confirmación)
    m.correr(5, 4000)
    assert not m.c.alarma


def test_un_pico_de_ruido_aislado_no_dispara(m):
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base, 4000)
    m.hx.valor = 0
    m.t += 100
    m.c.actualizar(m.t)                              # una sola muestra en cero
    m.correr(3, 4000)
    assert not m.c.alarma


def test_ca_16_3_si_nadie_la_desactiva_el_buzzer_sigue_sonando(m):
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base, 4000)
    m.correr(3, 2000)
    m.correr(60, 4000)                               # incluso si el peso vuelve a subir
    assert m.c.alarma
    assert True in m.bz.historial[-10:]


@pytest.mark.parametrize("cuna", [True, False])
def test_ca_16_4_la_alarma_suena_igual_con_cuna_o_con_fuente_propia(tmp_path, cuna):
    mm = Mundo(tmp_path, cuna=cuna)
    ag, base = montar(mm)
    mm.correr(3, 4000)
    base.pedir("activar_siesta")
    vuelta(mm, ag)
    base.caida_red = True                            # cuna apagada: tampoco hay red
    mm.correr(3, 1000)
    assert mm.c.alarma and True in mm.bz.historial[-8:]


# ------------------------------------------------------------------ HU-17
def test_ca_17_el_colchon_manda_evento_y_no_inserta_la_alerta_por_su_cuenta(m):
    """Telegram lo hace el trigger de la base: el firmware solo inserta el evento (README_BASE_DATOS)."""
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base, 4000)
    m.correr(3, 2000)
    vuelta(m, ag)
    assert not hasattr(base, "alertas")
    assert [e["tipo"] for e in base.eventos].count("alarma_antirrobo") == 1


def test_evento_reenviado_tras_perder_la_red_no_se_duplica(m):
    ag, base = montar(m)
    m.c.hora_iso = lambda: "2026-11-26T20:00:00Z"
    poner_bebe_y_siesta(m, ag, base, 4000)
    m.correr(3, 2000)
    base.caida_red = True
    with pytest.raises(OSError):
        ag.enviar_eventos()                          # falla: el evento vuelve a la cola
    base.caida_red = False
    ag.enviar_eventos()
    ag.enviar_eventos()
    assert [e["tipo"] for e in base.eventos].count("alarma_antirrobo") == 1
    assert base.eventos[-1]["ocurrido_en"] == "2026-11-26T20:00:00Z"   # hora original conservada


# ------------------------------------------------------------------ HU-18
def test_ca_18_1_con_la_siesta_desactivada_retirar_al_bebe_no_dispara(m):
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base, 4000)
    base.desactivar_rpc()
    vuelta(m, ag)
    assert not m.c.siesta
    m.correr(10, 0)                                  # retiran al bebé
    assert not m.c.alarma and not m.bz.sonando


def test_ca_18_2_desactivar_con_la_alarma_sonando_apaga_el_buzzer(m):
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base, 4000)
    m.correr(3, 2000)
    assert m.c.alarma
    base.desactivar_rpc()                            # un usuario con permiso pulsa el botón
    vuelta(m, ag)
    m.correr(1, 2000)
    assert not m.c.alarma and not m.c.siesta and not m.bz.sonando
    assert base.comandos[-1]["estado"] == "ejecutado"


def test_comando_desactivar_perdido_se_cubre_con_la_configuracion(m):
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base, 4000)
    m.correr(3, 2000)
    base.config["siesta_activa"] = False             # la base ya la cerró; el comando no llegó
    vuelta(m, ag)
    assert not m.c.alarma and not m.bz.sonando


# ------------------------------------------------------------------ HU-19 / CA-14.2
@pytest.mark.parametrize("cuna", [True, False])
def test_ca_19_1_y_14_2_informa_si_esta_conectado_a_la_cuna(tmp_path, cuna):
    mm = Mundo(tmp_path, cuna=cuna)
    ag, base = montar(mm)
    mm.correr(3, 4000)
    vuelta(mm, ag)
    assert base.senales[-1]["conectado_cuna"] is cuna
    assert base.senales[-1]["peso"] == 4000


# ------------------------------------------------------------------ robustez
def test_reinicio_en_plena_siesta_sigue_vigilando(tmp_path):
    a = Mundo(tmp_path)
    ag, base = montar(a)
    poner_bebe_y_siesta(a, ag, base, 4000)
    b = Mundo(tmp_path)                              # la placa se reinicia: nuevo objeto, mismo archivo
    assert b.c.siesta and b.c.base == pytest.approx(4000, abs=1)
    b.correr(3, 1000)
    assert b.c.alarma


def test_reinicio_sin_archivo_recupera_la_siesta_desde_la_base(tmp_path):
    a = Mundo(tmp_path)
    ag, base = montar(a)
    poner_bebe_y_siesta(a, ag, base, 4000)
    (tmp_path / "siesta.json").unlink()
    b = Mundo(tmp_path)
    assert not b.c.siesta
    ag2, _ = montar(b, base)
    b.correr(3, 4000)
    vuelta(b, ag2)
    assert b.c.siesta and b.c.base == pytest.approx(4000, abs=1)


def test_sensor_desconectado_no_dispara_pero_avisa(m):
    ag, base = montar(m)
    poner_bebe_y_siesta(m, ag, base, 4000)
    m.hx.valor = None                                # cable suelto: el driver devuelve None
    m.correr(10)
    assert not m.c.alarma
    vuelta(m, ag)
    assert "aviso" in base.senales[-1] and "peso" not in base.senales[-1]


def test_comando_probar_buzzer_suena_un_segundo(m):
    ag, base = montar(m)
    m.correr(1, 4000)
    base.pedir("probar_buzzer")
    vuelta(m, ag)
    m.t += 100
    m.c.actualizar(m.t)
    assert m.bz.sonando
    m.correr(2, 4000)
    assert not m.bz.sonando
    assert base.comandos[0]["estado"] == "ejecutado"


def test_comando_desconocido_se_marca_fallido(m):
    ag, base = montar(m)
    base.pedir("probar_luz")
    vuelta(m, ag)
    assert base.comandos[0]["estado"] == "fallido"


def test_el_peso_se_registra_cada_minuto_y_la_senal_cada_5_s(m):
    ag, base = montar(m)
    m.correr(3, 4000)
    ag.vuelta(m.t)
    m.correr(5, 4000)
    ag.vuelta(m.t)
    assert len(base.senales) == 2
    m.correr(60, 4000)
    ag.vuelta(m.t)
    assert [e["tipo"] for e in base.eventos].count("peso") == 2


def test_cola_de_eventos_descarta_pesos_antes_que_alarmas(m):
    m.correr(2, 4000)
    m.c._encolar({"tipo": "alarma_antirrobo", "valor": 1})
    for _ in range(colchon_mod.MAX_EVENTOS + 10):
        m.c.encolar_muestra(m.t)
    tipos = [e["tipo"] for e in m.c._eventos]
    assert "alarma_antirrobo" in tipos and len(tipos) == colchon_mod.MAX_EVENTOS


def test_mensaje_de_error_de_la_base():
    e = supabase_micro.ErrorSupabase(400, '{"code":"23514","message":"No se detecta al bebé"}')
    assert nube.mensaje_error(e) == "No se detecta al bebé"


def test_la_configuracion_de_la_base_cambia_los_umbrales(m):
    ag, base = montar(m)
    base.config.update(alarma_caida_pct=10, peso_minimo_g=200)
    m.correr(3, 4000)
    vuelta(m, ag)
    assert m.c.caida_pct == 10 and m.c.peso_minimo_g == 200
    base.pedir("activar_siesta")
    vuelta(m, ag)
    m.correr(3, 3500)                                # -12,5 %: con 30 % no dispararía, con 10 % sí
    assert m.c.alarma
