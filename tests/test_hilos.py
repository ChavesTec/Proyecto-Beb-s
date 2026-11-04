"""La red nunca corre en el hilo de Tkinter; Realtime se degrada y se detiene sin fugas de hilos."""
import threading
import time

import pytest

from app.errores import ErrorApp, SesionExpirada
from tests.fakes import ErrorPostgrest


@pytest.fixture
def raiz():
    tk = pytest.importorskip("tkinter")
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("Sin pantalla para Tk")
    r.withdraw()
    yield r
    r.destroy()


def _esperar(raiz, condicion, segundos=5):
    fin = time.time() + segundos
    while not condicion() and time.time() < fin:
        raiz.update()
        time.sleep(0.01)


def test_resultado_llega_en_el_hilo_de_tk(raiz):
    from app.ui.tareas import Ejecutor

    ejecutor = Ejecutor(raiz)
    hilo_trabajo, hilo_respuesta = [], []
    ejecutor.ejecutar(lambda: hilo_trabajo.append(threading.current_thread()) or 42,
                      lambda r: hilo_respuesta.append((threading.current_thread(), r)))
    _esperar(raiz, lambda: hilo_respuesta)
    ejecutor.cerrar()
    assert hilo_trabajo[0] is not threading.main_thread()
    assert hilo_respuesta == [(threading.main_thread(), 42)]


def test_errores_se_traducen_y_la_sesion_expirada_va_al_manejador_global(raiz):
    from app.ui.tareas import Ejecutor

    ejecutor = Ejecutor(raiz)
    globales, locales = [], []
    ejecutor.al_error_global(lambda e: globales.append(e) or isinstance(e, SesionExpirada))

    def falla(error):
        raise error

    ejecutor.ejecutar(lambda: falla(ErrorPostgrest("PGRST301", "JWT expired")), al_fallar=locales.append)
    ejecutor.ejecutar(lambda: falla(ErrorPostgrest("42501", "No tienes permiso para eliminar este perfil")),
                      al_fallar=locales.append)
    _esperar(raiz, lambda: len(globales) == 2)
    ejecutor.cerrar()
    assert isinstance(globales[0], SesionExpirada) or isinstance(globales[1], SesionExpirada)
    assert len(locales) == 1 and isinstance(locales[0], ErrorApp) and "eliminar este perfil" in locales[0].mensaje


def test_realtime_sin_servidor_queda_degradado_y_se_detiene():
    from app.infrastructure.realtime import ServicioRealtime

    estados = []
    servicio = ServicioRealtime("http://127.0.0.1:59999", "anon", lambda *a: None, lambda e, d: estados.append(e))
    servicio.iniciar("token")
    fin = time.time() + 30
    while "degradado" not in estados and time.time() < fin:
        time.sleep(0.1)
    servicio.detener(espera_s=10)
    assert "degradado" in estados
    assert not any(h.name == "realtime" and h.is_alive() for h in threading.enumerate())
