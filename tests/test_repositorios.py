"""Repositorios con un cliente Supabase simulado: consultas exactas, RLS con 0 filas, paginación."""
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.errores import ErrorApp, SesionExpirada, SinFilasAfectadas
from app.repositories.dispositivos import RepositorioDispositivos
from app.repositories.historial import FiltroHistorial, RepositorioHistorial
from app.repositories.perfiles import RepositorioPerfiles
from tests.fakes import BaseFalsa, ConexionFalsa, ErrorPostgrest, Respuesta

RAIZ = Path(__file__).resolve().parents[1]


# 3. Sin sesión no hay consultas ------------------------------------------------
def test_sin_sesion_no_consulta():
    repo = RepositorioPerfiles(ConexionFalsa(usuario_id=None))
    with pytest.raises(SesionExpirada):
        repo.listar_visibles()


# 4. Perfiles visibles ----------------------------------------------------------
def test_perfiles_visibles_excluye_eliminados():
    db = BaseFalsa()
    RepositorioPerfiles(ConexionFalsa(db)).listar_visibles()
    q = db.consultas[0]
    assert q.objetivo == "perfiles_bebe" and ("eliminado_en", "null") in q.argumentos("is_")


def test_crear_perfil_usa_columnas_reales():
    db = BaseFalsa(respuestas={"table:perfiles_bebe": Respuesta([{"id": "p1"}])})
    RepositorioPerfiles(ConexionFalsa(db)).crear("Sofía", date(2026, 1, 15))
    (datos,) = db.consultas[0].argumentos("insert")[0]
    assert datos == {"propietario_id": "u-1", "nombre": "Sofía", "fecha_nacimiento": "2026-01-15"}


def test_eliminar_y_compartir_usan_rpc():
    db = BaseFalsa()
    repo = RepositorioPerfiles(ConexionFalsa(db))
    repo.eliminar("p1")
    repo.compartir("p1", "beto@x.com", False)
    assert [(q.tipo, q.objetivo, q.params) for q in db.consultas] == [
        ("rpc", "eliminar_perfil", {"p_perfil": "p1"}),
        ("rpc", "compartir_perfil", {"p_perfil": "p1", "p_correo": "beto@x.com", "p_puede_controlar": False}),
    ]


def test_editar_perfil_ajeno_devuelve_cero_filas():
    db = BaseFalsa(respuestas={"table:perfiles_bebe": Respuesta([])})
    with pytest.raises(SinFilasAfectadas):
        RepositorioPerfiles(ConexionFalsa(db)).editar("p1", "X", date(2026, 1, 1))


# 5. Reasignación sin tocar el historial ----------------------------------------
def test_reasignar_solo_actualiza_perfil_del_dispositivo():
    db = BaseFalsa(respuestas={"table:dispositivos": Respuesta([{"id": "d1", "perfil_id": "p2"}])})
    RepositorioDispositivos(ConexionFalsa(db)).asignar_perfil("d1", "p2")
    assert len(db.consultas) == 1
    q = db.consultas[0]
    assert q.objetivo == "dispositivos" and q.argumentos("update") == [({"perfil_id": "p2"},)]
    assert "delete" not in q.nombres()
    assert not any(c.objetivo in {"eventos", "alertas", "v_historial"} for c in db.consultas)


def test_reasignar_sin_permiso_rls():
    db = BaseFalsa(respuestas={"table:dispositivos": Respuesta([])})
    with pytest.raises(SinFilasAfectadas, match="propietario"):
        RepositorioDispositivos(ConexionFalsa(db)).asignar_perfil("d1", "p2")


def test_registrar_dispositivo_rpc():
    db = BaseFalsa(respuestas={"rpc:registrar_dispositivo": Respuesta({"id": "d1", "tipo": "cuna"})})
    d = RepositorioDispositivos(ConexionFalsa(db)).registrar("CUNA-001", "Cuna")
    assert d["tipo"] == "cuna" and db.consultas[0].params == {"p_codigo": "CUNA-001", "p_nombre": "Cuna"}


def test_error_de_registro_se_traduce():
    db = BaseFalsa(error=ErrorPostgrest("23505", "Este dispositivo ya está vinculado a otra cuenta"))
    with pytest.raises(ErrorApp, match="otra cuenta"):
        RepositorioDispositivos(ConexionFalsa(db)).registrar("X", None)


# 7. Configuración: columnas permitidas y 0 filas -------------------------------
def test_configuracion_rechaza_columnas_no_editables():
    with pytest.raises(ValueError):
        RepositorioDispositivos(ConexionFalsa()).actualizar_configuracion("d1", {"siesta_activa": True})


def test_configuracion_sin_permiso_de_control():
    db = BaseFalsa(respuestas={"table:configuracion": Respuesta([])})
    with pytest.raises(SinFilasAfectadas, match="permiso de control"):
        RepositorioDispositivos(ConexionFalsa(db)).actualizar_configuracion("d1", {"temp_min": 18, "temp_max": 26})


def test_desactivar_siesta_es_rpc_y_no_comando_directo():
    db = BaseFalsa()
    RepositorioDispositivos(ConexionFalsa(db)).desactivar_siesta("d1")
    assert (db.consultas[0].tipo, db.consultas[0].objetivo) == ("rpc", "desactivar_siesta")


def test_comando_se_inserta_pendiente():
    db = BaseFalsa(respuestas={"table:comandos": Respuesta([{"id": 1, "estado": "pendiente"}])})
    c = RepositorioDispositivos(ConexionFalsa(db)).enviar_comando("d1", "activar_siesta")
    (datos,) = db.consultas[0].argumentos("insert")[0]
    assert datos == {"dispositivo_id": "d1", "tipo": "activar_siesta", "parametros": {}}
    assert c["estado"] == "pendiente"  # La app no lo marca: lo hace el dispositivo.


# 10. Historial: paginación de 50, orden y filtros -------------------------------
def test_historial_paginas_de_50_mas_reciente_primero():
    db = BaseFalsa(respuestas={"table:v_historial": Respuesta([{"id": i} for i in range(50)], count=120)})
    repo = RepositorioHistorial(ConexionFalsa(db))
    pagina = repo.pagina_historial(FiltroHistorial(), 0)
    assert db.consultas[0].argumentos("range") == [(0, 49)]
    assert ("ocurrido_en",) in db.consultas[0].argumentos("order")
    assert any(o[0] == "order" and o[2].get("desc") for o in db.consultas[0].operaciones)
    assert pagina.paginas == 3
    repo.pagina_historial(FiltroHistorial(), 2)
    assert db.consultas[1].argumentos("range") == [(100, 149)]


def test_historial_filtros():
    db = BaseFalsa()
    desde = datetime(2026, 11, 1, 6, tzinfo=timezone.utc)
    hasta = datetime(2026, 11, 3, 6, tzinfo=timezone.utc)
    RepositorioHistorial(ConexionFalsa(db)).pagina_historial(
        FiltroHistorial("p1", "d1", ["temperatura"], desde, hasta), 0)
    q = db.consultas[0]
    assert ("perfil_id", "p1") in q.argumentos("eq") and ("dispositivo_id", "d1") in q.argumentos("eq")
    assert q.argumentos("in_") == [("tipo", ["temperatura"])]
    assert q.argumentos("gte") == [("ocurrido_en", desde.isoformat())]
    assert q.argumentos("lt") == [("ocurrido_en", hasta.isoformat())]


def test_todo_el_historial_en_lotes_para_csv():
    lotes = iter([Respuesta([{"id": i} for i in range(1000)]), Respuesta([{"id": 1}])])
    db = BaseFalsa(respuestas={"table:v_historial": lambda q: next(lotes)})
    filas = RepositorioHistorial(ConexionFalsa(db)).todo_historial(FiltroHistorial())
    assert len(filas) == 1001 and db.consultas[1].argumentos("range") == [(1000, 1999)]


# 12. Fotos: solo URLs firmadas del bucket privado --------------------------------
def test_url_firmada_corta_duracion():
    db = BaseFalsa()
    url = RepositorioHistorial(ConexionFalsa(db)).url_firmada("capturas", "d1/foto.jpg")
    assert url.startswith("https://") and db.firmas == [("capturas", "d1/foto.jpg", 120)]


def test_url_firmada_sin_acceso():
    db = BaseFalsa(respuesta_firma={"signedURL": None, "signedUrl": None})
    with pytest.raises(ErrorApp, match="no tiene acceso"):
        RepositorioHistorial(ConexionFalsa(db)).url_firmada("capturas", "d1/ajena.jpg")


def test_url_firmada_sin_sesion():
    with pytest.raises(SesionExpirada):
        RepositorioHistorial(ConexionFalsa(usuario_id=None)).url_firmada("capturas", "x.jpg")


def test_la_app_nunca_pide_urls_publicas():
    codigo = "\n".join(p.read_text(encoding="utf-8") for p in (RAIZ / "app").rglob("*.py"))
    assert "get_public_url" not in codigo


# 9. Sin alertas duplicadas: la app nunca inserta eventos ni alertas -------------------
def test_la_app_no_inserta_en_alertas_ni_eventos():
    import re

    codigo = "\n".join(p.read_text(encoding="utf-8") for p in (RAIZ / "app").rglob("*.py"))
    assert not re.search(r'table\("(alertas|eventos)"\)\s*\.\s*(insert|upsert)', codigo)
    assert not re.search(r'table\("(alertas|eventos)"\)\.(insert|upsert)', codigo.replace("\n", ""))


def test_no_hay_secretos_en_el_repositorio():
    sospechosos = ("service_role_key=", "TELEGRAM_BOT_TOKEN=", "sb_secret_")
    for ruta in [RAIZ / ".env.example", *(RAIZ / "app").rglob("*.py")]:
        texto = ruta.read_text(encoding="utf-8")
        for s in sospechosos:
            if s == "sb_secret_" and ruta.name == "settings.py":
                continue  # Solo se usa para detectar y rechazar esa clave.
            assert s not in texto, f"{s} en {ruta}"
