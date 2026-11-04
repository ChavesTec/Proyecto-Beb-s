"""Clase base de las pantallas privadas."""
from __future__ import annotations

from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any, Callable

from app.errores import ErrorApp

if TYPE_CHECKING:  # pragma: no cover
    from app.ui.aplicacion import Aplicacion


class Pantalla(ttk.Frame):
    titulo = ""

    def __init__(self, padre, app: "Aplicacion"):
        super().__init__(padre, padding=(24, 18))
        self.app = app
        self.servicios = app.servicios

    # Ciclo de vida -------------------------------------------------------
    def al_mostrar(self, **parametros: Any) -> None:
        """Se llama cada vez que se navega a la pantalla."""

    def al_actualizar(self) -> None:
        """Cambió la instantánea (perfiles, dispositivos, configuración o alertas)."""

    def al_cambio(self, tabla: str, tipo: str, registro: dict) -> None:
        """Cambio Realtime puntual (por defecto, refresca)."""
        self.al_actualizar()

    def al_ocultar(self) -> None:
        """Se sale de la pantalla."""

    # Utilidades ----------------------------------------------------------
    def tarea(self, trabajo: Callable[[], Any], al_terminar: Callable[[Any], None] | None = None,
              al_fallar: Callable[[ErrorApp], None] | None = None, siempre: Callable[[], None] | None = None,
              boton: ttk.Button | None = None, exito: str | None = None) -> None:
        """Ejecuta en segundo plano; deshabilita el botón mientras tanto y avisa el resultado."""
        if boton is not None:
            texto = boton.cget("text")
            boton.configure(state="disabled", text="Procesando…")

        def restaurar():
            if boton is not None:
                try:
                    boton.configure(state="normal", text=texto)
                except Exception:
                    pass
            if siempre:
                siempre()

        def ok(resultado):
            if exito:
                self.app.notificar(exito, "exito")
            if al_terminar:
                al_terminar(resultado)

        def fallo(error: ErrorApp):
            if al_fallar:
                al_fallar(error)
            else:
                self.mostrar_error(error)

        self.app.ejecutor.ejecutar(trabajo, ok, fallo, restaurar)

    def mostrar_error(self, error: ErrorApp | str, titulo: str = "No se pudo completar") -> None:
        mensaje = error.mensaje if isinstance(error, ErrorApp) else str(error)
        tipo = error.tipo if isinstance(error, ErrorApp) else "error"
        if tipo == "sin_conexion":
            self.app.marcar_conexion(False)
        self.app.notificar(mensaje, "critico" if tipo in {"error", "sin_conexion"} else "aviso")
        if tipo in {"sin_permiso", "validacion", "no_encontrado"}:
            titulo = {"sin_permiso": "Sin permiso", "validacion": "Revise los datos",
                      "no_encontrado": "No encontrado"}[tipo]
        messagebox.showwarning(titulo, mensaje, parent=self)

    def confirmar(self, titulo: str, mensaje: str) -> bool:
        return messagebox.askyesno(titulo, mensaje, parent=self, icon="warning")

    @property
    def perfil_id(self) -> str | None:
        return self.app.perfil_seleccionado
