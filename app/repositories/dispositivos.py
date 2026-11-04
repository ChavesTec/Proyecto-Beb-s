"""dispositivos, configuracion, comandos, horarios y snapshots_peso (EP02-EP08)."""
from __future__ import annotations

from typing import Any

from app.repositories.base import Repositorio, ejecutar, exigir_filas, filas

COLUMNAS_DISPOSITIVO = ("id, codigo, tipo, nombre, propietario_id, perfil_id, en_linea, "
                        "ultima_senal_en, ultima_lectura, registrado_en, creado_en")

# Columnas que el usuario puede cambiar (GRANT de la migración 3).
COLUMNAS_CONFIG_EDITABLES = frozenset({
    "temp_min", "temp_max", "hum_min", "hum_max", "alerta_repeticion_min", "luz_intensidad",
    "peso_minimo_g", "alarma_caida_pct", "movil_encendido", "movil_secuencia", "movil_velocidad",
    "seguridad_armada", "seguridad_intervalo_foto_s", "juguete_tiempo_ronda_s", "juguete_volumen",
})

COLUMNAS_COMANDO = "id, dispositivo_id, tipo, parametros, estado, resultado, creado_por, creado_en, ejecutado_en"


class RepositorioDispositivos(Repositorio):
    # ------------------------------------------------------------ dispositivos
    def listar(self) -> list[dict]:
        """Lo que RLS deja ver: propios, de perfiles compartidos o de la credencial."""
        return filas(ejecutar(lambda: self.db.table("dispositivos")
                              .select(COLUMNAS_DISPOSITIVO).order("tipo").order("nombre").execute()))

    def obtener(self, dispositivo_id: str) -> dict | None:
        resultado = filas(ejecutar(lambda: self.db.table("dispositivos").select(COLUMNAS_DISPOSITIVO)
                                   .eq("id", dispositivo_id).limit(1).execute()))
        return resultado[0] if resultado else None

    def registrar(self, codigo: str, nombre: str | None) -> dict:
        respuesta = ejecutar(lambda: self.db.rpc("registrar_dispositivo",
                                                 {"p_codigo": codigo, "p_nombre": nombre}).execute())
        datos = respuesta.data
        return datos[0] if isinstance(datos, list) and datos else (datos or {})

    def asignar_perfil(self, dispositivo_id: str, perfil_id: str | None) -> dict:
        """Una sola columna perfil_id: nunca dos perfiles a la vez (CA-05.3)."""
        return exigir_filas(
            ejecutar(lambda: self.db.table("dispositivos").update({"perfil_id": perfil_id})
                     .eq("id", dispositivo_id).execute()),
            "No se reasignó: solo el propietario del dispositivo puede asignarlo a sus perfiles activos.")[0]

    def renombrar(self, dispositivo_id: str, nombre: str) -> dict:
        return exigir_filas(ejecutar(lambda: self.db.table("dispositivos").update({"nombre": nombre})
                                     .eq("id", dispositivo_id).execute()))[0]

    # ----------------------------------------------------------- configuracion
    def configuraciones(self) -> list[dict]:
        return filas(ejecutar(lambda: self.db.table("configuracion").select("*").execute()))

    def configuracion(self, dispositivo_id: str) -> dict | None:
        resultado = filas(ejecutar(lambda: self.db.table("configuracion").select("*")
                                   .eq("dispositivo_id", dispositivo_id).limit(1).execute()))
        return resultado[0] if resultado else None

    def actualizar_configuracion(self, dispositivo_id: str, cambios: dict[str, Any]) -> dict:
        invalidas = set(cambios) - COLUMNAS_CONFIG_EDITABLES
        if invalidas:
            raise ValueError(f"Columnas no editables: {sorted(invalidas)}")
        return exigir_filas(
            ejecutar(lambda: self.db.table("configuracion").update(cambios)
                     .eq("dispositivo_id", dispositivo_id).execute()),
            "No se guardó la configuración: no tiene permiso de control sobre este dispositivo.")[0]

    # ---------------------------------------------------------------- comandos
    def enviar_comando(self, dispositivo_id: str, tipo: str, parametros: dict | None = None) -> dict:
        datos = {"dispositivo_id": dispositivo_id, "tipo": tipo, "parametros": parametros or {}}
        return exigir_filas(ejecutar(lambda: self.db.table("comandos").insert(datos).execute()))[0]

    def comandos_recientes(self, dispositivo_id: str, limite: int = 10) -> list[dict]:
        return filas(ejecutar(lambda: self.db.table("comandos").select(COLUMNAS_COMANDO)
                              .eq("dispositivo_id", dispositivo_id)
                              .order("creado_en", desc=True).limit(limite).execute()))

    def comando(self, comando_id: int) -> dict | None:
        resultado = filas(ejecutar(lambda: self.db.table("comandos").select(COLUMNAS_COMANDO)
                                   .eq("id", comando_id).limit(1).execute()))
        return resultado[0] if resultado else None

    def desactivar_siesta(self, dispositivo_id: str) -> None:
        ejecutar(lambda: self.db.rpc("desactivar_siesta", {"p_dispositivo": dispositivo_id}).execute())

    # ---------------------------------------------------------------- horarios
    def horarios(self, dispositivo_id: str, tipo: str) -> list[dict]:
        return filas(ejecutar(lambda: self.db.table("horarios").select("*")
                              .eq("dispositivo_id", dispositivo_id).eq("tipo", tipo)
                              .order("hora_inicio").execute()))

    def crear_horario(self, datos: dict) -> dict:
        return exigir_filas(ejecutar(lambda: self.db.table("horarios").insert(datos).execute()))[0]

    def activar_horario(self, horario_id: str, activo: bool) -> dict:
        return exigir_filas(ejecutar(lambda: self.db.table("horarios").update({"activo": activo})
                                     .eq("id", horario_id).execute()))[0]

    def borrar_horario(self, horario_id: str) -> None:
        exigir_filas(ejecutar(lambda: self.db.table("horarios").delete().eq("id", horario_id).execute()))

    # ------------------------------------------------------------- colchón
    def snapshot_activo(self, dispositivo_id: str) -> dict | None:
        resultado = filas(ejecutar(lambda: self.db.table("snapshots_peso").select("*")
                                   .eq("dispositivo_id", dispositivo_id).is_("desactivado_en", "null")
                                   .limit(1).execute()))
        return resultado[0] if resultado else None

    def ultimo_snapshot(self, dispositivo_id: str) -> dict | None:
        resultado = filas(ejecutar(lambda: self.db.table("snapshots_peso").select("*")
                                   .eq("dispositivo_id", dispositivo_id)
                                   .order("creado_en", desc=True).limit(1).execute()))
        return resultado[0] if resultado else None
