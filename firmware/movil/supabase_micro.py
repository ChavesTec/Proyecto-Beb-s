# ============================================================
# supabase_micro.py · Cliente mínimo de Supabase para MicroPython
#
# Solo lo que el contrato de dispositivos necesita (README_BASE_DATOS.md):
#   * Auth con la cuenta propia del controlador (email + contraseña) y refresco.
#   * select id, codigo from dispositivos            (al arrancar)
#   * rpc('registrar_senal', {p_dispositivo, p_lectura})   (cada 5 s)
#   * leer configuracion                             (al arrancar y en sondeo)
#   * leer y marcar comandos pendientes
# Usa la clave pública (anon). Nunca la clave service_role.
# Ningún método imprime tokens ni contraseñas.
# ============================================================

import json
import time

try:
    import urequests as requests   # MicroPython
except ImportError:                # CPython (pruebas)
    import requests


class ErrorSupabase(Exception):
    def __init__(self, estado, texto=""):
        super().__init__("HTTP %s %s" % (estado, texto[:200]))
        self.estado = estado


def _codificar(valor):
    """Codifica para la URL lo mínimo necesario (MicroPython no trae urllib)."""
    seguro = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~"
    salida = ""
    for c in str(valor):
        if c in seguro:
            salida += c
        else:
            for b in c.encode("utf-8"):
                salida += "%%%02X" % b
    return salida


class ClienteSupabase:
    def __init__(self, url, clave_publica, correo, clave, tiempo_s=10):
        self.url = url.rstrip("/")
        self.clave_publica = clave_publica
        self.correo = correo
        self._clave = clave
        self.tiempo_s = tiempo_s
        self.token = None
        self.refresco = None
        self.vence = 0

    # ---------------------------------------------------------------- HTTP
    def _pedir(self, metodo, ruta, cuerpo=None, autenticado=True, prefer=None):
        encabezados = {"apikey": self.clave_publica, "Content-Type": "application/json"}
        if autenticado:
            self._asegurar_sesion()
            encabezados["Authorization"] = "Bearer " + self.token
        if prefer:
            encabezados["Prefer"] = prefer
        datos = json.dumps(cuerpo) if cuerpo is not None else None
        try:
            r = requests.request(metodo, self.url + ruta, data=datos, headers=encabezados,
                                 timeout=self.tiempo_s)
        except TypeError:  # algunas versiones de urequests no aceptan timeout
            r = requests.request(metodo, self.url + ruta, data=datos, headers=encabezados)
        try:
            estado = r.status_code
            texto = r.text
        finally:
            r.close()
        if estado == 401 and autenticado:
            self.token = None   # JWT vencido o revocado: se reintenta una vez
        if estado >= 400:
            raise ErrorSupabase(estado, texto)
        return json.loads(texto) if texto else None

    # ---------------------------------------------------------------- Auth
    def _guardar_sesion(self, datos):
        self.token = datos["access_token"]
        self.refresco = datos.get("refresh_token")
        self.vence = time.time() + int(datos.get("expires_in", 3600)) - 60

    def iniciar_sesion(self):
        datos = self._pedir("POST", "/auth/v1/token?grant_type=password",
                            {"email": self.correo, "password": self._clave}, autenticado=False)
        self._guardar_sesion(datos)

    def _asegurar_sesion(self):
        if self.token and time.time() < self.vence:
            return
        if self.refresco:
            try:
                datos = self._pedir("POST", "/auth/v1/token?grant_type=refresh_token",
                                    {"refresh_token": self.refresco}, autenticado=False)
                self._guardar_sesion(datos)
                return
            except ErrorSupabase:
                self.refresco = None
        self.iniciar_sesion()

    def _con_reintento(self, funcion):
        try:
            return funcion()
        except ErrorSupabase as e:
            if e.estado != 401:
                raise
            return funcion()   # token renovado en _asegurar_sesion

    # ------------------------------------------------------------ contrato
    def id_dispositivo(self, codigo):
        filas = self._con_reintento(lambda: self._pedir(
            "GET", "/rest/v1/dispositivos?select=id,codigo&codigo=eq." + _codificar(codigo)))
        if not filas:
            raise ErrorSupabase(404, "El código %s no pertenece a esta credencial" % codigo)
        return filas[0]["id"]

    def leer_config(self, dispositivo_id):
        filas = self._con_reintento(lambda: self._pedir(
            "GET", "/rest/v1/configuracion?select=movil_encendido,movil_secuencia,movil_velocidad"
                   "&dispositivo_id=eq." + dispositivo_id))
        return filas[0] if filas else None

    def registrar_senal(self, dispositivo_id, lectura):
        self._con_reintento(lambda: self._pedir(
            "POST", "/rest/v1/rpc/registrar_senal", {"p_dispositivo": dispositivo_id, "p_lectura": lectura}))

    def comandos_pendientes(self, dispositivo_id):
        return self._con_reintento(lambda: self._pedir(
            "GET", "/rest/v1/comandos?select=id,tipo,parametros&estado=eq.pendiente"
                   "&dispositivo_id=eq." + dispositivo_id + "&order=creado_en.asc&limit=10")) or []

    def marcar_comando(self, comando_id, estado, resultado=None, ejecutado_en=None):
        cuerpo = {"estado": estado, "resultado": resultado}
        if ejecutado_en:
            cuerpo["ejecutado_en"] = ejecutado_en
        self._con_reintento(lambda: self._pedir(
            "PATCH", "/rest/v1/comandos?id=eq.%d" % comando_id, cuerpo, prefer="return=minimal"))
