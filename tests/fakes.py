"""Dobles de prueba del SDK de Supabase: registran las llamadas y devuelven datos fijos."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.infrastructure.supabase_client import Usuario


@dataclass
class Respuesta:
    data: Any
    count: int | None = None


class Consulta:
    def __init__(self, db: "BaseFalsa", objetivo: str, tipo: str = "table", params: dict | None = None):
        self.db = db
        self.objetivo = objetivo
        self.tipo = tipo
        self.params = params
        self.operaciones: list[tuple[str, tuple, dict]] = []
        db.consultas.append(self)

    def __getattr__(self, nombre):
        def registrar(*args, **kwargs):
            self.operaciones.append((nombre, args, kwargs))
            return self
        return registrar

    def nombres(self) -> list[str]:
        return [o[0] for o in self.operaciones]

    def argumentos(self, nombre: str) -> list[tuple]:
        return [o[1] for o in self.operaciones if o[0] == nombre]

    def execute(self):
        if self.db.error:
            raise self.db.error
        clave = f"{self.tipo}:{self.objetivo}"
        respuesta = self.db.respuestas.get(clave, Respuesta([]))
        if callable(respuesta):
            respuesta = respuesta(self)
        return respuesta


class BucketFalso:
    def __init__(self, db: "BaseFalsa", nombre: str):
        self.db = db
        self.nombre = nombre

    def create_signed_url(self, ruta: str, segundos: int):
        self.db.firmas.append((self.nombre, ruta, segundos))
        if self.db.error:
            raise self.db.error
        return self.db.respuesta_firma

    def get_public_url(self, ruta: str):  # pragma: no cover - la app nunca debe llamarla
        raise AssertionError("La app no debe pedir URLs públicas")


class StorageFalso:
    def __init__(self, db):
        self.db = db

    def from_(self, nombre):
        return BucketFalso(self.db, nombre)


@dataclass
class BaseFalsa:
    respuestas: dict[str, Any] = field(default_factory=dict)
    consultas: list[Consulta] = field(default_factory=list)
    firmas: list[tuple] = field(default_factory=list)
    error: Exception | None = None
    respuesta_firma: dict = field(default_factory=lambda: {"signedURL": "https://x/firmada?token=t",
                                                           "signedUrl": "https://x/firmada?token=t"})

    def table(self, nombre):
        return Consulta(self, nombre)

    def rpc(self, nombre, params=None):
        return Consulta(self, nombre, "rpc", params or {})

    @property
    def storage(self):
        return StorageFalso(self)


class ConexionFalsa:
    def __init__(self, db: BaseFalsa | None = None, usuario_id: str | None = "u-1"):
        self.db = db or BaseFalsa()
        self.usuario = Usuario(id=usuario_id, correo="ana@ecosistema.test") if usuario_id else None

    @property
    def cliente(self):
        if self.usuario is None:
            from app.errores import SesionExpirada

            raise SesionExpirada("No hay una sesión activa.")
        return self.db


class ErrorPostgrest(Exception):
    """Imita postgrest.exceptions.APIError (atributos code/message/details)."""

    def __init__(self, code: str, message: str, details: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class ErrorAuth(Exception):
    def __init__(self, message: str, status: int = 400, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
