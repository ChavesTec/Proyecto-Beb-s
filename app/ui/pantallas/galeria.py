"""Galería de capturas (HU-28): v_galeria + URLs firmadas de corta duración del bucket privado."""
from __future__ import annotations

import io
import tkinter as tk
from tkinter import ttk

import httpx

from app.config.valores import MAX_FOTO_BYTES
from app.errores import ErrorApp, ErrorValidacion
from app.repositories.historial import Pagina
from app.ui.base import Pantalla
from app.ui.estilos import COLORES
from app.ui.pantallas.filtros import SelectorFechas, SelectorPerfilDispositivo
from app.ui.widgets import EstadoVista, MarcoDesplazable

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover - Pillow es dependencia, pero la galería degrada sin él.
    Image = ImageTk = None

MENSAJE_VACIO = "No hay capturas para el rango seleccionado"
TAMANO_PAGINA_GALERIA = 24
MINIATURA = (220, 165)


def descargar_firmada(servicios, ruta: str) -> bytes:
    """Pide una URL firmada (RLS decide si hay acceso) y descarga la foto con ella."""
    url = servicios.historial.url_firmada("capturas", ruta)
    try:
        r = httpx.get(url, timeout=15)
    except httpx.HTTPError as error:
        raise ErrorApp("No se pudo descargar la foto (sin conexión).", "sin_conexion") from error
    if r.status_code != 200:
        raise ErrorApp("La foto no está disponible o la URL firmada expiró.", "no_encontrado")
    if len(r.content) > MAX_FOTO_BYTES * 2:
        raise ErrorApp("La foto supera el tamaño esperado y no se mostrará.", "validacion")
    return r.content


class PantallaGaleria(Pantalla):
    titulo = "Galería"

    def __init__(self, padre, app):
        super().__init__(padre, app)
        ttk.Label(self, text="Galería de capturas", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(self, text="Fotos de evidencia de la seguridad, de la más reciente a la más antigua. "
                             "Se ven solo con acceso al perfil del evento.", style="Suave.TLabel").pack(anchor="w")
        filtros = ttk.LabelFrame(self, text="Filtros", padding=12)
        filtros.pack(fill="x", pady=(10, 8))
        self.sel = SelectorPerfilDispositivo(filtros, self.servicios, 0, 0)
        self.fechas = SelectorFechas(filtros, 0, 2, dias_atras=30)
        self.btn = ttk.Button(filtros, text="Aplicar filtros", style="Primario.TButton", command=self.buscar)
        self.btn.grid(row=1, column=4, padx=6)
        self.estado = EstadoVista(self)
        self.estado.pack(fill="x")
        self.marco = MarcoDesplazable(self)
        self.marco.pack(fill="both", expand=True)
        pag = ttk.Frame(self)
        pag.pack(fill="x", pady=(6, 0))
        self.btn_ant = ttk.Button(pag, text="← Más recientes", command=lambda: self._ir(-1))
        self.btn_ant.pack(side="left")
        self.lbl = ttk.Label(pag)
        self.lbl.pack(side="left", padx=12)
        self.btn_sig = ttk.Button(pag, text="Más antiguas →", command=lambda: self._ir(1))
        self.btn_sig.pack(side="left")
        self._imagenes: list = []  # Referencias para que Tk no libere las imágenes.
        self._pagina = 0
        self._consulta = None
        self._generacion = 0

    def al_mostrar(self, dispositivo_id: str | None = None, **_):
        self.sel.llenar(perfil_preferido=self.perfil_id, dispositivo_preferido=dispositivo_id)
        if dispositivo_id:
            self.sel.fijar_dispositivo(dispositivo_id)
        self.buscar()

    def al_actualizar(self):
        self.sel.llenar()

    def al_cambio(self, tabla, tipo, registro):
        pass

    def buscar(self):
        try:
            desde, hasta = self.fechas.rango_utc()
        except ErrorValidacion as e:
            self.mostrar_error(e)
            return
        self._consulta = (self.sel.perfil_id(), self.sel.dispositivo_id(), desde, hasta)
        self._pagina = 0
        self._cargar()

    def _ir(self, delta):
        self._pagina = max(0, self._pagina + delta)
        self._cargar()

    def _cargar(self):
        perfil, disp, desde, hasta = self._consulta
        pagina = self._pagina
        self.estado.cargando("Cargando capturas…")
        self.tarea(lambda: self.servicios.historial.galeria(perfil, disp, desde, hasta, pagina, TAMANO_PAGINA_GALERIA),
                   self._mostrar, al_fallar=lambda e: (self.estado.error(e.mensaje), self.mostrar_error(e)),
                   boton=self.btn)

    def _mostrar(self, pagina: Pagina):
        self._generacion += 1
        generacion = self._generacion
        for hijo in self.marco.interior.winfo_children():
            hijo.destroy()
        self._imagenes.clear()
        total = pagina.total or 0
        self.lbl.configure(text=f"Página {pagina.pagina + 1} de {pagina.paginas} · {total} capturas")
        self.btn_ant.configure(state="normal" if pagina.pagina > 0 else "disabled")
        self.btn_sig.configure(state="normal" if total > (pagina.pagina + 1) * TAMANO_PAGINA_GALERIA else "disabled")
        if not pagina.filas:
            self.estado.vacio(MENSAJE_VACIO)
            return
        self.estado.vacio(f"{total} captura(s). Haga clic en una foto para ampliarla.")
        if Image is None:
            self.estado.error("Falta la biblioteca Pillow para mostrar fotos JPEG (pip install Pillow).")
        inst = self.servicios.instantanea
        columnas = 4
        for i in range(columnas):
            self.marco.interior.columnconfigure(i, weight=1, uniform="fotos")
        for i, c in enumerate(pagina.filas):
            celda = ttk.Frame(self.marco.interior, style="Caja.TFrame", padding=8)
            celda.grid(row=i // columnas, column=i % columnas, sticky="nsew", padx=6, pady=6)
            foto = tk.Label(celda, text="⏳", bg=COLORES["neutro_suave"], width=28, height=9, cursor="hand2")
            foto.pack(fill="x")
            d = inst.dispositivo(c["dispositivo_id"])
            nombre = (d.get("nombre") or d["codigo"]) if d else "Dispositivo"
            evento = {"presencia": "Presencia", "puerta": "Puerta"}.get(c["tipo_evento"], c["tipo_evento"])
            ttk.Label(celda, text=f"{c['fecha_hora']}", style="Tarjeta.TLabel").pack(anchor="w", pady=(6, 0))
            ttk.Label(celda, text=f"{evento} · {nombre} · {inst.nombre_perfil(c.get('perfil_id'))}",
                      style="TarjetaSuave.TLabel").pack(anchor="w")
            foto.bind("<Button-1>", lambda e, ruta=c["foto_path"], titulo=f"{evento} — {c['fecha_hora']}": self._ampliar(ruta, titulo))
            if Image is not None:
                self._cargar_miniatura(foto, c["foto_path"], generacion)

    def _cargar_miniatura(self, etiqueta: tk.Label, ruta: str, generacion: int):
        def ok(contenido: bytes):
            if generacion != self._generacion or not etiqueta.winfo_exists():
                return
            try:
                imagen = Image.open(io.BytesIO(contenido))
                imagen.thumbnail(MINIATURA)
                foto = ImageTk.PhotoImage(imagen)
            except Exception:
                etiqueta.configure(text="Imagen no válida")
                return
            self._imagenes.append(foto)
            etiqueta.configure(image=foto, text="", width=MINIATURA[0], height=MINIATURA[1])

        def fallo(error: ErrorApp):
            if etiqueta.winfo_exists():
                etiqueta.configure(text=f"⛔ {error.mensaje}", wraplength=200)

        self.tarea(lambda: descargar_firmada(self.servicios, ruta), ok, al_fallar=fallo)

    def _ampliar(self, ruta: str, titulo: str):
        if Image is None:
            return
        ventana = tk.Toplevel(self)
        ventana.title(titulo)
        etiqueta = tk.Label(ventana, text="Cargando…", bg=COLORES["fondo"], padx=10, pady=10)
        etiqueta.pack()

        def ok(contenido):
            if not etiqueta.winfo_exists():
                return
            imagen = Image.open(io.BytesIO(contenido))
            foto = ImageTk.PhotoImage(imagen)
            etiqueta.configure(image=foto, text="")
            etiqueta.image = foto

        self.tarea(lambda: descargar_firmada(self.servicios, ruta), ok,
                   al_fallar=lambda e: etiqueta.winfo_exists() and etiqueta.configure(text=e.mensaje))
