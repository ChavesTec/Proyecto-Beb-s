"""v_historial, v_galeria, alertas y Storage de capturas (EP06, EP09, EP10)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from postgrest.types import CountMethod

from app.config.valores import SEGUNDOS_URL_FIRMADA, TAMANO_PAGINA
from app.repositories.base import Repositorio, ejecutar, filas

COLUMNAS_HISTORIAL = "id, perfil_id, dispositivo_id, ocurrido_en, fecha_hora, perfil, dispositivo, tipo, valor, unidad, descripcion"
COLUMNAS_ALERTA = ("id, perfil_id, dispositivo_id, evento_id, tipo, severidad, mensaje, valor, umbral, "
                   "foto_path, estado, intentos, enviada_en, desactivada_por, desactivada_en, creada_en")


@dataclass
class FiltroHistorial:
    perfil_id: str | None = None
    dispositivo_id: str | None = None
    tipos: list[str] = field(default_factory=list)
    desde_utc: datetime | None = None
    hasta_utc: datetime | None = None  # exclusivo


@dataclass
class FiltroAlertas:
    perfil_id: str | None = None
    dispositivo_id: str | None = None
    tipo: str | None = None
    severidad: str | None = None
    estado: str | None = None
    desde_utc: datetime | None = None
    hasta_utc: datetime | None = None


@dataclass
class Pagina:
    filas: list[dict]
    total: int | None
    pagina: int
    tamano: int = TAMANO_PAGINA

    @property
    def paginas(self) -> int:
        if not self.total:
            return 1
        return max(1, -(-self.total // self.tamano))


def _aplicar_filtro_historial(consulta, f: FiltroHistorial):
    if f.perfil_id:
        consulta = consulta.eq("perfil_id", f.perfil_id)
    if f.dispositivo_id:
        consulta = consulta.eq("dispositivo_id", f.dispositivo_id)
    if f.tipos:
        consulta = consulta.in_("tipo", list(f.tipos))
    if f.desde_utc:
        consulta = consulta.gte("ocurrido_en", f.desde_utc.isoformat())
    if f.hasta_utc:
        consulta = consulta.lt("ocurrido_en", f.hasta_utc.isoformat())
    return consulta


class RepositorioHistorial(Repositorio):
    # -------------------------------------------------------------- historial
    def pagina_historial(self, filtro: FiltroHistorial, pagina: int, tamano: int = TAMANO_PAGINA) -> Pagina:
        """Más reciente primero; páginas de 50 (CA-39.1)."""
        inicio = pagina * tamano

        def consulta():
            q = self.db.table("v_historial").select(COLUMNAS_HISTORIAL, count=CountMethod.exact)
            q = _aplicar_filtro_historial(q, filtro)
            return q.order("ocurrido_en", desc=True).order("id", desc=True).range(inicio, inicio + tamano - 1).execute()

        respuesta = ejecutar(consulta)
        return Pagina(filas=filas(respuesta), total=getattr(respuesta, "count", None), pagina=pagina, tamano=tamano)

    def todo_historial(self, filtro: FiltroHistorial, lote: int = 1000, maximo: int = 200_000) -> list[dict]:
        """Todas las filas del filtro actual (para el CSV), en lotes."""
        resultado: list[dict] = []
        inicio = 0
        while inicio < maximo:
            def consulta(i=inicio):
                q = _aplicar_filtro_historial(self.db.table("v_historial").select(COLUMNAS_HISTORIAL), filtro)
                return q.order("ocurrido_en", desc=True).order("id", desc=True).range(i, i + lote - 1).execute()

            parte = filas(ejecutar(consulta))
            resultado.extend(parte)
            if len(parte) < lote:
                break
            inicio += lote
        return resultado

    def eventos_dispositivo(self, dispositivo_id: str, tipos: list[str] | None = None, limite: int = 20) -> list[dict]:
        def consulta():
            q = self.db.table("v_historial").select(COLUMNAS_HISTORIAL).eq("dispositivo_id", dispositivo_id)
            if tipos:
                q = q.in_("tipo", tipos)
            return q.order("ocurrido_en", desc=True).limit(limite).execute()
        return filas(ejecutar(consulta))

    def ultimos_por_tipo(self, dispositivo_ids: list[str], tipos: list[str], limite: int = 200) -> list[dict]:
        """Lecturas recientes para las tarjetas cuando ultima_lectura no trae el dato."""
        if not dispositivo_ids:
            return []
        return filas(ejecutar(lambda: self.db.table("v_historial").select(COLUMNAS_HISTORIAL)
                              .in_("dispositivo_id", dispositivo_ids).in_("tipo", tipos)
                              .order("ocurrido_en", desc=True).limit(limite).execute()))

    # ---------------------------------------------------------------- galería
    def galeria(self, perfil_id: str | None, dispositivo_id: str | None, desde_utc: datetime | None,
                hasta_utc: datetime | None, pagina: int = 0, tamano: int = 24) -> Pagina:
        inicio = pagina * tamano

        def consulta():
            q = self.db.table("v_galeria").select(
                "id, perfil_id, dispositivo_id, foto_path, tomada_en, fecha_hora, tipo_evento",
                count=CountMethod.exact)
            if perfil_id:
                q = q.eq("perfil_id", perfil_id)
            if dispositivo_id:
                q = q.eq("dispositivo_id", dispositivo_id)
            if desde_utc:
                q = q.gte("tomada_en", desde_utc.isoformat())
            if hasta_utc:
                q = q.lt("tomada_en", hasta_utc.isoformat())
            return q.order("tomada_en", desc=True).range(inicio, inicio + tamano - 1).execute()

        respuesta = ejecutar(consulta)
        return Pagina(filas=filas(respuesta), total=getattr(respuesta, "count", None), pagina=pagina, tamano=tamano)

    def url_firmada(self, bucket: str, ruta: str, segundos: int = SEGUNDOS_URL_FIRMADA) -> str:
        """El Storage es privado: solo URLs firmadas de corta duración (RNF-23)."""
        respuesta = ejecutar(lambda: self.db.storage.from_(bucket).create_signed_url(ruta, segundos))
        url = respuesta.get("signedURL") or respuesta.get("signedUrl")
        if not url:
            from app.errores import ErrorApp

            raise ErrorApp("El archivo no existe o no tiene acceso a él.", "no_encontrado")
        return url

    def descargar(self, bucket: str, ruta: str) -> bytes:
        return ejecutar(lambda: self.db.storage.from_(bucket).download(ruta))

    # ----------------------------------------------------------------- alertas
    def pagina_alertas(self, f: FiltroAlertas, pagina: int, tamano: int = TAMANO_PAGINA) -> Pagina:
        inicio = pagina * tamano

        def consulta():
            q = self.db.table("alertas").select(COLUMNAS_ALERTA, count=CountMethod.exact)
            if f.perfil_id:
                q = q.eq("perfil_id", f.perfil_id)
            if f.dispositivo_id:
                q = q.eq("dispositivo_id", f.dispositivo_id)
            if f.tipo:
                q = q.eq("tipo", f.tipo)
            if f.severidad:
                q = q.eq("severidad", f.severidad)
            if f.estado:
                q = q.eq("estado", f.estado)
            if f.desde_utc:
                q = q.gte("creada_en", f.desde_utc.isoformat())
            if f.hasta_utc:
                q = q.lt("creada_en", f.hasta_utc.isoformat())
            return q.order("creada_en", desc=True).order("id", desc=True).range(inicio, inicio + tamano - 1).execute()

        respuesta = ejecutar(consulta)
        return Pagina(filas=filas(respuesta), total=getattr(respuesta, "count", None), pagina=pagina, tamano=tamano)

    def alertas_recientes(self, desde_utc: datetime, limite: int = 200) -> list[dict]:
        return filas(ejecutar(lambda: self.db.table("alertas").select(COLUMNAS_ALERTA)
                              .gte("creada_en", desde_utc.isoformat())
                              .order("creada_en", desc=True).limit(limite).execute()))

    def alertas_dispositivo(self, dispositivo_id: str, limite: int = 10) -> list[dict]:
        return filas(ejecutar(lambda: self.db.table("alertas").select(COLUMNAS_ALERTA)
                              .eq("dispositivo_id", dispositivo_id)
                              .order("creada_en", desc=True).limit(limite).execute()))
