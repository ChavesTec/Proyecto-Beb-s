# ============================================================
# supabase_micro.py · Cliente mínimo de Supabase para MicroPython
#
# Solo lo que el contrato de dispositivos necesita (README_BASE_DATOS.md):
#   * Auth con la cuenta propia del controlador (email + contraseña) y refresco.
#   * select id, codigo from dispositivos            (al arrancar)
#   * rpc('registrar_senal', {p_dispositivo, p_lectura})   (cada 5 s)
#   * leer configuracion                             (al arrancar y en sondeo)
#   * leer y marcar comandos pendientes
#   * subir una foto a Storage e insertar eventos (aparato de seguridad)
# Lo usan el móvil (firmware/movil) y la seguridad (firmware/seguridad): se
# copia a la placa junto a su main.py.
# Usa la clave pública (anon). Nunca la clave service_role.
# Ningún método imprime tokens ni contraseñas.
# ============================================================

import json
import os
import socket
import time

try:
    import ssl
except ImportError:  # MicroPython sin TLS: solo sirve con una base local por HTTP
    ssl = None

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


def _destino(url):
    """'https://x.supabase.co' -> ('https', 'x.supabase.co', 443)."""
    esquema, _, resto = url.partition("://")
    anfitrion = resto.split("/", 1)[0]
    host, _, puerto = anfitrion.partition(":")
    return esquema, host, int(puerto) if puerto else (443 if esquema == "https" else 80)


def _ruta_base(url):
    """Ruta que venga después del host en la URL del proyecto (normalmente vacía)."""
    resto = url.partition("://")[2]
    return "/" + resto.split("/", 1)[1] if "/" in resto else ""


def _envolver_tls(s, host):
    # Igual que urequests: cifra pero no valida el certificado (ver README del firmware).
    if hasattr(ssl, "SSLContext"):
        contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if hasattr(contexto, "check_hostname"):
            contexto.check_hostname = False
        contexto.verify_mode = ssl.CERT_NONE
        return contexto.wrap_socket(s, server_hostname=host)
    return ssl.wrap_socket(s, server_hostname=host)


def _escribir(s, datos):
    """Escribe todo, aunque el socket acepte menos de una vez."""
    if hasattr(s, "sendall"):
        s.sendall(datos)
        return
    vista = memoryview(datos)
    while len(vista):
        n = s.write(vista)
        if n is None:          # socket sin espacio todavía (lwIP): reintentar
            continue
        vista = vista[n:]


def _leer_respuesta(s, maximo=2048):
    """Lee la respuesta hasta que el servidor cierre (Connection: close). Solo se
    necesitan el estado y el texto del error, así que se guardan `maximo` bytes."""
    leer = getattr(s, "read", None) or s.recv
    partes = bytearray()
    while True:
        dato = leer(512)
        if not dato:
            break
        if len(partes) < maximo:
            partes += dato[:maximo - len(partes)]
    return bytes(partes)


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
        """cuerpo se envía como JSON. Los archivos van por _enviar_archivo (en trozos)."""
        encabezados = {"apikey": self.clave_publica, "Content-Type": "application/json"}
        if autenticado:
            self._asegurar_sesion()
            encabezados["Authorization"] = "Bearer " + self.token
        if prefer:
            encabezados["Prefer"] = prefer
        # El JSON va como bytes UTF-8: urequests calcula Content-Length con len(), que en
        # un str cuenta caracteres y no bytes, y un texto con tildes («está», «cámara»)
        # llegaba cortado a PostgREST (PGRST102 "Empty or invalid json").
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
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

    def _enviar_archivo(self, ruta, archivo_local, tipo, trozo):
        """POST de un archivo sin cargarlo entero en RAM.

        urequests necesita el cuerpo completo en memoria y lo escribe de una vez:
        con la foto (~56 KB) la Pico W se quedaba sin memoria (OSError ENOMEM)
        y las peticiones siguientes también fallaban. Aquí el archivo se lee y
        se escribe en el socket de a `trozo` bytes con el mismo búfer."""
        self._asegurar_sesion()
        esquema, host, puerto = _destino(self.url)
        largo = os.stat(archivo_local)[6]
        cabecera = ("POST %s%s HTTP/1.1\r\nHost: %s\r\napikey: %s\r\nAuthorization: Bearer %s\r\n"
                    "Content-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n") % (
            _ruta_base(self.url), ruta, host, self.clave_publica, self.token, tipo, largo)
        info = socket.getaddrinfo(host, puerto, 0, socket.SOCK_STREAM)[0]
        s = socket.socket(info[0], info[1], info[2])
        try:
            s.settimeout(self.tiempo_s)
            s.connect(info[-1])
            if esquema == "https":
                s = _envolver_tls(s, host)
            _escribir(s, cabecera.encode("utf-8"))
            bufer = bytearray(trozo)
            vista = memoryview(bufer)
            with open(archivo_local, "rb") as f:
                while True:
                    n = f.readinto(bufer)
                    if not n:
                        break
                    _escribir(s, vista[:n])
            respuesta = _leer_respuesta(s)
        finally:
            s.close()
        try:
            estado = int(respuesta.split(b" ", 2)[1])
        except (IndexError, ValueError):
            raise ErrorSupabase(0, "Respuesta HTTP inválida")
        texto = respuesta.partition(b"\r\n\r\n")[2].decode("utf-8", "ignore")
        if estado == 401:
            self.token = None   # se reintenta una vez con _con_reintento
        if estado >= 400:
            raise ErrorSupabase(estado, texto)

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

    def leer_config(self, dispositivo_id, columnas="movil_encendido,movil_secuencia,movil_velocidad"):
        filas = self._con_reintento(lambda: self._pedir(
            "GET", "/rest/v1/configuracion?select=" + columnas + "&dispositivo_id=eq." + dispositivo_id))
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

    def insertar_evento(self, evento):
        """insert en eventos. Si el evento ya estaba (reenvío del buffer, RNF-17), se ignora."""
        self._con_reintento(lambda: self._pedir(
            "POST", "/rest/v1/eventos?on_conflict=dispositivo_id,ocurrido_en,tipo", evento,
            prefer="resolution=ignore-duplicates,return=minimal"))

    def subir_archivo(self, bucket, ruta, archivo_local, tipo, trozo=1024):
        """Sube un archivo de la flash a Storage, en trozos de `trozo` bytes.
        Devuelve False si el archivo ya existía (subida repetida)."""
        destino = "/".join(_codificar(parte) for parte in ruta.split("/"))
        try:
            self._con_reintento(lambda: self._enviar_archivo(
                "/storage/v1/object/%s/%s" % (bucket, destino), archivo_local, tipo, trozo))
        except ErrorSupabase as e:
            texto = str(e)
            # Storage responde 400 o 409 "Duplicate" si un intento anterior sí llegó.
            if e.estado in (400, 409) and ("Duplicate" in texto or "already exists" in texto):
                return False
            raise
        return True
