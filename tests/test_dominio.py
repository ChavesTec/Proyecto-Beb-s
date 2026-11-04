"""Reglas puras: cuentas, conexión, rangos, comandos, horarios, MP3 y alimentación."""
from datetime import datetime, timedelta, timezone

import pytest

from app.errores import ErrorValidacion
from app.services import dominio

AHORA = datetime(2026, 11, 4, 18, 0, 0, tzinfo=timezone.utc)


# 1. Correo y contraseña ---------------------------------------------------
@pytest.mark.parametrize("correo", ["", "sin-arroba", "a@b", "a b@c.com"])
def test_correo_invalido(correo):
    with pytest.raises(ErrorValidacion):
        dominio.validar_correo(correo)


def test_correo_se_normaliza():
    assert dominio.validar_correo("  Ana@Ecosistema.TEST ") == "ana@ecosistema.test"


def test_clave_minimo_8():
    with pytest.raises(ErrorValidacion, match="8 caracteres"):
        dominio.validar_clave("1234567")
    assert dominio.validar_clave("12345678") == "12345678"


def test_clave_confirmacion_distinta():
    with pytest.raises(ErrorValidacion, match="no coinciden"):
        dominio.validar_clave("12345678", "12345679")


# 4. Filtrado y permisos -----------------------------------------------------
DISPOSITIVOS = [
    {"id": "d1", "tipo": "cuna", "perfil_id": "p1", "propietario_id": "u-1"},
    {"id": "d2", "tipo": "colchon", "perfil_id": "p2", "propietario_id": "u-1"},
    {"id": "d3", "tipo": "cuna", "perfil_id": None, "propietario_id": "u-1"},
    {"id": "d4", "tipo": "movil", "perfil_id": "p9", "propietario_id": "otro"},
]


def test_filtrar_por_perfil_y_tipo():
    assert [d["id"] for d in dominio.filtrar_dispositivos(DISPOSITIVOS, perfil_id="p1")] == ["d1"]
    assert [d["id"] for d in dominio.filtrar_dispositivos(DISPOSITIVOS, tipo="cuna")] == ["d1", "d3"]
    assert [d["id"] for d in dominio.filtrar_dispositivos(DISPOSITIVOS, sin_asignar=True)] == ["d3"]
    assert len(dominio.filtrar_dispositivos(DISPOSITIVOS)) == 4


def test_puede_controlar():
    accesos = {"p9": False, "p2": True}
    assert dominio.puede_controlar(DISPOSITIVOS[0], "u-1", {}) is True          # propietario
    assert dominio.puede_controlar(DISPOSITIVOS[3], "u-1", accesos) is False    # compartido sin control
    assert dominio.puede_controlar(DISPOSITIVOS[3], "u-1", {"p9": True}) is True
    assert dominio.puede_controlar({"propietario_id": "x", "perfil_id": None}, "u-1", {"p9": True}) is False


# 6. Conexión: 60 s sin señal ----------------------------------------------
def _disp(segundos, en_linea=True):
    return {"en_linea": en_linea, "ultima_senal_en": (AHORA - timedelta(seconds=segundos)).isoformat()}


def test_en_linea_dentro_del_umbral():
    assert dominio.estado_conexion(_disp(5), AHORA) == dominio.EN_LINEA
    assert dominio.estado_conexion(_disp(60), AHORA) == dominio.EN_LINEA


def test_fuera_de_linea_tras_60_s_aunque_pg_cron_no_lo_marque():
    assert dominio.estado_conexion(_disp(61), AHORA) == dominio.FUERA_DE_LINEA


def test_fuera_de_linea_si_la_base_ya_lo_marco():
    assert dominio.estado_conexion(_disp(10, en_linea=False), AHORA) == dominio.FUERA_DE_LINEA


def test_sin_senal_es_sin_datos_no_normal():
    assert dominio.estado_conexion({"en_linea": False, "ultima_senal_en": None}, AHORA) == dominio.SIN_DATOS


def test_fecha_con_decimales_variables_de_postgrest():
    d = {"en_linea": True, "ultima_senal_en": "2026-11-04T17:59:30.12345+00:00"}
    assert dominio.estado_conexion(d, AHORA) == dominio.EN_LINEA


def test_advertencia_colchon_en_siesta_fuera_de_linea():
    colchon = {"tipo": "colchon"}
    assert dominio.advertencia_critica_desconexion(colchon, {"siesta_activa": True}, dominio.FUERA_DE_LINEA)
    assert dominio.advertencia_critica_desconexion(colchon, {"siesta_activa": False}, dominio.FUERA_DE_LINEA) is None
    assert dominio.advertencia_critica_desconexion(colchon, {"siesta_activa": True}, dominio.EN_LINEA) is None
    seguridad = {"tipo": "seguridad"}
    assert dominio.advertencia_critica_desconexion(seguridad, {"seguridad_armada": True}, dominio.FUERA_DE_LINEA)


# 7. Rangos de temperatura y humedad ---------------------------------------
def test_rango_minimo_mayor_o_igual_se_rechaza():
    with pytest.raises(ErrorValidacion, match="menor que la máxima"):
        dominio.validar_rango("26", "26", "temperatura")
    with pytest.raises(ErrorValidacion):
        dominio.validar_rango("30", "20", "temperatura")


def test_rango_valido_y_coma_decimal():
    assert dominio.validar_rango("18", "26,5", "temperatura") == (18.0, 26.5)


@pytest.mark.parametrize("valor", ["", "abc", "nan", "inf"])
def test_rango_valores_no_numericos(valor):
    with pytest.raises(ErrorValidacion):
        dominio.validar_rango(valor, "30", "temperatura")


def test_humedad_entre_0_y_100():
    with pytest.raises(ErrorValidacion):
        dominio.validar_rango("-1", "60", "humedad", 0, 100)
    with pytest.raises(ErrorValidacion):
        dominio.validar_rango("40", "101", "humedad", 0, 100)


def test_enteros():
    assert dominio.validar_entero("10", "x", 1) == 10
    with pytest.raises(ErrorValidacion):
        dominio.validar_entero("2.5", "x")
    with pytest.raises(ErrorValidacion):
        dominio.validar_entero("0", "x", minimo=1)


def test_origen_del_valor():
    base = {"temp_min": 18}
    assert dominio.origen_valor({"temp_min": 18.0}, "temp_min", base) == "predeterminado"
    assert dominio.origen_valor({"temp_min": "20.00"}, "temp_min", base) == "personalizado"
    assert dominio.origen_valor(None, "temp_min", base) == "sin datos"


# 8. Comandos ---------------------------------------------------------------
def test_comando_pendiente_no_se_muestra_como_ejecutado():
    texto = dominio.describir_comando({"tipo": "probar_luz", "estado": "pendiente"})
    assert "Pendiente" in texto and "Ejecutado" not in texto


def test_comando_fallido_muestra_resultado_exacto():
    texto = dominio.describir_comando({"tipo": "activar_siesta", "estado": "fallido",
                                       "resultado": "No se detecta al bebé"})
    assert "Fallido" in texto and "No se detecta al bebé" in texto


def test_comando_ejecutado():
    assert "Ejecutado" in dominio.describir_comando({"tipo": "tomar_foto", "estado": "ejecutado"})


# Horarios ------------------------------------------------------------------
def test_horario_valido_normaliza():
    assert dominio.validar_horario([3, 1, 1], "7:05", "19:30") == ([1, 3], "07:05", "19:30")


def test_horario_sin_dias_o_horas_iguales():
    with pytest.raises(ErrorValidacion):
        dominio.validar_horario([], "07:00", "08:00")
    with pytest.raises(ErrorValidacion):
        dominio.validar_horario([1], "07:00", "07:00")
    with pytest.raises(ErrorValidacion):
        dominio.validar_horario([1], "25:00", "07:00")


def test_describir_horario_cruza_medianoche():
    texto = dominio.describir_horario({"dias": [5, 6], "hora_inicio": "22:00:00", "hora_fin": "06:00:00"})
    assert "cruza medianoche" in texto and "Vie" in texto


# MP3 y alimentación ---------------------------------------------------------
def test_mp3_formato_y_tamano():
    dominio.validar_mp3("nana.mp3", 1000, b"ID3\x03")
    with pytest.raises(ErrorValidacion, match="mp3"):
        dominio.validar_mp3("nana.wav", 1000)
    with pytest.raises(ErrorValidacion, match="5 MB"):
        dominio.validar_mp3("grande.mp3", 5 * 1024 * 1024 + 1)
    with pytest.raises(ErrorValidacion):
        dominio.validar_mp3("falso.mp3", 1000, b"RIFF")


@pytest.mark.parametrize("valor", ["", "  ", "-1", "abc"])
def test_cantidad_ml_rechaza_vacio_y_negativo(valor):
    with pytest.raises(ErrorValidacion):
        dominio.validar_cantidad_ml(valor)


def test_cantidad_ml_valida():
    assert dominio.validar_cantidad_ml("120,5") == 120.5
    assert dominio.validar_cantidad_ml("0") == 0


def test_formato_duracion():
    assert dominio.formato_duracion(3725) == "01:02:05"
    assert dominio.formato_duracion(None) == "—"


# Lecturas en vivo -------------------------------------------------------------
def test_colchon_conectado_o_independiente():
    assert dominio.conexion_colchon({"ultima_lectura": {"conectado_cuna": True}}) == "Conectado a la cuna"
    assert dominio.conexion_colchon({"ultima_lectura": {"conectado_cuna": False}}) == "Independiente"
    assert "Sin datos" in dominio.conexion_colchon({"ultima_lectura": None})


def test_lecturas_sin_datos_no_inventa_valores():
    assert dominio.lecturas_de({"ultima_lectura": None}) == []
    lecturas = dominio.lecturas_de({"tipo": "cuna", "ultima_lectura": {"temperatura": 21.5, "clave_rara": 3}})
    assert ("Temperatura", "21.5 °C") in [(l.etiqueta, l.valor) for l in lecturas]
    assert any(l.etiqueta == "Clave rara" for l in lecturas)


def test_perfil_valida_nombre_y_fecha():
    nombre, fecha = dominio.validar_perfil(" Sofía ", "2026-01-15")
    assert nombre == "Sofía" and fecha.isoformat() == "2026-01-15"
    with pytest.raises(ErrorValidacion):
        dominio.validar_perfil("", "2026-01-15")
    with pytest.raises(ErrorValidacion):
        dominio.validar_perfil("X", "15-01-2026x")
    with pytest.raises(ErrorValidacion, match="futuro"):
        dominio.validar_perfil("X", "2999-01-01")
