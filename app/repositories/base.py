"""Utilidades comunes de acceso a datos: ejecutar, traducir errores y verificar filas."""
from __future__ import annotations

from typing import Any, Callable, TypeVar

from app.errores import SinFilasAfectadas, traducir_error

T = TypeVar("T")


class Repositorio:
    """Base: recibe la ConexionSupabase y expone el cliente de la sesión actual."""

    def __init__(self, conexion):
        self._conexion = conexion

    @property
    def db(self):
        return self._conexion.cliente

    @property
    def usuario_id(self) -> str:
        usuario = self._conexion.usuario
        if usuario is None:
            from app.errores import SesionExpirada

            raise SesionExpirada("No hay una sesión activa.")
        return usuario.id


def ejecutar(consulta: Callable[[], T]) -> T:
    """Ejecuta una llamada al SDK y traduce cualquier error a ErrorApp."""
    try:
        return consulta()
    except Exception as error:  # Cada subcliente del SDK lanza su propia excepción.
        raise traducir_error(error) from None


def filas(respuesta: Any) -> list[dict[str, Any]]:
    datos = getattr(respuesta, "data", None)
    if datos is None:
        return []
    return datos if isinstance(datos, list) else [datos]


def exigir_filas(respuesta: Any, mensaje: str | None = None) -> list[dict[str, Any]]:
    """Un update/delete filtrado por RLS devuelve 0 filas sin error: se convierte en error."""
    resultado = filas(respuesta)
    if not resultado:
        raise SinFilasAfectadas(mensaje) if mensaje else SinFilasAfectadas()
    return resultado
