"""CSV (HU-40), fechas en Costa Rica (RNF-26) y estado compartido de la sesión."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.config.zona import formato_local, parsear_fecha_iso, parsear_fecha_local, rango_local_a_utc
from app.errores import ErrorValidacion
from app.services.contexto import Instantanea, Servicios
from app.services.exportacion import ENCABEZADOS_CSV, MENSAJE_SIN_DATOS, exportar_csv, generar_csv
from tests.fakes import ConexionFalsa

FILAS = [
    {"fecha_hora": "2026-11-04 12:00:00", "perfil": "Sofía", "dispositivo": "Cuna, cuarto", "tipo": "temperatura",
     "valor": 15.5, "unidad": "°C", "descripcion": 'Línea 1\nLínea "2"'},
    {"fecha_hora": "2026-11-04 11:59:00", "perfil": None, "dispositivo": "Colchón", "tipo": "peso",
     "valor": None, "unidad": None, "descripcion": None},
]


# 11. CSV ---------------------------------------------------------------------
def test_csv_columnas_y_orden_exactos():
    assert ENCABEZADOS_CSV == ("fecha y hora", "perfil", "dispositivo", "tipo", "valor", "unidad", "descripción")
    assert generar_csv([]).splitlines()[0] == "fecha y hora,perfil,dispositivo,tipo,valor,unidad,descripción"


def test_csv_utf8_con_bom_y_caracteres_especiales(tmp_path):
    destino = tmp_path / "h.csv"
    assert exportar_csv(FILAS, destino) == 2
    crudo = destino.read_bytes()
    assert crudo.startswith(b"\xef\xbb\xbf")
    texto = crudo.decode("utf-8-sig")
    assert '"Cuna, cuarto"' in texto and '"Línea 1\nLínea ""2"""' in texto and "Sofía" in texto and "°C" in texto
    import csv
    import io

    filas = list(csv.reader(io.StringIO(texto, newline="")))
    assert len(filas) == 3 and filas[1][6] == 'Línea 1\nLínea "2"' and filas[2][4] == ""


def test_csv_vacio_no_crea_archivo(tmp_path):
    destino = tmp_path / "vacio.csv"
    with pytest.raises(ErrorValidacion, match=MENSAJE_SIN_DATOS):
        exportar_csv([], destino)
    assert not destino.exists()


# Fechas (UTC ↔ UTC-6) -----------------------------------------------------------
def test_formato_local_costa_rica():
    assert formato_local("2026-11-04T18:30:00+00:00") == "04/11/2026 12:30"
    assert formato_local(None) == "—"


def test_rango_de_dias_locales_a_utc():
    desde, hasta = rango_local_a_utc(date(2026, 11, 1), date(2026, 11, 3))
    assert desde == datetime(2026, 11, 1, 6, tzinfo=timezone.utc)
    assert hasta == datetime(2026, 11, 4, 6, tzinfo=timezone.utc)  # 'hasta' incluido completo


def test_rango_invertido():
    with pytest.raises(ValueError):
        rango_local_a_utc(date(2026, 11, 3), date(2026, 11, 1))


def test_fechas_en_dos_formatos():
    assert parsear_fecha_local("2026-11-04") == parsear_fecha_local("04/11/2026")
    with pytest.raises(ValueError):
        parsear_fecha_local("mañana")


def test_parsear_iso_sin_zona_es_utc():
    assert parsear_fecha_iso("2026-11-04T18:00:00").tzinfo is not None


# Estado de la sesión ---------------------------------------------------------------
def _servicios_con(inst: Instantanea) -> Servicios:
    s = Servicios(ConexionFalsa())
    s._instantanea = inst
    return s


def test_realtime_mezcla_cambios_en_la_instantanea():
    s = _servicios_con(Instantanea(dispositivos=[{"id": "d1", "tipo": "cuna", "nombre": "A", "en_linea": False}]))
    s.aplicar_cambio("dispositivos", "UPDATE", {"id": "d1", "tipo": "cuna", "nombre": "A", "en_linea": True}, {})
    assert s.instantanea.dispositivo("d1")["en_linea"] is True
    s.aplicar_cambio("configuracion", "UPDATE", {"dispositivo_id": "d1", "temp_min": 19}, {})
    assert s.instantanea.configuraciones["d1"]["temp_min"] == 19
    s.aplicar_cambio("alertas", "INSERT", {"id": 7, "dispositivo_id": "d1", "severidad": "critica"}, {})
    assert s.instantanea.alertas_24h[0]["id"] == 7


def test_alerta_fuera_de_linea_ya_registrada_no_se_duplica():
    ahora = datetime.now(timezone.utc)
    senal = (ahora - timedelta(minutes=3)).isoformat()
    d = {"id": "d1", "ultima_senal_en": senal}
    s = _servicios_con(Instantanea(alertas_24h=[]))
    assert s.alerta_fuera_de_linea_registrada(d) is False
    s._instantanea.alertas_24h = [{"id": 1, "dispositivo_id": "d1", "tipo": "fuera_de_linea",
                                   "creada_en": (ahora - timedelta(minutes=1)).isoformat()}]
    assert s.alerta_fuera_de_linea_registrada(d) is True


def test_resumen_cuenta_estados_por_perfil():
    ahora = datetime.now(timezone.utc).isoformat()
    inst = Instantanea(dispositivos=[
        {"id": "a", "tipo": "cuna", "perfil_id": "p1", "en_linea": True, "ultima_senal_en": ahora},
        {"id": "b", "tipo": "colchon", "perfil_id": "p1", "en_linea": False, "ultima_senal_en": None},
        {"id": "c", "tipo": "movil", "perfil_id": "p2", "en_linea": True, "ultima_senal_en": ahora},
    ], alertas_24h=[{"perfil_id": "p1", "severidad": "critica"}, {"perfil_id": "p2", "severidad": "advertencia"}])
    r = _servicios_con(inst).resumen("p1")
    assert (r["total"], r["en_linea"], r["sin_datos"], r["alertas_24h"], r["criticas_24h"]) == (2, 1, 1, 1, 1)
    assert "seguridad" in r["tipos_sin_dispositivo"]


def test_nombre_de_perfil_eliminado_en_historial():
    inst = Instantanea(todos_perfiles=[{"id": "p1", "nombre": "Sofía", "eliminado_en": "2026-11-01T00:00:00Z"}])
    assert inst.nombre_perfil("p1") == "Sofía (eliminado)" and inst.nombre_perfil(None) == "Sin asignar"
