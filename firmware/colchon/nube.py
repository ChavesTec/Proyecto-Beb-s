# ============================================================
# nube.py · Lo que el colchón agrega al cliente de Supabase del móvil
#
# Contrato (README_BASE_DATOS.md, "Modo siesta"):
#   * insert en snapshots_peso {dispositivo_id, peso_base_g}  -> la base valida:
#       - peso menor a configuracion.peso_minimo_g => error 23514 "No se detecta al bebé" (CA-15.2)
#       - sin perfil asignado / ya hay siesta activa => error
#   * insert en eventos (peso cada minuto, alarma_antirrobo al ocurrir). El trigger
#     crea la alerta; NO se inserta en `alertas` (saldrían dos mensajes).
#   * (dispositivo_id, ocurrido_en, tipo) es único: reenviar un evento no lo duplica (RNF-17).
# ============================================================

import json

from supabase_micro import ClienteSupabase, ErrorSupabase  # noqa: F401  (ErrorSupabase se reexporta)


def mensaje_error(error):
    """Saca el texto en español que mandó la base (campo `message` de PostgREST)."""
    try:
        return json.loads(error.texto).get("message") or str(error)
    except Exception:
        return str(error)


class ClienteColchon(ClienteSupabase):
    def leer_config_colchon(self, dispositivo_id):
        filas = self._con_reintento(lambda: self._pedir(
            "GET", "/rest/v1/configuracion?select=siesta_activa,peso_minimo_g,alarma_caida_pct"
                   "&dispositivo_id=eq." + dispositivo_id))
        return filas[0] if filas else None

    def snapshot_activo(self, dispositivo_id):
        """Peso base de la siesta en curso, o None."""
        filas = self._con_reintento(lambda: self._pedir(
            "GET", "/rest/v1/snapshots_peso?select=peso_base_g&desactivado_en=is.null"
                   "&limit=1&dispositivo_id=eq." + dispositivo_id))
        return float(filas[0]["peso_base_g"]) if filas else None

    def insertar_snapshot(self, dispositivo_id, peso_g):
        self._con_reintento(lambda: self._pedir(
            "POST", "/rest/v1/snapshots_peso",
            {"dispositivo_id": dispositivo_id, "peso_base_g": round(peso_g, 2)},
            prefer="return=minimal"))

    def insertar_evento(self, dispositivo_id, evento):
        cuerpo = dict(evento)
        cuerpo["dispositivo_id"] = dispositivo_id
        self._con_reintento(lambda: self._pedir(
            "POST", "/rest/v1/eventos?on_conflict=dispositivo_id,ocurrido_en,tipo", cuerpo,
            prefer="resolution=ignore-duplicates,return=minimal"))
