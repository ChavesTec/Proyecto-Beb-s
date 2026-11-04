"""Ejecuta trabajo de red fuera del hilo de Tkinter.

Regla: ningún hilo secundario toca widgets. Los resultados se ponen en una
queue.Queue y el hilo de Tkinter los procesa con root.after().
"""
from __future__ import annotations

import logging
import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from app.errores import ErrorApp, traducir_error

log = logging.getLogger(__name__)

INTERVALO_MS = 50


class Ejecutor:
    def __init__(self, raiz: tk.Misc, hilos: int = 4):
        self._raiz = raiz
        self._cola: queue.Queue[tuple[Callable[..., Any], tuple]] = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=hilos, thread_name_prefix="supabase")
        self._activo = True
        self._manejador_error_global: Callable[[ErrorApp], bool] | None = None
        self._raiz.after(INTERVALO_MS, self._procesar)

    def al_error_global(self, manejador: Callable[[ErrorApp], bool]) -> None:
        """Se llama primero con cada error; si devuelve True, el error ya se atendió (p. ej. sesión)."""
        self._manejador_error_global = manejador

    def ejecutar(self, trabajo: Callable[[], Any], al_terminar: Callable[[Any], None] | None = None,
                 al_fallar: Callable[[ErrorApp], None] | None = None,
                 siempre: Callable[[], None] | None = None) -> None:
        if not self._activo:
            return

        def envoltura():
            try:
                resultado = trabajo()
            except Exception as error:  # Se traduce aquí: la UI solo ve ErrorApp.
                traducido = error if isinstance(error, ErrorApp) else traducir_error(error)
                if not isinstance(error, ErrorApp):
                    log.debug("Error en tarea: %s", type(error).__name__)
                self.en_hilo_ui(self._entregar_error, traducido, al_fallar, siempre)
                return
            self.en_hilo_ui(self._entregar_ok, resultado, al_terminar, siempre)

        self._pool.submit(envoltura)

    def en_hilo_ui(self, funcion: Callable[..., Any], *args: Any) -> None:
        """Seguro desde cualquier hilo (Realtime, pool)."""
        if self._activo:
            self._cola.put((funcion, args))

    def _entregar_ok(self, resultado, al_terminar, siempre):
        try:
            if al_terminar:
                al_terminar(resultado)
        finally:
            if siempre:
                siempre()

    def _entregar_error(self, error: ErrorApp, al_fallar, siempre):
        try:
            if self._manejador_error_global and self._manejador_error_global(error):
                return
            if al_fallar:
                al_fallar(error)
        finally:
            if siempre:
                siempre()

    def _procesar(self) -> None:
        if not self._activo:
            return
        for _ in range(200):
            try:
                funcion, args = self._cola.get_nowait()
            except queue.Empty:
                break
            try:
                funcion(*args)
            except tk.TclError:
                pass  # El widget destino ya no existe (pantalla cerrada).
            except Exception:
                log.exception("Error procesando resultado en la UI")
        self._raiz.after(INTERVALO_MS, self._procesar)

    def cerrar(self) -> None:
        self._activo = False
        self._pool.shutdown(wait=False, cancel_futures=True)
