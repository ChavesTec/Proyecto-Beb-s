"""Utilidades compartidas por los scripts de datos de prueba LOCALES.

⚠️ Solo para Supabase local (supabase start). Se niegan a correr contra otra URL.
Las contraseñas de las cuentas de prueba se generan al azar y se guardan en
pruebas/.credenciales_locales.json (fuera de Git), nunca en el código.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ARCHIVO_CREDENCIALES = RAIZ / "pruebas" / ".credenciales_locales.json"

CUENTA_ADMIN = "admin@ecosistema.test"
CONTROLADORES = {
    "controlador-a@ecosistema.test": ("CUNA-001", "SEGURIDAD-001"),   # Raspberry Pi
    "controlador-b@ecosistema.test": ("COLCHON-001",),                 # ESP32
    "controlador-c@ecosistema.test": ("MOVIL-001", "JUGUETE-001", "BIBERON-001"),  # ESP32
}


def claves_locales() -> tuple[str, str, str]:
    """URL, clave anon y clave service_role de Supabase local (no son secretas)."""
    salida = subprocess.run("npx -y supabase@3.0.0 status -o env", shell=True, capture_output=True,
                            text=True, cwd=RAIZ).stdout
    variables = dict(l.split("=", 1) for l in salida.splitlines() if "=" in l)
    try:
        url, anon, servicio = (variables[v].strip('"') for v in ("API_URL", "ANON_KEY", "SERVICE_ROLE_KEY"))
    except KeyError:
        sys.exit("No encontré Supabase local. Abra Docker Desktop y ejecute: npx -y supabase@3.0.0 start")
    if "127.0.0.1" not in url and "localhost" not in url:
        sys.exit("Estos scripts solo corren contra Supabase local.")
    return url, anon, servicio


def leer_credenciales() -> dict[str, str]:
    if not ARCHIVO_CREDENCIALES.exists():
        sys.exit("Primero ejecute: .venv\\Scripts\\python.exe pruebas\\preparar_base_local.py")
    return json.loads(ARCHIVO_CREDENCIALES.read_text(encoding="utf-8"))


def foto_jpeg(texto: str, color=(31, 95, 107)) -> bytes:
    """Foto de evidencia de prueba: JPEG 640x480 de menos de 150 KB (RNF-05)."""
    from PIL import Image, ImageDraw

    imagen = Image.new("RGB", (640, 480), color)
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle((40, 40, 600, 440), outline=(221, 242, 240), width=6)
    dibujo.text((70, 220), texto, fill=(255, 255, 255))
    salida = io.BytesIO()
    imagen.save(salida, "JPEG", quality=70)
    return salida.getvalue()
