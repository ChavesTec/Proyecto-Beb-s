# ============================================================
# vigilancia.py · EP06 Lógica del aparato de seguridad (sin hardware ni red)
#
# Reglas (README_BASE_DATOS.md y migraciones):
#   * Desarmada (configuracion.seguridad_armada = false) la base descarta los
#     eventos de presencia (CA-23.2): el aparato no toma fotos ni los envía.
#   * Armada, cada presencia nueva genera un evento 'presencia'. Mientras la
#     presencia siga, se toma como máximo una foto cada
#     seguridad_intervalo_foto_s segundos (CA-26.3).
#   * Las fotos y los eventos se guardan en una cola en la flash y se borran
#     solo cuando la base los recibió. Sin red se conservan y se reenvían con
#     su ocurrido_en original (RNF-17). Si la flash se llena, se descartan las
#     fotos más viejas: así nunca deja de tomar fotos nuevas.
#
# Se prueba en la PC (tests/test_firmware_seguridad.py).
# ============================================================

import json
import os
import time

FUERA_DE_RANGO = 999       # lo devuelve Ultrasonico.medir() cuando no hay nada al frente

if hasattr(time, "ticks_ms"):
    ticks_ms, ticks_diff = time.ticks_ms, time.ticks_diff
else:
    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b

INTERVALO_FOTO_S = 30       # valor por defecto de la base


class Vigilancia:
    def __init__(self, distancia_disparo_cm=20):
        self.distancia_disparo_cm = distancia_disparo_cm
        self.armada = False
        self.intervalo_s = INTERVALO_FOTO_S
        self.en_presencia = False
        self.ultima_foto = None         # ticks_ms de la última foto
        self.ultima_distancia = None

    def aplicar_config(self, armada, intervalo_s):
        """Devuelve True si cambió algo."""
        armada = bool(armada)
        try:
            intervalo_s = int(intervalo_s)
        except (TypeError, ValueError):
            intervalo_s = self.intervalo_s
        if intervalo_s <= 0:
            intervalo_s = self.intervalo_s
        cambio = (armada, intervalo_s) != (self.armada, self.intervalo_s)
        self.armada, self.intervalo_s = armada, intervalo_s
        if not armada:
            self.en_presencia = False
        return cambio

    def hay_presencia(self, distancia):
        return distancia is not None and distancia != FUERA_DE_RANGO and distancia < self.distancia_disparo_cm

    def al_medir(self, distancia, ahora_ms=None):
        """Decide qué hacer con una medición.
        None     -> nada
        'evento' -> presencia nueva, sin foto (aún no pasa el intervalo)
        'foto'   -> presencia con foto de evidencia"""
        self.ultima_distancia = distancia
        if ahora_ms is None:
            ahora_ms = ticks_ms()
        if not self.hay_presencia(distancia):
            self.en_presencia = False
            return None
        if not self.armada:
            return None
        nueva = not self.en_presencia
        self.en_presencia = True
        if self.ultima_foto is None or ticks_diff(ahora_ms, self.ultima_foto) >= self.intervalo_s * 1000:
            self.ultima_foto = ahora_ms
            return "foto"
        return "evento" if nueva else None


def _unir(carpeta, nombre):
    return carpeta.rstrip("/") + "/" + nombre


def _existe(ruta):
    try:
        os.stat(ruta)
        return True
    except OSError:
        return False


class Cola:
    """Eventos (con o sin foto) que todavía no llegan a la base, guardados en la flash.

    Cada elemento: {"tipo", "ocurrido_en", "descripcion", "foto", "subida"}.
    "foto" es el nombre del archivo dentro de la carpeta (o None)."""

    def __init__(self, carpeta="pendientes", espacio_libre=None, max_elementos=40):
        self.carpeta = carpeta
        self.indice = _unir(carpeta, "cola.json")
        self.max_elementos = max_elementos
        self._espacio_libre = espacio_libre or self._statvfs
        if not _existe(carpeta):
            os.mkdir(carpeta)
        self.elementos = self._cargar()
        self._contador = 0

    def _statvfs(self):
        st = os.statvfs(self.carpeta)
        return st[0] * st[3]

    def _cargar(self):
        try:
            with open(self.indice) as f:
                elementos = json.load(f)
        except (OSError, ValueError):
            return []
        # Descarta referencias a fotos que ya no existen (p. ej. un corte de luz al escribir).
        return [e for e in elementos if not e.get("foto") or _existe(_unir(self.carpeta, e["foto"]))]

    def _guardar(self):
        temporal = self.indice + ".tmp"
        with open(temporal, "w") as f:
            json.dump(self.elementos, f)
        try:
            os.remove(self.indice)
        except OSError:
            pass
        os.rename(temporal, self.indice)

    def __len__(self):
        return len(self.elementos)

    def fotos_pendientes(self):
        return sum(1 for e in self.elementos if e.get("foto"))

    def ruta(self, elemento):
        return _unir(self.carpeta, elemento["foto"])

    def _borrar_foto(self, elemento):
        if elemento.get("foto"):
            try:
                os.remove(self.ruta(elemento))
            except OSError:
                pass

    def _descartar_foto_mas_vieja(self):
        for e in self.elementos:
            if e.get("foto"):
                self._borrar_foto(e)
                e["foto"] = None          # el evento se conserva, solo pierde la foto
                return True
        return False

    def nombre_foto(self, sello):
        """Nombre único para una foto nueva: <sello>-<n>.png."""
        while True:
            self._contador += 1
            nombre = "%s-%d.png" % (sello, self._contador)
            if not _existe(_unir(self.carpeta, nombre)):
                return nombre

    def hacer_espacio(self, bytes_necesarios, margen=20000):
        """Borra las fotos más viejas hasta que quepa una nueva. False si no se pudo."""
        while self._espacio_libre() < bytes_necesarios + margen:
            if not self._descartar_foto_mas_vieja():
                return False
            self._guardar()
        return True

    def agregar(self, tipo, ocurrido_en, descripcion=None, foto=None):
        while len(self.elementos) >= self.max_elementos:
            self._borrar_foto(self.elementos.pop(0))
        self.elementos.append({"tipo": tipo, "ocurrido_en": ocurrido_en, "descripcion": descripcion,
                               "foto": foto, "subida": False})
        self._guardar()

    def primero(self):
        return self.elementos[0] if self.elementos else None

    def marcar_subida(self, elemento):
        elemento["subida"] = True
        self._guardar()

    def quitar(self, elemento):
        self._borrar_foto(elemento)
        self.elementos.remove(elemento)
        self._guardar()
