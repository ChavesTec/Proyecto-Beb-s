"""Fechas: se guardan en UTC y se muestran en America/Costa_Rica (RNF-26)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    ZONA_LOCAL = ZoneInfo("America/Costa_Rica")
except Exception:  # Sin base de zonas (Windows sin tzdata): Costa Rica no usa horario de verano.
    ZONA_LOCAL = timezone(timedelta(hours=-6), "UTC-6")


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def parsear_fecha_iso(valor: str | None) -> datetime | None:
    """Convierte un timestamptz de PostgREST en datetime con zona. None si no hay valor."""
    if not valor:
        return None
    texto = valor.strip().replace("Z", "+00:00")
    # PostgREST puede mandar 1 a 6 decimales; fromisoformat de 3.10 exige 3 o 6.
    if "." in texto:
        cabeza, _, resto = texto.partition(".")
        fin = next((i for i, c in enumerate(resto) if c in "+-"), len(resto))
        decimales, zona = resto[:fin], resto[fin:]
        texto = f"{cabeza}.{decimales[:6].ljust(6, '0')}{zona}"
    dt = datetime.fromisoformat(texto)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def a_local(dt: datetime | None) -> datetime | None:
    return dt.astimezone(ZONA_LOCAL) if dt else None


def formato_local(valor: str | datetime | None, con_segundos: bool = False, vacio: str = "—") -> str:
    """Texto dd/mm/aaaa hh:mm en hora de Costa Rica."""
    dt = parsear_fecha_iso(valor) if isinstance(valor, str) else valor
    if dt is None:
        return vacio
    return a_local(dt).strftime("%d/%m/%Y %H:%M:%S" if con_segundos else "%d/%m/%Y %H:%M")


def hace_cuanto(valor: str | datetime | None, ahora: datetime | None = None) -> str:
    dt = parsear_fecha_iso(valor) if isinstance(valor, str) else valor
    if dt is None:
        return "sin registro"
    segundos = int(((ahora or ahora_utc()) - dt).total_seconds())
    if segundos < 0:
        return "ahora"
    if segundos < 60:
        return f"hace {segundos} s"
    if segundos < 3600:
        return f"hace {segundos // 60} min"
    if segundos < 86400:
        return f"hace {segundos // 3600} h"
    return f"hace {segundos // 86400} d"


def parsear_fecha_local(texto: str) -> date:
    """Lee AAAA-MM-DD o DD/MM/AAAA. Lanza ValueError con mensaje en español."""
    texto = (texto or "").strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha no válida: {texto!r}. Use AAAA-MM-DD o DD/MM/AAAA.")


def rango_local_a_utc(desde: date | None, hasta: date | None) -> tuple[datetime | None, datetime | None]:
    """Días locales completos → [inicio, fin) en UTC. 'hasta' es inclusivo."""
    if desde and hasta and desde > hasta:
        raise ValueError("La fecha inicial no puede ser posterior a la final.")
    inicio = datetime.combine(desde, time.min, ZONA_LOCAL).astimezone(timezone.utc) if desde else None
    fin = (
        datetime.combine(hasta + timedelta(days=1), time.min, ZONA_LOCAL).astimezone(timezone.utc)
        if hasta
        else None
    )
    return inicio, fin
