"""Traducción de errores (credenciales, RLS, 23514, RPC faltante, red) y configuración."""
import base64
import json

import httpx
import pytest

from app.config.settings import ErrorConfiguracion, cargar_configuracion
from app.errores import (MENSAJE_CORREO_REGISTRADO, MENSAJE_CREDENCIALES, MENSAJE_SIN_CONEXION, SesionExpirada,
                         traducir_error, traducir_error_auth)
from tests.fakes import ErrorAuth, ErrorPostgrest


# 2. Credenciales incorrectas: un solo mensaje -------------------------------
@pytest.mark.parametrize("mensaje", ["Invalid login credentials", "User not found", "Email or password wrong"])
def test_login_siempre_mismo_mensaje(mensaje):
    assert traducir_error_auth(ErrorAuth(mensaje), "login").mensaje == MENSAJE_CREDENCIALES


def test_login_correo_no_confirmado():
    e = traducir_error_auth(ErrorAuth("Email not confirmed", code="email_not_confirmed"), "login")
    assert "confirmar" in e.mensaje


def test_registro_correo_ya_registrado():
    assert traducir_error_auth(ErrorAuth("User already registered"), "registro").mensaje == MENSAJE_CORREO_REGISTRADO


def test_auth_sin_red():
    e = traducir_error_auth(httpx.ConnectError("sin red"), "login")
    assert e.tipo == "sin_conexion" and e.mensaje == MENSAJE_SIN_CONEXION


# 3. Sesión expirada -----------------------------------------------------------
@pytest.mark.parametrize("codigo,mensaje", [("PGRST301", "JWT expired"), ("PGRST303", "x"), (None, "invalid JWT")])
def test_jwt_vencido_es_sesion_expirada(codigo, mensaje):
    assert isinstance(traducir_error(ErrorPostgrest(codigo, mensaje)), SesionExpirada)


# 7 y 13. Reglas check, RLS, RPC faltante -------------------------------------
def test_23514_rango_temperatura():
    e = traducir_error(ErrorPostgrest("23514", 'new row for relation "configuracion" violates check constraint '
                                               '"configuracion_rango_temperatura"'))
    assert e.tipo == "validacion" and "mínima debe ser menor" in e.mensaje


def test_23514_de_funcion_conserva_texto_en_espanol():
    assert traducir_error(ErrorPostgrest("23514", "No se detecta al bebé")).mensaje == "No se detecta al bebé"


def test_42501_de_funcion_y_de_rls():
    assert traducir_error(ErrorPostgrest("42501", "No tienes permiso de control sobre este dispositivo")).mensaje \
        == "No tienes permiso de control sobre este dispositivo"
    e = traducir_error(ErrorPostgrest("42501", 'new row violates row-level security policy for table "comandos"'))
    assert e.tipo == "sin_permiso" and "permiso" in e.mensaje


def test_registrar_dispositivo_errores():
    assert traducir_error(ErrorPostgrest("P0002", "El código de dispositivo no es válido")).mensaje \
        == "El código de dispositivo no es válido"
    assert traducir_error(ErrorPostgrest("23505", "Este dispositivo ya está vinculado a otra cuenta")).mensaje \
        == "Este dispositivo ya está vinculado a otra cuenta"


def test_horario_traslapado():
    assert "traslapa" in traducir_error(ErrorPostgrest("23P01", "El horario se traslapa con otro ya guardado")).mensaje


def test_rpc_faltante():
    e = traducir_error(ErrorPostgrest("PGRST202", "Could not find the function public.generar_codigo_telegram"))
    assert "no existe" in e.mensaje and "migraciones" in e.mensaje


def test_toma_en_curso_unica():
    e = traducir_error(ErrorPostgrest("23505", 'duplicate key value violates unique constraint "tomas_una_en_curso"'))
    assert "toma en curso" in e.mensaje


def test_red_caida():
    assert traducir_error(httpx.ReadTimeout("t")).tipo == "sin_conexion"


def test_error_desconocido_en_ingles_no_se_muestra_crudo():
    e = traducir_error(ErrorPostgrest("XX000", "internal server error with stack"))
    assert "inesperado" in e.mensaje


# Configuración ---------------------------------------------------------------
def _jwt(rol):
    cuerpo = base64.urlsafe_b64encode(json.dumps({"role": rol}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{cuerpo}.firma"


def test_config_faltante(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    with pytest.raises(ErrorConfiguracion, match="SUPABASE_URL"):
        cargar_configuracion(tmp_path / "no-existe.env")


def test_config_rechaza_service_role(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", _jwt("service_role"))
    with pytest.raises(ErrorConfiguracion, match="service_role"):
        cargar_configuracion(tmp_path / "no-existe.env")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "sb_secret_abc")
    with pytest.raises(ErrorConfiguracion):
        cargar_configuracion(tmp_path / "no-existe.env")


def test_config_exige_https_remoto(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", _jwt("anon"))
    with pytest.raises(ErrorConfiguracion, match="HTTPS"):
        cargar_configuracion(tmp_path / "no-existe.env")


def test_config_valida(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:44321/")
    monkeypatch.setenv("SUPABASE_ANON_KEY", _jwt("anon"))
    c = cargar_configuracion(tmp_path / "no-existe.env")
    assert c.supabase_url == "http://127.0.0.1:44321" and c.es_local
