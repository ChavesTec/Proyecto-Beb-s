"""usuarios, audios (Storage) y vinculación de Telegram."""
from __future__ import annotations

import re
import uuid

from app.repositories.base import Repositorio, ejecutar, exigir_filas, filas


class RepositorioCuenta(Repositorio):
    def mi_usuario(self) -> dict | None:
        resultado = filas(ejecutar(lambda: self.db.table("usuarios")
                                   .select("id, correo, nombre, rol, telegram_chat_id, telegram_vinculado_en")
                                   .eq("id", self.usuario_id).limit(1).execute()))
        return resultado[0] if resultado else None

    def cambiar_nombre(self, nombre: str) -> None:
        exigir_filas(ejecutar(lambda: self.db.table("usuarios").update({"nombre": nombre})
                              .eq("id", self.usuario_id).execute()))

    # ------------------------------------------------------------- Telegram
    def generar_codigo_telegram(self) -> dict:
        """RPC de la migración 20261104000000_telegram_envio.sql. Devuelve {codigo, expira_en}."""
        respuesta = ejecutar(lambda: self.db.rpc("generar_codigo_telegram", {}).execute())
        datos = respuesta.data
        if isinstance(datos, list):
            datos = datos[0] if datos else {}
        return datos or {}

    def desvincular_telegram(self) -> None:
        ejecutar(lambda: self.db.rpc("desvincular_telegram", {}).execute())

    # ---------------------------------------------------------------- audios
    def audios(self) -> list[dict]:
        return filas(ejecutar(lambda: self.db.table("audios")
                              .select("id, propietario_id, nombre, archivo_path, tamano_bytes, creado_en")
                              .eq("propietario_id", self.usuario_id).order("nombre").execute()))

    def subir_audio(self, nombre: str, nombre_archivo: str, contenido: bytes) -> dict:
        """Sube a audios/<propietario_id>/<archivo>.mp3 y registra la fila en `audios`."""
        base = re.sub(r"[^A-Za-z0-9_.-]+", "_", nombre_archivo.rsplit(".", 1)[0])[:60] or "audio"
        ruta = f"{self.usuario_id}/{base}-{uuid.uuid4().hex[:8]}.mp3"
        ejecutar(lambda: self.db.storage.from_("audios").upload(
            ruta, contenido, {"content-type": "audio/mpeg", "upsert": "false"}))
        try:
            return exigir_filas(ejecutar(lambda: self.db.table("audios").insert(
                {"nombre": nombre, "archivo_path": ruta, "tamano_bytes": len(contenido)}).execute()))[0]
        except Exception:
            # Sin fila no hay lista: se quita el archivo para no dejarlo huérfano.
            try:
                self.db.storage.from_("audios").remove([ruta])
            except Exception:
                pass
            raise

    def borrar_audio(self, audio: dict) -> None:
        exigir_filas(ejecutar(lambda: self.db.table("audios").delete().eq("id", audio["id"]).execute()))
        try:
            self.db.storage.from_("audios").remove([audio["archivo_path"]])
        except Exception:
            pass  # La fila ya no existe; el archivo huérfano no es visible para nadie más.
