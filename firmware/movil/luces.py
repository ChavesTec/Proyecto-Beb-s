# ============================================================
# luces.py · EP05 Móvil de luces LED (MicroPython)
#
# Secuencias y control de los LEDs, sin red. Basado en raspberry_movil.py
# (versión USB del compañero): mismas cinco secuencias, cambio de velocidad
# sin reiniciar la secuencia (CA-21.1) y apagado total (CA-20.2).
#
# Cambios para el contrato de Supabase (README_BASE_DATOS.md):
#   * La base guarda la secuencia y la velocidad como números
#     (configuracion.movil_secuencia >= 1, movil_velocidad 1..3).
#     NUMERO_A_SECUENCIA y NUMERO_A_VELOCIDAD son la tabla oficial; la app
#     de escritorio usa la misma (app/config/valores.py).
#   * Las secuencias reciben la cantidad de LEDs: sirven para los 6 LEDs por
#     PWM del prototipo o para el anillo WS2812B de 16 LEDs de la arquitectura.
#   * Los horarios ya no los aplica la PC: los aplica pg_cron en la base.
# ============================================================

import time

try:
    import _thread
    _nuevo_candado = _thread.allocate_lock
except ImportError:  # CPython sin _thread (pruebas)
    import threading
    _nuevo_candado = threading.Lock

# --- reloj: MicroPython usa ticks_*; en CPython (pruebas) se emulan ---
if hasattr(time, "ticks_ms"):
    ticks_ms, ticks_add, ticks_diff = time.ticks_ms, time.ticks_add, time.ticks_diff
else:
    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_add(t, delta):
        return t + delta

    def ticks_diff(a, b):
        return a - b


# Tabla oficial número <-> nombre (compartida con la app de escritorio).
NUMERO_A_SECUENCIA = {1: "alternada", 2: "progresiva", 3: "colores", 4: "suave", 5: "ronda"}
NUMERO_A_VELOCIDAD = {1: "lenta", 2: "media", 3: "rapida"}

# Más grande = más lento: porcentaje del intervalo base de cada secuencia (HU-21).
FACTOR_VELOCIDAD = {"lenta": 160, "media": 100, "rapida": 60}

PASOS_SUAVE = 60


def grupos_de_color(n, cantidad=3):
    """Reparte n LEDs en grupos contiguos (para la secuencia 'colores')."""
    cantidad = max(1, min(cantidad, n))
    return [list(range(i * n // cantidad, (i + 1) * n // cantidad)) for i in range(cantidad)]


# ---------------- secuencias: (paso, n LEDs) -> brillos 0-100 ----------------
def cuadro_alternada(paso, n):
    """LEDs pares e impares se encienden por turnos."""
    return [100 if (i % 2) == (paso % 2) else 0 for i in range(n)]


def cuadro_progresiva(paso, n):
    """Se encienden uno tras otro y luego se apagan uno tras otro."""
    if paso < n:
        return [100 if i <= paso else 0 for i in range(n)]
    k = paso - n + 1
    return [100 if i >= k else 0 for i in range(n)]


def cuadro_colores(paso, n):
    """Un grupo de color a la vez y al final todos juntos."""
    grupos = grupos_de_color(n)
    if paso < len(grupos):
        cuadro = [0] * n
        for i in grupos[paso]:
            cuadro[i] = 100
        return cuadro
    return [100] * n


def cuadro_suave(paso, n):
    """Brillo que sube y baja ("respiración"), con desfase entre LEDs."""
    mitad = PASOS_SUAVE // 2
    cuadro = []
    for i in range(n):
        fase = (paso + i * PASOS_SUAVE // n) % PASOS_SUAVE
        t = fase if fase < mitad else PASOS_SUAVE - fase
        cuadro.append(t * 100 // mitad)
    return cuadro


def cuadro_ronda(paso, n):
    """Un solo LED recorre el círculo."""
    return [100 if i == paso else 0 for i in range(n)]


def pasos_de(nombre, n):
    return {"alternada": 2, "progresiva": 2 * n, "colores": len(grupos_de_color(n)) + 1,
            "suave": PASOS_SUAVE, "ronda": n}[nombre]


# nombre: (intervalo base ms en velocidad media, intervalo mínimo ms, función).
# El mínimo evita destellos rápidos aunque se configure mal.
SECUENCIAS = {
    "alternada": (700, 400, cuadro_alternada),
    "progresiva": (600, 350, cuadro_progresiva),
    "colores": (900, 500, cuadro_colores),
    "suave": (60, 25, cuadro_suave),
    "ronda": (500, 350, cuadro_ronda),
}


class MovilLed:
    """Estado de las luces. actualizar() se llama muy seguido y nunca espera.

    El hilo de red llama a aplicar_config() y destello(); el bucle principal
    llama a actualizar(). Un candado protege el estado compartido.
    """

    def __init__(self, salida):
        self.salida = salida
        self.n = salida.cantidad
        self._candado = _nuevo_candado()
        self.encendido = False
        self.secuencia = "alternada"
        self.velocidad = "media"
        self.numero_secuencia = 1
        self.numero_velocidad = 2
        self.paso = 0
        ahora = ticks_ms()
        self.t_ultimo_paso = ahora
        self.t_proximo_paso = ahora
        self.t_fin_destello = None
        self.motivo = "inicio"        # por qué está apagado
        self.aviso = None             # p. ej. secuencia desconocida
        self.salida.apagar()

    # ------------------------------------------------------------ internos
    def _intervalo_ms(self):
        base, minimo, _ = SECUENCIAS[self.secuencia]
        return max(minimo, base * FACTOR_VELOCIDAD[self.velocidad] // 100)

    # ------------------------------------------------- órdenes de la base
    def aplicar_config(self, encendido, numero_secuencia, numero_velocidad):
        """Aplica la fila de configuracion. Devuelve True si algo cambió."""
        with self._candado:
            cambio = False
            self.aviso = None
            nombre = NUMERO_A_SECUENCIA.get(numero_secuencia)
            if nombre is None:
                self.aviso = "secuencia_desconocida"
                nombre, numero_secuencia = "alternada", 1
            if nombre != self.secuencia:
                self.secuencia, self.numero_secuencia = nombre, numero_secuencia
                self.paso = 0
                self.t_proximo_paso = ticks_ms()
                cambio = True

            nivel = NUMERO_A_VELOCIDAD.get(numero_velocidad)
            if nivel is None:
                self.aviso = self.aviso or "velocidad_desconocida"
                nivel, numero_velocidad = "media", 2
            if nivel != self.velocidad:
                # CA-21.1: se conserva el paso; solo se reprograma el siguiente.
                self.velocidad, self.numero_velocidad = nivel, numero_velocidad
                self.t_proximo_paso = ticks_add(self.t_ultimo_paso, self._intervalo_ms())
                cambio = True

            encendido = bool(encendido)
            if encendido and not self.encendido:
                self.encendido = True
                self.motivo = None
                self.paso = 0
                self.t_proximo_paso = ticks_ms()
                cambio = True
            elif not encendido and self.encendido:
                self._apagar("usuario")
                cambio = True
            elif not encendido and self.motivo == "sin_conexion":
                self.motivo = "usuario"  # La base confirma que debe seguir apagado.
            return cambio

    def apagar_sin_conexion(self):
        """Sin contacto con Supabase un buen rato: se apaga por seguridad."""
        with self._candado:
            if self.encendido:
                self._apagar("sin_conexion")

    def destello(self, duracion_ms=2000):
        """Comando probar_luz (HU-07): todos los LEDs encendidos un momento."""
        with self._candado:
            self.t_fin_destello = ticks_add(ticks_ms(), duracion_ms)
            self.salida.escribir([100] * self.n)

    def _apagar(self, motivo):
        self.encendido = False
        self.motivo = motivo
        self.salida.apagar()   # CA-20.2: todos los LEDs apagados

    # ------------------------------------------------------ bucle principal
    def actualizar(self):
        with self._candado:
            ahora = ticks_ms()
            if self.t_fin_destello is not None:
                if ticks_diff(ahora, self.t_fin_destello) < 0:
                    return
                self.t_fin_destello = None
                if not self.encendido:
                    self.salida.apagar()
                    return
                self.t_proximo_paso = ahora
            if not self.encendido:
                return
            if ticks_diff(ahora, self.t_proximo_paso) >= 0:
                funcion = SECUENCIAS[self.secuencia][2]
                self.salida.escribir(funcion(self.paso, self.n))
                self.paso = (self.paso + 1) % pasos_de(self.secuencia, self.n)
                self.t_ultimo_paso = ahora
                self.t_proximo_paso = ticks_add(ahora, self._intervalo_ms())

    def lectura(self):
        """Lo que se manda en registrar_senal(p_lectura): la vista en vivo de la app."""
        with self._candado:
            datos = {"encendido": self.encendido, "secuencia": self.numero_secuencia,
                     "velocidad": self.numero_velocidad}
            if not self.encendido and self.motivo:
                datos["motivo"] = self.motivo
            if self.aviso:
                datos["aviso"] = self.aviso
            return datos
