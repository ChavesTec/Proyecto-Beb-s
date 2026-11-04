"""Fachada de servicios y estado compartido de la sesión.

Las pantallas no hablan con Supabase directamente: usan `Servicios`. Todos los
métodos son bloqueantes y deben correr en un hilo de trabajo (ver ui/tareas.py).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.config.valores import TIPOS_DISPOSITIVO
from app.config.zona import ahora_utc, parsear_fecha_iso
from app.infrastructure.supabase_client import ConexionSupabase
from app.repositories.alimentacion import RepositorioAlimentacion
from app.repositories.cuenta import RepositorioCuenta
from app.repositories.dispositivos import RepositorioDispositivos
from app.repositories.historial import RepositorioHistorial
from app.repositories.perfiles import RepositorioPerfiles
from app.services import dominio


@dataclass
class Instantanea:
    """Lo que necesitan el encabezado, el panel y los selectores."""
    perfiles: list[dict] = field(default_factory=list)          # visibles (no eliminados)
    todos_perfiles: list[dict] = field(default_factory=list)    # incluye eliminados (historial)
    accesos: dict[str, bool] = field(default_factory=dict)      # perfil_id -> puede_controlar
    dispositivos: list[dict] = field(default_factory=list)
    configuraciones: dict[str, dict] = field(default_factory=dict)
    alertas_24h: list[dict] = field(default_factory=list)
    lecturas_historial: dict[str, dict[str, dict]] = field(default_factory=dict)  # disp -> tipo -> evento
    usuario: dict | None = None
    cargada_en: datetime | None = None

    def nombre_perfil(self, perfil_id: str | None) -> str:
        if not perfil_id:
            return "Sin asignar"
        for p in self.todos_perfiles or self.perfiles:
            if p["id"] == perfil_id:
                return p["nombre"] + (" (eliminado)" if p.get("eliminado_en") else "")
        return "Perfil sin acceso"

    def dispositivo(self, dispositivo_id: str) -> dict | None:
        return next((d for d in self.dispositivos if d["id"] == dispositivo_id), None)


class Servicios:
    def __init__(self, conexion: ConexionSupabase):
        self.conexion = conexion
        self.perfiles = RepositorioPerfiles(conexion)
        self.dispositivos = RepositorioDispositivos(conexion)
        self.historial = RepositorioHistorial(conexion)
        self.cuenta = RepositorioCuenta(conexion)
        self.alimentacion = RepositorioAlimentacion(conexion)
        self._bloqueo = threading.Lock()
        self._instantanea = Instantanea()

    # ------------------------------------------------------------------ sesión
    @property
    def usuario_id(self) -> str:
        return self.conexion.usuario.id if self.conexion.usuario else ""

    @property
    def instantanea(self) -> Instantanea:
        with self._bloqueo:
            return self._instantanea

    def limpiar(self) -> None:
        with self._bloqueo:
            self._instantanea = Instantanea()

    # -------------------------------------------------------------- cargar todo
    def cargar_instantanea(self) -> Instantanea:
        perfiles = self.perfiles.listar_visibles()
        todos = self.perfiles.listar_todos()
        accesos = {a["perfil_id"]: bool(a["puede_controlar"]) for a in self.perfiles.mis_accesos()}
        dispositivos = self.dispositivos.listar()
        configs = {c["dispositivo_id"]: c for c in self.dispositivos.configuraciones()}
        alertas = self.historial.alertas_recientes(ahora_utc() - timedelta(hours=24))
        lecturas = self._ultimas_lecturas(dispositivos)
        usuario = self.cuenta.mi_usuario()
        nueva = Instantanea(perfiles=perfiles, todos_perfiles=todos, accesos=accesos,
                            dispositivos=dispositivos, configuraciones=configs, alertas_24h=alertas,
                            lecturas_historial=lecturas, usuario=usuario, cargada_en=ahora_utc())
        with self._bloqueo:
            self._instantanea = nueva
        return nueva

    def _ultimas_lecturas(self, dispositivos: list[dict]) -> dict[str, dict[str, dict]]:
        """Último evento de cada tipo de lectura por dispositivo (respaldo de ultima_lectura)."""
        tipos = ["temperatura", "humedad", "temperatura_biberon", "peso", "juguete_acierto",
                 "puerta", "presencia", "movimiento", "alarma_antirrobo"]
        ids = [d["id"] for d in dispositivos]
        resultado: dict[str, dict[str, dict]] = {}
        for evento in self.historial.ultimos_por_tipo(ids, tipos, limite=300):
            por_tipo = resultado.setdefault(evento["dispositivo_id"], {})
            por_tipo.setdefault(evento["tipo"], evento)
        return resultado

    # ------------------------------------------------ aplicar cambios Realtime
    def aplicar_cambio(self, tabla: str, tipo: str, registro: dict, anterior: dict) -> bool:
        """Mezcla un cambio Realtime en la instantánea. Devuelve True si cambió algo visible."""
        with self._bloqueo:
            inst = self._instantanea
            if tabla == "dispositivos":
                clave = registro.get("id") or anterior.get("id")
                inst.dispositivos = [d for d in inst.dispositivos if d["id"] != clave]
                if tipo != "DELETE" and registro:
                    inst.dispositivos.append(registro)
                    inst.dispositivos.sort(key=lambda d: (d.get("tipo") or "", d.get("nombre") or ""))
                return True
            if tabla == "configuracion":
                clave = registro.get("dispositivo_id") or anterior.get("dispositivo_id")
                if tipo == "DELETE":
                    inst.configuraciones.pop(clave, None)
                elif registro:
                    inst.configuraciones[clave] = registro
                return True
            if tabla == "alertas" and tipo == "INSERT" and registro:
                inst.alertas_24h.insert(0, registro)
                return True
            if tabla == "alertas" and tipo == "UPDATE" and registro:
                inst.alertas_24h = [registro if a["id"] == registro.get("id") else a for a in inst.alertas_24h]
                return True
        return tabla == "comandos"

    # ----------------------------------------------------------------- consultas
    def puede_controlar(self, dispositivo: dict) -> bool:
        return dominio.puede_controlar(dispositivo, self.usuario_id, self.instantanea.accesos)

    def puede_controlar_perfil(self, perfil_id: str | None) -> bool:
        return bool(perfil_id and self.instantanea.accesos.get(perfil_id))

    def es_propietario_perfil(self, perfil_id: str | None) -> bool:
        return any(p["id"] == perfil_id and p["propietario_id"] == self.usuario_id
                   for p in self.instantanea.perfiles)

    def resumen(self, perfil_id: str | None = None) -> dict[str, Any]:
        inst = self.instantanea
        dispositivos = dominio.filtrar_dispositivos(inst.dispositivos, perfil_id=perfil_id)
        conteo = {dominio.EN_LINEA: 0, dominio.FUERA_DE_LINEA: 0, dominio.SIN_DATOS: 0}
        ahora = ahora_utc()
        for d in dispositivos:
            conteo[dominio.estado_conexion(d, ahora)] += 1
        alertas = [a for a in inst.alertas_24h if not perfil_id or a.get("perfil_id") == perfil_id]
        return {
            "total": len(dispositivos), **conteo,
            "alertas_24h": len(alertas),
            "criticas_24h": sum(1 for a in alertas if a.get("severidad") == "critica"),
            "tipos_sin_dispositivo": [t for t in TIPOS_DISPOSITIVO
                                      if not any(d["tipo"] == t for d in dispositivos)],
        }

    def alertas_de(self, dispositivo_id: str, horas: int = 24) -> list[dict]:
        limite = ahora_utc() - timedelta(hours=horas)
        return [a for a in self.instantanea.alertas_24h
                if a.get("dispositivo_id") == dispositivo_id
                and (parsear_fecha_iso(a.get("creada_en")) or limite) >= limite]

    def alerta_fuera_de_linea_registrada(self, dispositivo: dict) -> bool:
        """¿La base ya registró la alerta fuera_de_linea tras la última señal? (no se duplica)."""
        senal = parsear_fecha_iso(dispositivo.get("ultima_senal_en"))
        for a in self.alertas_de(dispositivo["id"]):
            creada = parsear_fecha_iso(a.get("creada_en"))
            if a.get("tipo") == "fuera_de_linea" and (senal is None or (creada and creada >= senal)):
                return True
        return False
