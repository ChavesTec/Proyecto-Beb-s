"""Punto de entrada: python -m app.main"""
from __future__ import annotations

import logging
import sys


def _configurar_registro() -> None:
    # Nivel INFO sin datos sensibles: nunca se registran contraseñas, JWT ni tokens.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for ruidoso in ("httpx", "httpcore", "hpack", "websockets", "realtime"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def main() -> int:
    if sys.version_info < (3, 10):
        print("Se requiere Python 3.10 o superior.", file=sys.stderr)
        return 1
    _configurar_registro()
    from app.ui.aplicacion import Aplicacion

    Aplicacion().ejecutar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
