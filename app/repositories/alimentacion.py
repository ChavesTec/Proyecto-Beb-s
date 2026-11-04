"""tomas y recordatorios (EP08)."""
from __future__ import annotations

from datetime import datetime

from app.repositories.base import Repositorio, ejecutar, exigir_filas, filas

COLUMNAS_TOMA = "id, perfil_id, dispositivo_id, inicio, fin, duracion_s, cantidad_ml, creado_por"


class RepositorioAlimentacion(Repositorio):
    def tomas(self, perfil_id: str, limite: int = 30) -> list[dict]:
        return filas(ejecutar(lambda: self.db.table("tomas").select(COLUMNAS_TOMA)
                              .eq("perfil_id", perfil_id).order("inicio", desc=True).limit(limite).execute()))

    def toma_en_curso(self, perfil_id: str) -> dict | None:
        resultado = filas(ejecutar(lambda: self.db.table("tomas").select(COLUMNAS_TOMA)
                                   .eq("perfil_id", perfil_id).is_("fin", "null").limit(1).execute()))
        return resultado[0] if resultado else None

    def iniciar_toma(self, perfil_id: str, dispositivo_id: str | None) -> dict:
        """inicio lo pone la base (default now()) para no depender del reloj del PC."""
        datos = {"perfil_id": perfil_id}
        if dispositivo_id:
            datos["dispositivo_id"] = dispositivo_id
        return exigir_filas(ejecutar(lambda: self.db.table("tomas").insert(datos).execute()))[0]

    def finalizar_toma(self, toma_id: int, fin_utc: datetime) -> dict:
        return exigir_filas(
            ejecutar(lambda: self.db.table("tomas").update({"fin": fin_utc.isoformat()})
                     .eq("id", toma_id).is_("fin", "null").execute()),
            "No se detuvo la toma: ya estaba finalizada o no tiene permiso de control.")[0]

    def registrar_cantidad(self, toma_id: int, cantidad_ml: float) -> dict:
        return exigir_filas(
            ejecutar(lambda: self.db.table("tomas").update({"cantidad_ml": cantidad_ml})
                     .eq("id", toma_id).execute()),
            "No se guardó la cantidad: no tiene permiso de control sobre este perfil.")[0]

    # ------------------------------------------------------------ recordatorios
    def recordatorios(self, perfil_id: str) -> list[dict]:
        return filas(ejecutar(lambda: self.db.table("recordatorios").select("*")
                              .eq("perfil_id", perfil_id).order("creado_en").execute()))

    def crear_recordatorio(self, perfil_id: str, tipo: str, intervalo_min: int | None, hora: str | None) -> dict:
        datos = {"perfil_id": perfil_id, "tipo": tipo, "intervalo_min": intervalo_min, "hora": hora, "activo": True}
        return exigir_filas(ejecutar(lambda: self.db.table("recordatorios").insert(datos).execute()))[0]

    def activar_recordatorio(self, recordatorio_id: str, activo: bool) -> dict:
        return exigir_filas(ejecutar(lambda: self.db.table("recordatorios").update({"activo": activo})
                                     .eq("id", recordatorio_id).execute()))[0]

    def borrar_recordatorio(self, recordatorio_id: str) -> None:
        exigir_filas(ejecutar(lambda: self.db.table("recordatorios").delete()
                              .eq("id", recordatorio_id).execute()))
