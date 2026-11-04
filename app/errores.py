"""Traducción centralizada de errores de Supabase a mensajes en español.

Ninguna pantalla interpreta excepciones del SDK: todas pasan por `traducir_error`.
Nunca se incluyen tokens, contraseñas ni JWT en los mensajes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MENSAJE_CREDENCIALES = "Correo o contraseña incorrectos"
MENSAJE_CORREO_REGISTRADO = "El correo ya está registrado"
MENSAJE_SIN_CONEXION = "No hay conexión con Supabase. Revise su red e intente de nuevo."
MENSAJE_SESION_EXPIRADA = "La sesión expiró. Inicie sesión de nuevo."
MENSAJE_SIN_PERMISO = "No tiene permiso para realizar esta acción."
MENSAJE_SIN_FILAS = (
    "No se aplicó el cambio: no tiene permiso sobre este recurso o ya no existe."
)


class ErrorApp(Exception):
    """Error ya traducido, listo para mostrar."""

    def __init__(self, mensaje: str, tipo: str = "error", codigo: str | None = None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.tipo = tipo  # error | sin_permiso | sin_conexion | sesion | validacion | no_encontrado
        self.codigo = codigo


class ErrorValidacion(ErrorApp):
    def __init__(self, mensaje: str):
        super().__init__(mensaje, "validacion")


class SinFilasAfectadas(ErrorApp):
    """Un update filtrado por RLS devuelve 0 filas sin error."""

    def __init__(self, mensaje: str = MENSAJE_SIN_FILAS):
        super().__init__(mensaje, "sin_permiso")


class SesionExpirada(ErrorApp):
    def __init__(self, mensaje: str = MENSAJE_SESION_EXPIRADA):
        super().__init__(mensaje, "sesion")


# Reglas check de las migraciones → mensaje claro (código 23514).
MENSAJES_CHECK = {
    "configuracion_rango_temperatura": "La temperatura mínima debe ser menor que la máxima.",
    "configuracion_rango_humedad": "La humedad mínima debe ser menor que la máxima y estar entre 0 y 100 %.",
    "configuracion_repeticion": "La repetición de alertas debe ser mayor que 0 minutos.",
    "configuracion_luz": "La intensidad de la luz debe estar entre 0 y 100 %.",
    "configuracion_peso_minimo": "El peso mínimo no puede ser negativo.",
    "configuracion_caida": "La caída de peso debe ser mayor que 0 y como máximo 100 %.",
    "configuracion_secuencia": "La secuencia del móvil debe ser 1 o mayor.",
    "configuracion_velocidad": "La velocidad del móvil debe ser 1, 2 o 3.",
    "configuracion_intervalo_foto": "El intervalo entre fotos debe ser mayor que 0 segundos.",
    "configuracion_tiempo_ronda": "El tiempo por ronda debe ser mayor que 0 segundos.",
    "configuracion_volumen": "El volumen debe estar entre 0 y 100.",
    "horarios_dias_validos": "Seleccione al menos un día de la semana.",
    "horarios_horas_distintas": "La hora de inicio y la de fin no pueden ser iguales.",
    "horarios_horas_en_minutos": "Las horas deben indicarse en horas y minutos.",
    "horarios_secuencia_movil": "Los horarios del móvil deben indicar una secuencia.",
    "tomas_fin_despues_de_inicio": "La hora de fin de la toma no puede ser anterior al inicio.",
    "tomas_cantidad_valida": "La cantidad ingerida no puede ser negativa.",
    "tomas_cantidad_al_finalizar": "Solo se puede registrar la cantidad de una toma finalizada.",
    "recordatorios_datos_por_tipo": "Indique el intervalo (por intervalo) o la hora (a hora fija).",
    "recordatorios_intervalo_min_check": "El intervalo debe ser mayor que 0 minutos.",
    "audios_solo_mp3": "Solo se admiten archivos MP3.",
    "audios_tamano_valido": "El MP3 debe pesar como máximo 5 MB.",
    "perfiles_bebe_nombre_check": "El nombre del perfil no puede estar vacío.",
    "dispositivos_perfil_requiere_dueno": "El dispositivo debe estar registrado antes de asignarlo.",
}

MENSAJES_UNICOS = {
    "tomas_una_en_curso": "Ya hay una toma en curso para este perfil. Deténgala primero.",
    "snapshots_peso_una_siesta_activa": "El modo siesta ya está activo.",
    "audios_archivo_path_key": "Ya existe un audio con ese archivo.",
    "eventos_sin_duplicados": "El evento ya estaba registrado.",
}


@dataclass
class _Datos:
    texto: str
    codigo: str | None = None
    estado_http: int | None = None


def _extraer(error: BaseException) -> _Datos:
    codigo = getattr(error, "code", None)
    mensaje = getattr(error, "message", None)
    estado = getattr(error, "status", None)
    detalles = getattr(error, "details", None)
    texto = " ".join(str(p) for p in (mensaje, detalles) if p) or str(error)
    return _Datos(texto=texto, codigo=str(codigo) if codigo is not None else None,
                  estado_http=estado if isinstance(estado, int) else None)


def _es_error_red(error: BaseException) -> bool:
    try:
        import httpx

        if isinstance(error, (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
            return True
    except ImportError:  # pragma: no cover
        pass
    nombre = type(error).__name__
    if nombre in {"AuthRetryableError", "ConnectionError", "ConnectError", "gaierror", "TimeoutError"}:
        return True
    return isinstance(error, (ConnectionError, TimeoutError, OSError)) and not isinstance(
        error, FileNotFoundError
    )


def traducir_error_auth(error: BaseException, contexto: str = "login") -> ErrorApp:
    """Errores de Supabase Auth. En login nunca se revela si el correo existe (CA-02.2)."""
    if isinstance(error, ErrorApp):
        return error
    if _es_error_red(error):
        return ErrorApp(MENSAJE_SIN_CONEXION, "sin_conexion")
    d = _extraer(error)
    texto = d.texto.lower()
    if contexto == "login":
        if "email not confirmed" in texto or d.codigo == "email_not_confirmed":
            return ErrorApp("Debe confirmar su correo antes de iniciar sesión. Revise su bandeja de entrada.",
                            "validacion", d.codigo)
        if "rate limit" in texto or d.estado_http == 429:
            return ErrorApp("Demasiados intentos. Espere unos minutos e intente de nuevo.", "error", d.codigo)
        return ErrorApp(MENSAJE_CREDENCIALES, "validacion", d.codigo)
    # registro
    if "already registered" in texto or d.codigo in {"user_already_exists", "email_exists"}:
        return ErrorApp(MENSAJE_CORREO_REGISTRADO, "validacion", d.codigo)
    if "password" in texto and ("at least" in texto or "weak" in texto or "8" in texto):
        return ErrorApp("La contraseña debe tener al menos 8 caracteres.", "validacion", d.codigo)
    if "invalid" in texto and "email" in texto:
        return ErrorApp("El correo no es válido.", "validacion", d.codigo)
    if "rate limit" in texto or d.estado_http == 429:
        return ErrorApp("Demasiados intentos. Espere unos minutos e intente de nuevo.", "error", d.codigo)
    if "signups not allowed" in texto or "signup is disabled" in texto:
        return ErrorApp("El registro de cuentas está desactivado en este proyecto.", "error", d.codigo)
    return ErrorApp("No se pudo crear la cuenta. Intente de nuevo más tarde.", "error", d.codigo)


def traducir_error(error: BaseException) -> ErrorApp:
    """Errores de PostgREST, RPC y Storage."""
    if isinstance(error, ErrorApp):
        return error
    if _es_error_red(error):
        return ErrorApp(MENSAJE_SIN_CONEXION, "sin_conexion")

    d = _extraer(error)
    texto = d.texto
    bajo = texto.lower()

    # Sesión vencida o inválida (PostgREST PGRST301/PGRST303, Storage 'exp' claim).
    if d.codigo in {"PGRST301", "PGRST302", "PGRST303"} or "jwt expired" in bajo or "invalid jwt" in bajo:
        return SesionExpirada()

    if d.codigo == "23514":
        for regla, mensaje in MENSAJES_CHECK.items():
            if regla in texto:
                return ErrorApp(mensaje, "validacion", d.codigo)
        # Excepciones de funciones con errcode 23514 traen su propio texto en español.
        return ErrorApp(_mensaje_funcion(texto) or "Los datos no cumplen las reglas de la base.",
                        "validacion", d.codigo)

    if d.codigo == "23505":
        for regla, mensaje in MENSAJES_UNICOS.items():
            if regla in texto:
                return ErrorApp(mensaje, "validacion", d.codigo)
        return ErrorApp(_mensaje_funcion(texto) or "El registro ya existe.", "validacion", d.codigo)

    if d.codigo == "23P01":  # horarios traslapados (CA-22.3)
        return ErrorApp(_mensaje_funcion(texto) or "El horario se traslapa con otro ya guardado.",
                        "validacion", d.codigo)

    if d.codigo == "42501":
        mensaje = _mensaje_funcion(texto)
        if mensaje and "permission denied" not in mensaje.lower() and "row-level" not in mensaje.lower():
            return ErrorApp(mensaje, "sin_permiso", d.codigo)
        return ErrorApp(MENSAJE_SIN_PERMISO, "sin_permiso", d.codigo)

    if d.codigo == "P0002":
        return ErrorApp(_mensaje_funcion(texto) or "No se encontró el recurso.", "no_encontrado", d.codigo)

    if d.codigo in {"PGRST202", "42883"}:
        return ErrorApp(
            "La función solicitada no existe en la base de datos. Verifique que las migraciones "
            "estén aplicadas.", "error", d.codigo)
    if d.codigo in {"PGRST205", "42P01"}:
        return ErrorApp(
            "La tabla o vista no existe en la base de datos. Verifique que las migraciones "
            "estén aplicadas.", "error", d.codigo)
    if d.codigo == "PGRST116":
        return ErrorApp("No se encontró el registro solicitado.", "no_encontrado", d.codigo)
    if d.codigo == "22P02":
        return ErrorApp("Uno de los valores tiene un formato no válido.", "validacion", d.codigo)
    if d.codigo == "22003":
        return ErrorApp("Uno de los valores numéricos está fuera de rango.", "validacion", d.codigo)

    # Storage
    if "exceeded the maximum" in bajo or "payload too large" in bajo or d.estado_http == 413:
        return ErrorApp("El archivo supera el tamaño permitido.", "validacion", d.codigo)
    if "mime type" in bajo:
        return ErrorApp("Formato de archivo no admitido.", "validacion", d.codigo)
    if "row-level security" in bajo or "permission denied" in bajo:
        return ErrorApp(MENSAJE_SIN_PERMISO, "sin_permiso", d.codigo)
    if "object not found" in bajo or (d.estado_http == 404 and "not found" in bajo):
        return ErrorApp("El archivo no existe o no tiene acceso a él.", "no_encontrado", d.codigo)

    mensaje = _mensaje_funcion(texto)
    if mensaje and _parece_espanol(mensaje):
        return ErrorApp(mensaje, "error", d.codigo)
    return ErrorApp("Ocurrió un error inesperado al comunicarse con Supabase.", "error", d.codigo)


_PALABRAS_ES = re.compile(r"[áéíóúñ¿¡]|\b(no|el|la|los|las|de|para|ya|este|esta|tienes|cuenta)\b", re.I)


def _parece_espanol(texto: str) -> bool:
    return bool(_PALABRAS_ES.search(texto))


def _mensaje_funcion(texto: str) -> str | None:
    """El mensaje de un RAISE EXCEPTION llega tal cual; se limpia de prefijos técnicos."""
    if not texto:
        return None
    limpio = texto.strip().split("\n")[0]
    limpio = re.sub(r"^(ERROR:\s*)", "", limpio)
    return limpio or None
