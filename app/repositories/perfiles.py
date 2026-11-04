"""perfiles_bebe y acceso_perfil (EP01)."""
from __future__ import annotations

from datetime import date

from app.repositories.base import Repositorio, ejecutar, exigir_filas, filas

COLUMNAS_PERFIL = "id, propietario_id, nombre, fecha_nacimiento, creado_en, eliminado_en"


class RepositorioPerfiles(Repositorio):
    def listar_visibles(self) -> list[dict]:
        """Perfiles no eliminados que el usuario posee o le compartieron (RLS + CA-03.1)."""
        return filas(ejecutar(lambda: self.db.table("perfiles_bebe")
                              .select(COLUMNAS_PERFIL)
                              .is_("eliminado_en", "null")
                              .order("nombre").execute()))

    def listar_todos(self) -> list[dict]:
        """Incluye eliminados: el historial conserva su perfil (CA-03.2)."""
        return filas(ejecutar(lambda: self.db.table("perfiles_bebe")
                              .select(COLUMNAS_PERFIL).order("nombre").execute()))

    def mis_accesos(self) -> list[dict]:
        """Filas de acceso_perfil del usuario actual: perfil y si puede controlar."""
        return filas(ejecutar(lambda: self.db.table("acceso_perfil")
                              .select("perfil_id, puede_controlar")
                              .eq("usuario_id", self.usuario_id).execute()))

    def accesos_de_perfil(self, perfil_id: str) -> list[dict]:
        """Solo el propietario ve los accesos de otros (política acceso_ver)."""
        return filas(ejecutar(lambda: self.db.table("acceso_perfil")
                              .select("usuario_id, perfil_id, puede_controlar, creado_en")
                              .eq("perfil_id", perfil_id).execute()))

    def crear(self, nombre: str, fecha_nacimiento: date) -> dict:
        datos = {"propietario_id": self.usuario_id, "nombre": nombre,
                 "fecha_nacimiento": fecha_nacimiento.isoformat()}
        return exigir_filas(ejecutar(lambda: self.db.table("perfiles_bebe").insert(datos).execute()))[0]

    def editar(self, perfil_id: str, nombre: str, fecha_nacimiento: date) -> dict:
        datos = {"nombre": nombre, "fecha_nacimiento": fecha_nacimiento.isoformat()}
        return exigir_filas(
            ejecutar(lambda: self.db.table("perfiles_bebe").update(datos).eq("id", perfil_id).execute()),
            "No se guardó el perfil: solo el propietario puede editarlo.")[0]

    def eliminar(self, perfil_id: str) -> None:
        """RPC eliminar_perfil: borrado lógico, dispositivos sin asignar, historial intacto."""
        ejecutar(lambda: self.db.rpc("eliminar_perfil", {"p_perfil": perfil_id}).execute())

    def compartir(self, perfil_id: str, correo: str, puede_controlar: bool) -> None:
        ejecutar(lambda: self.db.rpc("compartir_perfil", {
            "p_perfil": perfil_id, "p_correo": correo, "p_puede_controlar": puede_controlar,
        }).execute())

    def cambiar_control(self, perfil_id: str, usuario_id: str, puede_controlar: bool) -> None:
        exigir_filas(ejecutar(lambda: self.db.table("acceso_perfil")
                              .update({"puede_controlar": puede_controlar})
                              .eq("perfil_id", perfil_id).eq("usuario_id", usuario_id).execute()))

    def quitar_acceso(self, perfil_id: str, usuario_id: str) -> None:
        exigir_filas(ejecutar(lambda: self.db.table("acceso_perfil").delete()
                              .eq("perfil_id", perfil_id).eq("usuario_id", usuario_id).execute()))
