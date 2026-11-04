"""Cliente Supabase (sync) y sesión del usuario.

La sesión vive solo en memoria: no se guardan contraseñas ni tokens en disco.
Al cerrar la app hay que volver a iniciar sesión (decisión conservadora).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

import httpx
from supabase import Client, ClientOptions, create_client

from app.config.settings import Configuracion
from app.errores import ErrorApp, SesionExpirada, traducir_error_auth

log = logging.getLogger(__name__)

TIEMPO_ESPERA_S = 20


@dataclass(frozen=True)
class Usuario:
    id: str
    correo: str


class ConexionSupabase:
    """Envuelve el cliente oficial; un solo punto para Auth y para obtener el cliente."""

    def __init__(self, config: Configuracion):
        self.config = config
        self._cliente: Client = self._nuevo_cliente()
        self._usuario: Usuario | None = None
        self._bloqueo = threading.Lock()
        self._oyentes_token: list[Callable[[str | None], None]] = []
        self._cliente.auth.on_auth_state_change(self._al_cambiar_auth)

    def _nuevo_cliente(self) -> Client:
        opciones = ClientOptions(
            auto_refresh_token=True,
            persist_session=False,
            httpx_client=httpx.Client(timeout=TIEMPO_ESPERA_S),
        )
        return create_client(self.config.supabase_url, self.config.supabase_anon_key, options=opciones)

    # ------------------------------------------------------------------ estado
    @property
    def cliente(self) -> Client:
        if self._usuario is None:
            raise SesionExpirada("No hay una sesión activa.")
        return self._cliente

    @property
    def usuario(self) -> Usuario | None:
        return self._usuario

    def token_acceso(self) -> str | None:
        sesion = self._cliente.auth.get_session()
        return sesion.access_token if sesion else None

    def al_cambiar_token(self, oyente: Callable[[str | None], None]) -> None:
        """Realtime necesita el JWT vigente cada vez que se refresca."""
        self._oyentes_token.append(oyente)

    def _al_cambiar_auth(self, evento, sesion) -> None:
        token = sesion.access_token if sesion else None
        nombre = getattr(evento, "value", str(evento))
        if nombre == "SIGNED_OUT":
            token = None
        for oyente in list(self._oyentes_token):
            try:
                oyente(token)
            except Exception:  # Un oyente roto no debe tumbar la sesión.
                log.exception("Oyente de token falló")

    # -------------------------------------------------------------------- auth
    def iniciar_sesion(self, correo: str, clave: str) -> Usuario:
        try:
            respuesta = self._cliente.auth.sign_in_with_password({"email": correo, "password": clave})
        except Exception as error:
            raise traducir_error_auth(error, "login") from None
        if not respuesta.user or not respuesta.session:
            raise ErrorApp("Correo o contraseña incorrectos", "validacion")
        with self._bloqueo:
            self._usuario = Usuario(id=respuesta.user.id, correo=respuesta.user.email or correo)
        return self._usuario

    def registrar(self, correo: str, clave: str) -> tuple[Usuario | None, bool]:
        """Crea la cuenta. Devuelve (usuario, requiere_confirmacion).

        La fila en `usuarios` la crea el trigger usuarios_desde_auth: aquí no se toca.
        """
        try:
            respuesta = self._cliente.auth.sign_up({"email": correo, "password": clave})
        except Exception as error:
            raise traducir_error_auth(error, "registro") from None
        usuario = respuesta.user
        if usuario is None:
            raise ErrorApp("No se pudo crear la cuenta. Intente de nuevo más tarde.")
        # Con confirmación por correo activa, Supabase no revela si el correo existía:
        # devuelve un usuario sin identidades. Es seguro decirlo solo en ese caso.
        if usuario.identities is not None and len(usuario.identities) == 0:
            raise ErrorApp("El correo ya está registrado", "validacion")
        if respuesta.session is None:
            return None, True
        with self._bloqueo:
            self._usuario = Usuario(id=usuario.id, correo=usuario.email or correo)
        return self._usuario, False

    def cerrar_sesion(self) -> None:
        try:
            self._cliente.auth.sign_out()
        except Exception:  # Sin red igual se borra la sesión local.
            log.warning("No se pudo avisar a Supabase del cierre de sesión; se descarta localmente.")
        finally:
            with self._bloqueo:
                self._usuario = None
            # Cliente nuevo: ningún encabezado con el JWT anterior queda vivo.
            self._cliente = self._nuevo_cliente()
            self._cliente.auth.on_auth_state_change(self._al_cambiar_auth)
            for oyente in list(self._oyentes_token):
                try:
                    oyente(None)
                except Exception:
                    log.exception("Oyente de token falló")

    def probar_conexion(self) -> bool:
        """Consulta el endpoint de salud de Auth (no requiere sesión)."""
        try:
            r = httpx.get(f"{self.config.supabase_url}/auth/v1/health",
                          headers={"apikey": self.config.supabase_anon_key}, timeout=8)
            return r.status_code < 500
        except httpx.HTTPError:
            return False
