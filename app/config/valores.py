"""Valores documentados en README_BASE_DATOS.md ("Valores establecidos por el desarrollador").

Son valores iniciales de la maqueta, no umbrales clínicos. Los que viven en la
tabla `configuracion` se leen de la base; aquí solo quedan como referencia para
mostrar el origen del valor (guardado o predeterminado) y para validar en la UI.
"""

# Fuera de línea: 60 s sin señal (CA-06.1). La base lo marca con pg_cron cada minuto.
SEGUNDOS_FUERA_DE_LINEA = 60

# Historial y alertas paginados de 50 en 50 (CA-39.1).
TAMANO_PAGINA = 50

# Límites de Storage (los aplica también el bucket).
MAX_FOTO_BYTES = 150 * 1024          # 153600, RNF-05
MAX_MP3_BYTES = 5 * 1024 * 1024      # 5242880, CA-13.2

# URLs firmadas de corta duración para el Storage privado.
SEGUNDOS_URL_FIRMADA = 120

# Valores predeterminados de `configuracion` (migración 1 y crear_configuracion()).
PREDETERMINADOS = {
    "cuna": {"temp_min": 18, "temp_max": 26, "hum_min": 40, "hum_max": 60,
             "alerta_repeticion_min": 10, "luz_intensidad": 0},
    "biberon": {"temp_min": 35, "temp_max": 40, "alerta_repeticion_min": 10},
    "colchon": {"peso_minimo_g": 500, "alarma_caida_pct": 30},
    "movil": {"movil_encendido": False, "movil_secuencia": 1, "movil_velocidad": 2},
    "seguridad": {"seguridad_armada": False, "seguridad_intervalo_foto_s": 30},
    "juguete": {"juguete_tiempo_ronda_s": 10, "juguete_volumen": 50},
}

# Secuencias y velocidades del móvil (CA-20.1, HU-21). La base guarda números
# (movil_secuencia >= 1, movil_velocidad 1..3); esta tabla es la misma que usa el
# firmware en firmware/movil/luces.py (NUMERO_A_SECUENCIA / NUMERO_A_VELOCIDAD).
SECUENCIAS_MOVIL = {1: "Alternada", 2: "Progresiva", 3: "Colores por grupos",
                    4: "Suave (respiración)", 5: "Ronda"}
VELOCIDADES_MOVIL = {1: "Lenta", 2: "Media", 3: "Rápida"}


def nombre_secuencia(numero) -> str:
    try:
        return SECUENCIAS_MOVIL.get(int(numero), f"Secuencia {numero}")
    except (TypeError, ValueError):
        return "—"


def nombre_velocidad(numero) -> str:
    try:
        return VELOCIDADES_MOVIL.get(int(numero), f"Velocidad {numero}")
    except (TypeError, ValueError):
        return "—"

# Polling de respaldo cuando Realtime no está disponible (segundos).
SEGUNDOS_POLLING_DEGRADADO = 10
SEGUNDOS_POLLING_NORMAL = 30

TIPOS_DISPOSITIVO = ("cuna", "colchon", "movil", "seguridad", "juguete", "biberon")

NOMBRES_TIPO = {
    "cuna": "Cuna inteligente",
    "colchon": "Colchón inteligente",
    "movil": "Móvil de luces LED",
    "seguridad": "Seguridad de la habitación",
    "juguete": "Juguete interactivo",
    "biberon": "Biberón inteligente",
}

# Tipos de evento de la tabla `eventos` (check de la migración 1).
TIPOS_EVENTO = (
    "temperatura", "humedad", "temperatura_biberon", "peso", "movimiento", "puerta",
    "presencia", "alarma_antirrobo", "siesta_activada", "siesta_desactivada",
    "seguridad_armada", "seguridad_desarmada", "conexion", "juguete_acierto", "sistema",
)

# Tipos de alerta (check de la migración 1).
TIPOS_ALERTA = (
    "temperatura_baja", "temperatura_alta", "humedad_baja", "humedad_alta", "movimiento",
    "antirrobo", "puerta", "presencia", "fuera_de_linea", "biberon_caliente", "biberon_fria",
    "recordatorio",
)
SEVERIDADES = ("critica", "advertencia", "informativa")
ESTADOS_ALERTA = ("pendiente", "enviada", "fallida", "sin_destinatarios")

# Comandos permitidos por la base (check de comandos.tipo). desactivar_siesta solo
# se crea desde la RPC desactivar_siesta() (la política lo impide directo).
COMANDOS_POR_TIPO = {
    "cuna": ("probar_luz", "probar_buzzer", "audio_reproducir", "audio_detener"),
    "colchon": ("activar_siesta", "probar_buzzer"),
    "movil": ("probar_luz",),
    "seguridad": ("tomar_foto",),
    "juguete": ("probar_luz", "probar_buzzer"),
    "biberon": ("probar_luz",),
}

NOMBRES_COMANDO = {
    "activar_siesta": "Activar modo siesta",
    "desactivar_siesta": "Desactivar modo siesta",
    "audio_reproducir": "Reproducir audio",
    "audio_detener": "Detener audio",
    "probar_luz": "Probar luz",
    "probar_buzzer": "Probar buzzer",
    "tomar_foto": "Tomar foto",
}
