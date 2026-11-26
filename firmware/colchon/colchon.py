# ============================================================
# colchon.py · EP04 Colchón inteligente: lógica local (sin red)
#
# Aquí vive lo CRÍTICO, y por eso no depende de Wi-Fi ni de Supabase (RNF-16):
#   * HU-15  promedio del peso para el snapshot (la base lo valida y lo guarda).
#   * HU-16  alarma anti-robo: si en siesta el peso cae >= alarma_caida_pct %
#            respecto al snapshot durante `segundos_confirmacion`, suena el buzzer
#            y se encola el evento `alarma_antirrobo` (el trigger de la base crea
#            la alerta crítica y el aviso de Telegram, HU-17).
#            La alarma NO se apaga sola: solo con desactivar() (CA-16.3).
#   * HU-18  desactivar(): apaga el buzzer y deja de vigilar (CA-18.1, CA-18.2).
#   * HU-19  igual con la cuna o con fuente propia (CA-19.1): nada aquí cambia;
#            solo se informa `conectado_cuna` (CA-14.2).
#
# El snapshot se guarda también en siesta.json: si la placa se reinicia en plena
# siesta, sigue vigilando con el mismo peso base.
# ============================================================

import json
import time

try:
    import _thread
    _nuevo_candado = _thread.allocate_lock
except ImportError:           # CPython (pruebas)
    import threading
    _nuevo_candado = threading.Lock

if hasattr(time, "ticks_ms"):
    ticks_ms, ticks_diff = time.ticks_ms, time.ticks_diff
else:                          # CPython (pruebas)
    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b

LECTURAS_MEDIANA = 5       # filtro anti-ruido: mediana de las últimas 5 muestras (~0,5 s)
VENTANA_SNAPSHOT = 20      # muestras filtradas que se promedian para el snapshot (~2 s)
MS_SENSOR_PERDIDO = 3000   # sin muestras válidas durante este tiempo = sensor sin respuesta
MAX_EVENTOS = 60           # cola de eventos pendientes de enviar


class Balanza:
    """Convierte el valor crudo del HX711 a gramos: gramos = (crudo - offset) / factor."""

    def __init__(self, hx711, offset=0, factor=1.0):
        self.hx = hx711
        self.offset = offset
        self.factor = factor if factor else 1.0

    def tomar(self):
        crudo = self.hx.leer_crudo()
        if crudo is None:
            return None
        return (crudo - self.offset) / self.factor


def _mediana(valores):
    s = sorted(valores)
    return s[len(s) // 2]


class Colchon:
    def __init__(self, balanza, buzzer, lee_cuna=None, archivo="siesta.json",
                 segundos_confirmacion=2.0):
        self.balanza = balanza
        self.buzzer = buzzer
        self.lee_cuna = lee_cuna or (lambda: False)
        self.archivo = archivo
        self.ms_confirmacion = int(segundos_confirmacion * 1000)
        self.hora_iso = lambda: None        # main.py la reemplaza cuando hay hora real

        # ajustes que llegan de la base (valores por defecto = los de la base)
        self.peso_minimo_g = 500.0
        self.caida_pct = 30.0

        self.peso = None                    # último peso filtrado (g)
        self._crudas = []
        self._ventana = []
        self._ultima_muestra = None

        self.siesta = False
        self.base = None
        self.alarma = False
        self._t_bajo = None                 # desde cuándo está bajo el umbral
        self._prueba_hasta = None

        self._eventos = []
        self._candado = _nuevo_candado()
        self._cargar_siesta()

    # ------------------------------------------------------------ medición
    def actualizar(self, ahora):
        """Una vuelta del bucle principal. No bloquea."""
        g = self.balanza.tomar()
        if g is not None:
            self._ultima_muestra = ahora
            self._crudas.append(g)
            del self._crudas[:-LECTURAS_MEDIANA]
            self.peso = _mediana(self._crudas)
            self._ventana.append(self.peso)
            del self._ventana[:-VENTANA_SNAPSHOT]
        self._vigilar(ahora)
        self._sonar(ahora)

    def sensor_ok(self, ahora):
        return (self._ultima_muestra is not None
                and ticks_diff(ahora, self._ultima_muestra) < MS_SENSOR_PERDIDO)

    def promedio(self, ahora):
        """Promedio del peso reciente (HU-15). None si el sensor no responde."""
        if not self.sensor_ok(ahora) or len(self._ventana) < LECTURAS_MEDIANA:
            return None
        return sum(self._ventana) / len(self._ventana)

    # ------------------------------------------------------------ siesta
    def umbral(self):
        return None if self.base is None else self.base * (1 - self.caida_pct / 100.0)

    def activar(self, base_g):
        """Empieza a vigilar contra el snapshot `base_g` (ya aceptado por la base)."""
        self.siesta = True
        self.base = float(base_g)
        self.alarma = False
        self._t_bajo = None
        self._guardar_siesta()

    def desactivar(self):
        """HU-18: sin siesta no hay alarma. Apaga el buzzer."""
        self.siesta = False
        self.base = None
        self.alarma = False
        self._t_bajo = None
        self.buzzer.apagar()
        self._borrar_siesta()

    def _vigilar(self, ahora):
        if not self.siesta or self.alarma or self.peso is None or not self.sensor_ok(ahora):
            return
        if self.peso <= self.umbral():
            if self._t_bajo is None:
                self._t_bajo = ahora
            elif ticks_diff(ahora, self._t_bajo) >= self.ms_confirmacion:
                self._disparar()
        else:
            self._t_bajo = None            # CA-16.2: una caída pasajera o pequeña no cuenta

    def _disparar(self):
        self.alarma = True
        self._encolar({"tipo": "alarma_antirrobo", "valor": round(self.peso, 1), "unidad": "g",
                       "descripcion": "Caída de peso durante la siesta"})

    # ------------------------------------------------------------ buzzer
    def probar_buzzer(self, ahora, ms=1000):
        """Orden `probar_buzzer` de la app (HU-07, CA-07.2)."""
        self._prueba_hasta = ahora + ms

    def _sonar(self, ahora):
        if self.alarma:
            self.buzzer.fijar((ahora // 250) % 2 == 0)      # pitido intermitente
        elif self._prueba_hasta is not None and ticks_diff(self._prueba_hasta, ahora) > 0:
            self.buzzer.fijar(True)
        else:
            self._prueba_hasta = None
            self.buzzer.apagar()

    # ------------------------------------------------------------ eventos
    def _encolar(self, evento):
        evento = dict(evento)
        hora = self.hora_iso()
        if hora:                              # sin hora real, la base pone la suya
            evento["ocurrido_en"] = hora
        with self._candado:
            self._eventos.append(evento)
            while len(self._eventos) > MAX_EVENTOS:
                for i, e in enumerate(self._eventos):   # primero se descartan muestras de peso
                    if e["tipo"] != "alarma_antirrobo":
                        del self._eventos[i]
                        break
                else:
                    del self._eventos[0]

    def encolar_muestra(self, ahora):
        if self.peso is not None and self.sensor_ok(ahora):
            self._encolar({"tipo": "peso", "valor": round(self.peso), "unidad": "g"})

    def sacar_eventos(self):
        with self._candado:
            salida, self._eventos = self._eventos, []
        return salida

    def devolver_eventos(self, eventos):
        with self._candado:
            self._eventos = list(eventos) + self._eventos

    # ------------------------------------------------------------ estado
    def lectura(self, ahora):
        """Contenido de ultima_lectura (lo que muestra la tarjeta del colchón)."""
        datos = {"conectado_cuna": bool(self.lee_cuna()), "siesta": self.siesta, "alarma": self.alarma}
        if self.peso is not None and self.sensor_ok(ahora):
            datos["peso"] = round(self.peso)
        else:
            datos["aviso"] = "Sensor de peso sin respuesta"
        return datos

    # ------------------------------------------------------------ archivo
    def _guardar_siesta(self):
        try:
            with open(self.archivo, "w") as f:
                json.dump({"base": self.base}, f)
        except Exception as e:
            print("siesta.json:", type(e).__name__)

    def _borrar_siesta(self):
        try:
            import os
            os.remove(self.archivo)
        except Exception:
            pass

    def _cargar_siesta(self):
        try:
            with open(self.archivo) as f:
                base = json.load(f).get("base")
            if base:
                self.siesta, self.base = True, float(base)
        except Exception:
            pass
