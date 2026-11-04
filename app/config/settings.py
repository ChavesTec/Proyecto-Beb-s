"""Lectura y validación de la configuración local (.env).

La app solo usa la URL del proyecto y la clave pública (anon/publishable). La
seguridad depende de Supabase Auth y de las políticas RLS de la base.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]


class ErrorConfiguracion(Exception):
    """Falta o es inválida alguna variable de entorno."""


@dataclass(frozen=True)
class Configuracion:
    supabase_url: str
    supabase_anon_key: str
    telegram_bot_usuario: str | None = None

    @property
    def es_local(self) -> bool:
        host = urlparse(self.supabase_url).hostname or ""
        return host in {"127.0.0.1", "localhost", "::1"} or host.endswith(".localhost")


def _parece_service_role(clave: str) -> bool:
    """Detecta (sin verificar firma) si alguien puso la clave service_role por error."""
    if clave.startswith("sb_secret_"):
        return True
    partes = clave.split(".")
    if len(partes) != 3:
        return False
    import base64
    import json

    try:
        relleno = partes[1] + "=" * (-len(partes[1]) % 4)
        datos = json.loads(base64.urlsafe_b64decode(relleno))
    except (ValueError, json.JSONDecodeError):
        return False
    return datos.get("role") == "service_role"


def cargar_configuracion(archivo_env: Path | None = None) -> Configuracion:
    """Carga .env (si existe) y valida las variables obligatorias."""
    load_dotenv(archivo_env or RAIZ_PROYECTO / ".env", override=False)

    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    clave = (os.getenv("SUPABASE_ANON_KEY") or "").strip()
    bot = (os.getenv("TELEGRAM_BOT_USUARIO") or "").strip().lstrip("@") or None

    faltan = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_ANON_KEY", clave)) if not v]
    if faltan:
        raise ErrorConfiguracion(
            "Faltan variables de entorno: " + ", ".join(faltan) + ".\n\n"
            "Copie .env.example como .env en la raíz del proyecto y complete la URL y la "
            "clave pública (anon) de su proyecto Supabase (Dashboard → Project Settings → API)."
        )

    partes = urlparse(url)
    if partes.scheme not in {"http", "https"} or not partes.hostname:
        raise ErrorConfiguracion(f"SUPABASE_URL no es una URL válida: {url!r}")

    if _parece_service_role(clave):
        raise ErrorConfiguracion(
            "SUPABASE_ANON_KEY contiene una clave service_role o secreta. La aplicación de "
            "escritorio solo debe usar la clave pública anon/publishable. Retírela del .env."
        )

    config = Configuracion(supabase_url=url, supabase_anon_key=clave, telegram_bot_usuario=bot)
    if partes.scheme == "http" and not config.es_local:
        raise ErrorConfiguracion("Use HTTPS para un proyecto Supabase remoto (RNF-13).")
    return config
