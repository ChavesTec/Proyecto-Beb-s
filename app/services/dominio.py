"""Reglas puras de la aplicación (sin red ni Tkinter): fáciles de probar."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Iterable

from app.config.valores import MAX_MP3_BYTES, NOMBRES_COMANDO, SEGUNDOS_FUERA_DE_LINEA
from app.config.zona import ahora_utc, parsear_fecha_iso
from app.errores import ErrorValidacion

# --------------------------------------------------------------------- cuentas
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LARGO_MINIMO_CLAVE = 8


def validar_correo(correo: str) -> str:
    correo = (correo or "").strip().lower()
    if not correo:
        raise ErrorValidacion("Ingrese su correo.")
    if not _CORREO.match(correo) or len(correo) > 254:
        raise ErrorValidacion("El correo no es válido.")
    return correo


def validar_clave(clave: str, confirmar: str | None = None) -> str:
    if len(clave or "") < LARGO_MINIMO_CLAVE:
        raise ErrorValidacion(f"La contraseña debe tener al menos {LARGO_MINIMO_CLAVE} caracteres.")
    if confirmar is not None and clave != confirmar:
        raise ErrorValidacion("Las contraseñas no coinciden.")
    return clave


# --------------------------------------------------------------------- perfiles
def validar_perfil(nombre: str, fecha_texto: str) -> tuple[str, date]:
    from app.config.zona import parsear_fecha_local

    nombre = (nombre or "").strip()
    if not nombre:
        raise ErrorValidacion("El nombre del perfil no puede estar vacío.")
    if len(nombre) > 80:
        raise ErrorValidacion("El nombre es demasiado largo (máximo 80 caracteres).")
    try:
        fecha = parsear_fecha_local(fecha_texto)
    except ValueError as error:
        raise ErrorValidacion(str(error)) from None
    if fecha > date.today():
        raise ErrorValidacion("La fecha de nacimiento no puede estar en el futuro.")
    return nombre, fecha


# ------------------------------------------------------------- conexión (HU-06)
EN_LINEA, FUERA_DE_LINEA, SIN_DATOS = "en_linea", "fuera_de_linea", "sin_datos"
NOMBRES_CONEXION = {EN_LINEA: "En línea", FUERA_DE_LINEA: "Fuera de línea", SIN_DATOS: "Sin datos"}


def estado_conexion(dispositivo: dict, ahora: datetime | None = None,
                    umbral_s: int = SEGUNDOS_FUERA_DE_LINEA) -> str:
    """En línea solo con evidencia: señal en los últimos 60 s y en_linea=true.

    * Sin ultima_senal_en → SIN_DATOS (nunca se convierte en "normal").
    * Más de 60 s sin señal → FUERA_DE_LINEA aunque pg_cron aún no lo marque.
    * en_linea=false (pg_cron ya lo marcó) → FUERA_DE_LINEA.
    """
    senal = parsear_fecha_iso(dispositivo.get("ultima_senal_en"))
    if senal is None:
        return SIN_DATOS
    edad = ((ahora or ahora_utc()) - senal).total_seconds()
    if edad > umbral_s or not dispositivo.get("en_linea"):
        return FUERA_DE_LINEA
    return EN_LINEA


def advertencia_critica_desconexion(dispositivo: dict, config: dict | None, conexion: str) -> str | None:
    """CA-06.2: colchón en siesta o seguridad armada que queda fuera de línea."""
    if conexion != FUERA_DE_LINEA or not config:
        return None
    if dispositivo.get("tipo") == "colchon" and config.get("siesta_activa"):
        return "El colchón está FUERA DE LÍNEA con el modo siesta activo. La alarma local sigue funcionando en el colchón, pero la app no recibe datos."
    if dispositivo.get("tipo") == "seguridad" and config.get("seguridad_armada"):
        return "La seguridad está ARMADA y el dispositivo está FUERA DE LÍNEA: no se registran eventos de puerta ni presencia."
    return None


# ------------------------------------------------------------------- permisos
def puede_controlar(dispositivo: dict, usuario_id: str, accesos: dict[str, bool]) -> bool:
    """Espejo de puede_controlar_dispositivo(): solo para habilitar controles.

    La base vuelve a validar siempre; la UI nunca depende solo de esto.
    """
    if dispositivo.get("propietario_id") == usuario_id:
        return True
    perfil = dispositivo.get("perfil_id")
    return bool(perfil and accesos.get(perfil))


def filtrar_dispositivos(dispositivos: Iterable[dict], perfil_id: str | None = None,
                         tipo: str | None = None, sin_asignar: bool = False) -> list[dict]:
    resultado = []
    for d in dispositivos:
        if sin_asignar and d.get("perfil_id"):
            continue
        if perfil_id and d.get("perfil_id") != perfil_id:
            continue
        if tipo and d.get("tipo") != tipo:
            continue
        resultado.append(d)
    return resultado


# -------------------------------------------------------------------- comandos
NOMBRES_ESTADO_COMANDO = {"pendiente": "Pendiente", "ejecutado": "Ejecutado", "fallido": "Fallido"}


def describir_comando(comando: dict) -> str:
    """Nunca dice "ejecutado" por haber insertado la fila: usa el estado real."""
    nombre = NOMBRES_COMANDO.get(comando.get("tipo", ""), comando.get("tipo", "Orden"))
    estado = comando.get("estado") or "pendiente"
    texto = f"{nombre}: {NOMBRES_ESTADO_COMANDO.get(estado, estado)}"
    if estado == "fallido":
        texto += f" — {comando.get('resultado') or 'el dispositivo no indicó el motivo'}"
    elif estado == "ejecutado" and comando.get("resultado"):
        texto += f" — {comando['resultado']}"
    elif estado == "pendiente":
        texto += " (esperando al dispositivo)"
    return texto


# --------------------------------------------------------------- configuración
def _numero(texto: Any, nombre: str, entero: bool = False) -> float | int:
    if texto is None or str(texto).strip() == "":
        raise ErrorValidacion(f"Ingrese un valor para {nombre}.")
    try:
        valor = float(str(texto).replace(",", "."))
    except ValueError:
        raise ErrorValidacion(f"{nombre.capitalize()} debe ser un número.") from None
    if valor != valor or valor in (float("inf"), float("-inf")):
        raise ErrorValidacion(f"{nombre.capitalize()} debe ser un número.")
    if entero:
        if not valor.is_integer():
            raise ErrorValidacion(f"{nombre.capitalize()} debe ser un número entero.")
        return int(valor)
    return round(valor, 2)


def validar_rango(minimo: Any, maximo: Any, nombre: str, limite_inf: float | None = None,
                  limite_sup: float | None = None) -> tuple[float, float]:
    """CA-09.3: mínimo estrictamente menor que el máximo."""
    a = _numero(minimo, f"{nombre} mínima")
    b = _numero(maximo, f"{nombre} máxima")
    if a >= b:
        raise ErrorValidacion(f"La {nombre} mínima debe ser menor que la máxima.")
    if limite_inf is not None and a < limite_inf:
        raise ErrorValidacion(f"La {nombre} mínima no puede ser menor que {limite_inf:g}.")
    if limite_sup is not None and b > limite_sup:
        raise ErrorValidacion(f"La {nombre} máxima no puede ser mayor que {limite_sup:g}.")
    if abs(a) > 999 or abs(b) > 999:
        raise ErrorValidacion(f"La {nombre} está fuera del rango admitido.")
    return a, b


def validar_entero(texto: Any, nombre: str, minimo: int | None = None, maximo: int | None = None) -> int:
    valor = int(_numero(texto, nombre, entero=True))
    if minimo is not None and valor < minimo:
        raise ErrorValidacion(f"{nombre.capitalize()} debe ser al menos {minimo}.")
    if maximo is not None and valor > maximo:
        raise ErrorValidacion(f"{nombre.capitalize()} debe ser como máximo {maximo}.")
    return valor


def validar_decimal(texto: Any, nombre: str, minimo: float | None = None, maximo: float | None = None,
                    minimo_exclusivo: bool = False) -> float:
    valor = float(_numero(texto, nombre))
    if minimo is not None and (valor < minimo or (minimo_exclusivo and valor == minimo)):
        signo = "mayor que" if minimo_exclusivo else "al menos"
        raise ErrorValidacion(f"{nombre.capitalize()} debe ser {signo} {minimo:g}.")
    if maximo is not None and valor > maximo:
        raise ErrorValidacion(f"{nombre.capitalize()} debe ser como máximo {maximo:g}.")
    return valor


def origen_valor(config: dict | None, columna: str, predeterminados: dict) -> str:
    """'predeterminado' si coincide con el valor inicial documentado; si no, 'personalizado'."""
    if not config or columna not in config:
        return "sin datos"
    actual = config[columna]
    base = predeterminados.get(columna)
    if base is None:
        return "guardado"
    try:
        return "predeterminado" if float(actual) == float(base) else "personalizado"
    except (TypeError, ValueError):
        return "predeterminado" if actual == base else "personalizado"


# --------------------------------------------------------------------- horarios
NOMBRES_DIAS = ("Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb")  # 0 = domingo (migración 1)


def parsear_hora(texto: str) -> time:
    texto = (texto or "").strip()
    try:
        return datetime.strptime(texto, "%H:%M").time()
    except ValueError:
        raise ErrorValidacion(f"Hora no válida: {texto!r}. Use HH:MM (24 h).") from None


def validar_horario(dias: Iterable[int], inicio: str, fin: str) -> tuple[list[int], str, str]:
    dias = sorted({int(d) for d in dias})
    if not dias:
        raise ErrorValidacion("Seleccione al menos un día de la semana.")
    if any(d < 0 or d > 6 for d in dias):
        raise ErrorValidacion("Día de la semana no válido.")
    h_ini, h_fin = parsear_hora(inicio), parsear_hora(fin)
    if h_ini == h_fin:
        raise ErrorValidacion("La hora de inicio y la de fin no pueden ser iguales.")
    return dias, h_ini.strftime("%H:%M"), h_fin.strftime("%H:%M")


def describir_horario(h: dict) -> str:
    dias = ", ".join(NOMBRES_DIAS[d] for d in sorted(h.get("dias") or []) if 0 <= d <= 6)
    texto = f"{dias} · {str(h.get('hora_inicio', ''))[:5]}–{str(h.get('hora_fin', ''))[:5]}"
    if h.get("secuencia"):
        from app.config.valores import nombre_secuencia

        texto += f" · {nombre_secuencia(h['secuencia'])}"
    if str(h.get("hora_fin", "")) < str(h.get("hora_inicio", "")):
        texto += " (cruza medianoche)"
    if not h.get("activo", True):
        texto += " · inactivo"
    return texto


# ----------------------------------------------------------------------- audio
def validar_mp3(nombre_archivo: str, tamano: int, cabecera: bytes = b"") -> None:
    """CA-13.3: solo MP3 de hasta 5 MB."""
    if not nombre_archivo.lower().endswith(".mp3"):
        raise ErrorValidacion("Formato no admitido: solo se aceptan archivos .mp3.")
    if tamano <= 0:
        raise ErrorValidacion("El archivo está vacío.")
    if tamano > MAX_MP3_BYTES:
        raise ErrorValidacion(f"El MP3 pesa {tamano / 1048576:.1f} MB; el máximo es 5 MB.")
    if cabecera and not (cabecera.startswith(b"ID3") or (len(cabecera) > 1 and cabecera[0] == 0xFF
                                                          and (cabecera[1] & 0xE0) == 0xE0)):
        raise ErrorValidacion("El archivo no parece un MP3 válido.")


# ---------------------------------------------------------------- alimentación
def validar_cantidad_ml(texto: Any) -> float:
    """CA-35.2: rechaza vacío o negativo."""
    if texto is None or str(texto).strip() == "":
        raise ErrorValidacion("Ingrese la cantidad ingerida en mililitros.")
    valor = validar_decimal(texto, "la cantidad", minimo=0)
    if valor > 9999:
        raise ErrorValidacion("La cantidad es demasiado grande.")
    return round(valor, 1)


def formato_duracion(segundos: int | float | None) -> str:
    if segundos is None:
        return "—"
    segundos = max(int(segundos), 0)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ----------------------------------------------------------- lecturas en vivo
@dataclass(frozen=True)
class Lectura:
    etiqueta: str
    valor: str


# Claves conocidas de ultima_lectura. Solo `conectado_cuna` está confirmada por el
# contrato (CA-14.2); las demás son nombres razonables que el firmware puede usar.
# Si llega otra clave, se muestra tal cual en lugar de inventar un significado.
_CLAVES_LECTURA = {
    "temperatura": ("Temperatura", "°C"),
    "humedad": ("Humedad", "%"),
    "temperatura_biberon": ("Temperatura de la leche", "°C"),
    "peso": ("Peso", "g"),
    "peso_g": ("Peso", "g"),
    "movimiento": ("Movimiento", ""),
    "luz_intensidad": ("Luz nocturna", "%"),
    "puerta": ("Puerta", ""),
    "presencia": ("Presencia", ""),
    "boton_activo": ("Botón iluminado", ""),
    "aciertos": ("Aciertos", ""),
    "secuencia": ("Secuencia", ""),
    "velocidad": ("Velocidad", ""),
    "motivo": ("Motivo del último apagado", ""),
    "aviso": ("Aviso del dispositivo", ""),
    "encendido": ("Encendido", ""),
    "reproduciendo": ("Reproduciendo", ""),
}


def _formato_valor(valor: Any, unidad: str) -> str:
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, (int, float)):
        texto = f"{valor:.1f}".rstrip("0").rstrip(".") if isinstance(valor, float) else str(valor)
        return f"{texto} {unidad}".strip()
    if valor is None:
        return "—"
    return f"{valor} {unidad}".strip()


_MOTIVOS_APAGADO = {"sin_conexion": "perdió la conexión con Supabase", "usuario": "orden de la app o del horario",
                    "inicio": "el dispositivo acaba de arrancar"}


def lecturas_de(dispositivo: dict) -> list[Lectura]:
    """Convierte ultima_lectura (jsonb libre) en filas legibles, sin inventar valores."""
    datos = dispositivo.get("ultima_lectura")
    if not isinstance(datos, dict):
        return []
    resultado = []
    for clave, valor in datos.items():
        if clave == "conectado_cuna":
            resultado.append(Lectura("Alimentación", "Conectado a la cuna" if valor else "Independiente"))
            continue
        etiqueta, unidad = _CLAVES_LECTURA.get(clave, (clave.replace("_", " ").capitalize(), ""))
        if dispositivo.get("tipo") == "biberon" and clave == "temperatura":
            etiqueta = "Temperatura de la leche"
        if clave == "motivo" and valor in _MOTIVOS_APAGADO:
            resultado.append(Lectura(etiqueta, _MOTIVOS_APAGADO[valor]))
            continue
        if dispositivo.get("tipo") == "movil" and clave in ("secuencia", "velocidad"):
            from app.config.valores import nombre_secuencia, nombre_velocidad

            resultado.append(Lectura(etiqueta, (nombre_secuencia if clave == "secuencia" else nombre_velocidad)(valor)))
            continue
        resultado.append(Lectura(etiqueta, _formato_valor(valor, unidad)))
    return resultado


def valor_lectura(dispositivo: dict, *claves: str) -> Any:
    datos = dispositivo.get("ultima_lectura")
    if not isinstance(datos, dict):
        return None
    for clave in claves:
        if clave in datos:
            return datos[clave]
    return None


def conexion_colchon(dispositivo: dict) -> str:
    """CA-14.2: "Conectado a la cuna" / "Independiente" / sin datos."""
    valor = valor_lectura(dispositivo, "conectado_cuna")
    if valor is None:
        return "Sin datos de alimentación"
    return "Conectado a la cuna" if valor else "Independiente"


# ---------------------------------------------------------------------- alertas
NOMBRES_SEVERIDAD = {"critica": "CRÍTICA", "advertencia": "Advertencia", "informativa": "Informativa"}
NOMBRES_ESTADO_ALERTA = {
    "pendiente": "Pendiente de envío",
    "enviada": "Enviada por Telegram",
    "fallida": "Envío fallido (se reintenta)",
    "sin_destinatarios": "Sin destinatarios con Telegram",
}
NOMBRES_TIPO_ALERTA = {
    "temperatura_baja": "Temperatura baja", "temperatura_alta": "Temperatura alta",
    "humedad_baja": "Humedad baja", "humedad_alta": "Humedad alta", "movimiento": "Movimiento",
    "antirrobo": "Anti-robo", "puerta": "Puerta", "presencia": "Presencia",
    "fuera_de_linea": "Fuera de línea", "biberon_caliente": "Biberón demasiado caliente",
    "biberon_fria": "Biberón demasiado frío", "recordatorio": "Recordatorio",
}
