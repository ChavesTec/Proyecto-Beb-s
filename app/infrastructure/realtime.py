"""Realtime en un hilo propio con su bucle asyncio.

supabase-py 2.x solo ofrece Realtime asíncrono. Este módulo:
  * abre un AsyncRealtimeClient con la clave pública y el JWT del usuario,
  * se suscribe a las tablas publicadas (dispositivos, configuracion, comandos, alertas),
  * entrega cada cambio a un callback (que debe ser seguro entre hilos: la UI usa una cola),
  * vigila la conexión y la rehace si se pierde, avisando el estado ('conectado',
    'reconectando', 'degradado', 'detenido').

RLS filtra en el servidor lo que cada usuario recibe; no se confía en filtros del cliente.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable

from realtime import AsyncRealtimeClient

log = logging.getLogger(__name__)

# Tablas incluidas en la publicación supabase_realtime (migración 4). eventos, capturas,
# tomas y snapshots_peso NO están publicadas: la UI las consulta con polling.
TABLAS_PUBLICADAS = ("dispositivos", "configuracion", "comandos", "alertas")

SEGUNDOS_VIGILANCIA = 5


class ServicioRealtime:
    def __init__(
        self,
        url_proyecto: str,
        clave_publica: str,
        al_cambio: Callable[[str, str, dict[str, Any], dict[str, Any]], None],
        al_estado: Callable[[str, str], None],
    ):
        self._url = f"{url_proyecto}/realtime/v1"
        self._clave = clave_publica
        self._al_cambio = al_cambio
        self._al_estado = al_estado
        self._token: str | None = None
        self._bucle: asyncio.AbstractEventLoop | None = None
        self._hilo: threading.Thread | None = None
        self._detener: asyncio.Event | None = None
        self._estado = "detenido"

    # ------------------------------------------------------------ API pública
    def iniciar(self, token: str) -> None:
        if self._hilo and self._hilo.is_alive():
            self.actualizar_token(token)
            return
        self._token = token
        self._hilo = threading.Thread(target=self._ejecutar, name="realtime", daemon=True)
        self._hilo.start()

    def actualizar_token(self, token: str | None) -> None:
        if token is None:
            self.detener()
            return
        self._token = token
        if self._bucle and self._cliente_actual:
            asyncio.run_coroutine_threadsafe(self._cliente_actual.set_auth(token), self._bucle)

    def detener(self, espera_s: float = 3.0) -> None:
        if self._bucle and self._detener:
            self._bucle.call_soon_threadsafe(self._detener.set)
        if self._hilo and self._hilo is not threading.current_thread():
            self._hilo.join(timeout=espera_s)
        self._hilo = None

    # ---------------------------------------------------------------- interno
    _cliente_actual: AsyncRealtimeClient | None = None

    def _notificar(self, estado: str, detalle: str = "") -> None:
        if estado != self._estado:
            self._estado = estado
            try:
                self._al_estado(estado, detalle)
            except Exception:
                log.exception("Callback de estado Realtime falló")

    def _ejecutar(self) -> None:
        self._bucle = asyncio.new_event_loop()
        asyncio.set_event_loop(self._bucle)
        try:
            self._bucle.run_until_complete(self._supervisar())
        except Exception:
            log.exception("Realtime terminó con error")
        finally:
            try:
                self._bucle.run_until_complete(self._bucle.shutdown_asyncgens())
            finally:
                self._bucle.close()
                self._bucle = None
                self._notificar("detenido")

    async def _supervisar(self) -> None:
        self._detener = asyncio.Event()
        intentos = 0
        while not self._detener.is_set():
            cliente = AsyncRealtimeClient(self._url, token=self._clave, auto_reconnect=True,
                                          max_retries=3, initial_backoff=1.0)
            self._cliente_actual = cliente
            estados: dict[str, str] = {}
            try:
                self._notificar("reconectando" if intentos else "conectando")
                await cliente.connect()
                await cliente.set_auth(self._token)
                canal = cliente.channel("app-escritorio")
                for tabla in TABLAS_PUBLICADAS:
                    canal.on_postgres_changes("*", schema="public", table=tabla,
                                              callback=self._crear_callback(tabla))

                def al_suscribir(estado, error, _estados=estados):
                    _estados["canal"] = getattr(estado, "value", str(estado))
                    if error:
                        log.warning("Realtime: %s", error)

                await canal.subscribe(al_suscribir)
                # Espera la confirmación de la suscripción.
                for _ in range(40):
                    if estados.get("canal") or self._detener.is_set():
                        break
                    await asyncio.sleep(0.25)
                if estados.get("canal") != "SUBSCRIBED":
                    raise ConnectionError(f"Suscripción no confirmada: {estados.get('canal')}")

                intentos = 0
                self._notificar("conectado")
                # Vigila la conexión hasta que se caiga o se pida detener.
                while not self._detener.is_set():
                    try:
                        await asyncio.wait_for(self._detener.wait(), timeout=SEGUNDOS_VIGILANCIA)
                    except asyncio.TimeoutError:
                        pass
                    if not cliente.is_connected or estados.get("canal") in {"CLOSED", "CHANNEL_ERROR", "TIMED_OUT"}:
                        raise ConnectionError("Conexión Realtime perdida")
            except asyncio.CancelledError:
                break
            except Exception as error:
                intentos += 1
                log.info("Realtime no disponible (%s); intento %s", type(error).__name__, intentos)
                self._notificar("degradado", "Actualización en vivo no disponible; se consulta periódicamente.")
                espera = min(5 * intentos, 60)
                try:
                    await asyncio.wait_for(self._detener.wait(), timeout=espera)
                except asyncio.TimeoutError:
                    pass
            finally:
                for cierre in (cliente.remove_all_channels, cliente.close):
                    try:
                        await asyncio.wait_for(cierre(), timeout=3)
                    except Exception:
                        pass
                self._cliente_actual = None

    def _crear_callback(self, tabla: str):
        def callback(payload: dict[str, Any]) -> None:
            datos = payload.get("data", {}) if isinstance(payload, dict) else {}
            tipo = str(datos.get("type", ""))
            tipo = getattr(datos.get("type"), "value", tipo)
            try:
                self._al_cambio(tabla, tipo, datos.get("record") or {}, datos.get("old_record") or {})
            except Exception:
                log.exception("Callback Realtime falló")
        return callback
