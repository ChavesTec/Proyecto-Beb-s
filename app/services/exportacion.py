"""Exportación CSV del historial (HU-40)."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Iterable

from app.errores import ErrorValidacion

# CA-40.1: columnas y orden exactos.
ENCABEZADOS_CSV = ("fecha y hora", "perfil", "dispositivo", "tipo", "valor", "unidad", "descripción")
_CAMPOS_VISTA = ("fecha_hora", "perfil", "dispositivo", "tipo", "valor", "unidad", "descripcion")

MENSAJE_SIN_DATOS = "No hay datos para exportar con los filtros actuales."


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float):
        return f"{valor:g}"
    return str(valor)


def generar_csv(filas: Iterable[dict]) -> str:
    """Texto CSV (sin BOM). fecha_hora ya viene en hora de Costa Rica desde v_historial."""
    salida = io.StringIO(newline="")
    escritor = csv.writer(salida, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    escritor.writerow(ENCABEZADOS_CSV)
    for fila in filas:
        escritor.writerow([_texto(fila.get(campo)) for campo in _CAMPOS_VISTA])
    return salida.getvalue()


def exportar_csv(filas: list[dict], destino: Path) -> int:
    """CA-40.2: con resultado vacío no crea archivo. UTF-8 con BOM para Excel."""
    if not filas:
        raise ErrorValidacion(MENSAJE_SIN_DATOS)
    contenido = generar_csv(filas)
    destino = Path(destino)
    temporal = destino.with_suffix(destino.suffix + ".tmp")
    temporal.write_text(contenido, encoding="utf-8-sig", newline="")
    temporal.replace(destino)
    return len(filas)
