# ============================================================
# agente.py · EP04 Colchón: conversación con Supabase (corre en el hilo de red)
#
#   * Lee `configuracion` cada vuelta: siesta_activa, peso_minimo_g, alarma_caida_pct.
#   * Atiende comandos: activar_siesta (HU-15), desactivar_siesta (HU-18),
#     probar_buzzer (HU-07). Cualquier otro se marca `fallido` con el motivo.
#   * Llama a registrar_senal cada 5 s con ultima_lectura (peso, conectado_cuna...).
#   * Inserta un evento `peso` cada minuto y envía los eventos pendientes
#     (alarma_antirrobo incluida). Si no hay red, quedan en cola y se envían después.
#
# La alarma NO pasa por aquí: suena en colchon.py aunque no haya Wi-Fi.
# ============================================================

import time

from colchon import ticks_diff
from nube import ClienteColchon, ErrorSupabase, mensaje_error

MS_SENAL = 5000
MS_MUESTRA = 60000


def ahora_iso():
    a = time.gmtime()
    if a[0] < 2024:          # reloj sin sincronizar: mejor no mandar una fecha falsa
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % a[:6]


def sincronizar_hora():
    try:
        import ntptime
        ntptime.settime()    # UTC
        return True
    except Exception:
        return False


class Agente:
    def __init__(self, cfg, colchon, cliente=None):
        self.cfg = cfg
        self.colchon = colchon
        self.cliente = cliente or ClienteColchon(cfg["supabase_url"], cfg["supabase_anon_key"],
                                                 cfg["correo_controlador"], cfg["clave_controlador"])
        self.dispositivo_id = None
        self.ultima_senal = None
        self.ultima_muestra = None
        self.activo = True

    # ------------------------------------------------------------ arranque
    def preparar(self):
        if sincronizar_hora():
            self.colchon.hora_iso = ahora_iso
        self.cliente.iniciar_sesion()
        self.dispositivo_id = self.cliente.id_dispositivo(self.cfg["codigo_dispositivo"])

    # ------------------------------------------------------------ configuración
    def aplicar_config(self):
        fila = self.cliente.leer_config_colchon(self.dispositivo_id)
        if not fila:
            return
        c = self.colchon
        c.peso_minimo_g = float(fila["peso_minimo_g"])
        c.caida_pct = float(fila["alarma_caida_pct"])
        if fila["siesta_activa"] and not c.siesta:
            base = self.cliente.snapshot_activo(self.dispositivo_id)   # p. ej. tras un reinicio
            if base is not None:
                c.activar(base)
        elif not fila["siesta_activa"] and c.siesta:
            c.desactivar()          # la base manda (también cubre un comando perdido)

    # ------------------------------------------------------------ comandos
    def atender_comandos(self, ahora):
        for cmd in self.cliente.comandos_pendientes(self.dispositivo_id):
            tipo = cmd["tipo"]
            if tipo == "activar_siesta":
                self._activar_siesta(cmd, ahora)
            elif tipo == "desactivar_siesta":
                self.colchon.desactivar()
                self._marcar(cmd, "ejecutado", "Siesta desactivada")
            elif tipo == "probar_buzzer":
                self.colchon.probar_buzzer(ahora)
                self._marcar(cmd, "ejecutado")
            else:
                self._marcar(cmd, "fallido", "El colchón no admite la orden %s" % tipo)

    def _marcar(self, cmd, estado, resultado=None):
        self.cliente.marcar_comando(cmd["id"], estado, resultado, ahora_iso())

    def _activar_siesta(self, cmd, ahora):
        if self.colchon.siesta:
            self._marcar(cmd, "fallido", "El modo siesta ya está activo")
            return
        peso = self.colchon.promedio(ahora)
        if peso is None:
            self._marcar(cmd, "fallido", "El sensor de peso no responde")
            return
        try:
            self.cliente.insertar_snapshot(self.dispositivo_id, peso)   # la base valida CA-15.2
        except ErrorSupabase as e:
            if 400 <= e.estado < 500:
                self._marcar(cmd, "fallido", mensaje_error(e))          # p. ej. "No se detecta al bebé"
                return
            raise                                                       # error de red: se reintenta
        self.colchon.activar(peso)
        self._marcar(cmd, "ejecutado", "Snapshot de %d g" % round(peso))

    # ------------------------------------------------------------ eventos
    def enviar_eventos(self):
        pendientes = self.colchon.sacar_eventos()
        for i, ev in enumerate(pendientes):
            try:
                self.cliente.insertar_evento(self.dispositivo_id, ev)
            except ErrorSupabase as e:
                if 400 <= e.estado < 500 and e.estado not in (401, 408, 429):
                    print("evento descartado:", e.estado)           # inválido: reintentar no sirve
                    continue
                self.colchon.devolver_eventos(pendientes[i:])
                raise
            except Exception:
                self.colchon.devolver_eventos(pendientes[i:])
                raise

    # ------------------------------------------------------------ ciclo
    def vuelta(self, ahora):
        if self.dispositivo_id is None:
            self.preparar()
        self.aplicar_config()
        self.atender_comandos(ahora)
        if self.ultima_muestra is None or ticks_diff(ahora, self.ultima_muestra) >= MS_MUESTRA:
            self.ultima_muestra = ahora
            self.colchon.encolar_muestra(ahora)
        self.enviar_eventos()
        if self.ultima_senal is None or ticks_diff(ahora, self.ultima_senal) >= MS_SENAL:
            self.ultima_senal = ahora
            self.cliente.registrar_senal(self.dispositivo_id, self.colchon.lectura(ahora))
