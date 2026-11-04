"""Componentes reutilizables: insignias, avisos, marco desplazable, tablas y estados."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable, Sequence

from app.ui.estilos import COLORES

# Cada tono lleva icono/texto además del color (no depender solo del color).
TONOS = {
    "info": (COLORES["turquesa_suave"], COLORES["petroleo_oscuro"], "ℹ"),
    "exito": (COLORES["exito_suave"], COLORES["exito"], "✔"),
    "aviso": (COLORES["aviso_suave"], COLORES["aviso"], "⚠"),
    "critico": (COLORES["critico_suave"], COLORES["critico"], "⛔"),
    "neutro": (COLORES["neutro_suave"], COLORES["texto_suave"], "•"),
}


class Insignia(tk.Label):
    """Etiqueta con fondo de color, icono y texto (accesible sin color)."""

    def __init__(self, padre, texto: str = "", tono: str = "neutro", **kw):
        super().__init__(padre, padx=8, pady=2, font=("Segoe UI", 9, "bold"), **kw)
        self.cambiar(texto, tono)

    def cambiar(self, texto: str, tono: str = "neutro") -> None:
        fondo, frente, icono = TONOS.get(tono, TONOS["neutro"])
        self.configure(text=f"{icono} {texto}", bg=fondo, fg=frente)


class Aviso(tk.Frame):
    """Banda de aviso con icono y mensaje; se oculta con ocultar()."""

    def __init__(self, padre, **kw):
        super().__init__(padre, bd=0, **kw)
        self._etiqueta = tk.Label(self, anchor="w", justify="left", padx=12, pady=8,
                                  font=("Segoe UI", 10))
        self._etiqueta.pack(fill="x")
        self._visible = False
        self._pack_opciones: dict = {}

    def mostrar(self, texto: str, tono: str = "info", **pack) -> None:
        fondo, frente, icono = TONOS.get(tono, TONOS["info"])
        self.configure(bg=fondo)
        self._etiqueta.configure(text=f"{icono}  {texto}", bg=fondo, fg=frente,
                                 font=("Segoe UI", 10, "bold" if tono == "critico" else "normal"))
        self._etiqueta.bind("<Configure>", lambda e: self._etiqueta.configure(wraplength=max(e.width - 30, 200)))
        if not self._visible:
            self.pack(fill="x", pady=(0, 8), **(pack or self._pack_opciones))
            self._visible = True

    def ocultar(self) -> None:
        if self._visible:
            self.pack_forget()
            self._visible = False


class MarcoDesplazable(ttk.Frame):
    """Contenedor con barra vertical y rueda del ratón. Use .interior para los hijos."""

    def __init__(self, padre, fondo: str = COLORES["fondo"], **kw):
        super().__init__(padre, **kw)
        self.lienzo = tk.Canvas(self, bg=fondo, highlightthickness=0, bd=0)
        self.barra = ttk.Scrollbar(self, orient="vertical", command=self.lienzo.yview)
        self.interior = ttk.Frame(self.lienzo)
        self._ventana = self.lienzo.create_window((0, 0), window=self.interior, anchor="nw")
        self.lienzo.configure(yscrollcommand=self.barra.set)
        self.lienzo.pack(side="left", fill="both", expand=True)
        self.barra.pack(side="right", fill="y")
        self.interior.bind("<Configure>", lambda e: self.lienzo.configure(scrollregion=self.lienzo.bbox("all")))
        self.lienzo.bind("<Configure>", lambda e: self.lienzo.itemconfigure(self._ventana, width=e.width))
        self.lienzo.bind("<Enter>", lambda e: self._rueda(True))
        self.lienzo.bind("<Leave>", lambda e: self._rueda(False))

    def _rueda(self, activar: bool) -> None:
        if activar:
            self.lienzo.bind_all("<MouseWheel>", self._al_rodar)
            self.lienzo.bind_all("<Button-4>", lambda e: self.lienzo.yview_scroll(-3, "units"))
            self.lienzo.bind_all("<Button-5>", lambda e: self.lienzo.yview_scroll(3, "units"))
        else:
            self.lienzo.unbind_all("<MouseWheel>")
            self.lienzo.unbind_all("<Button-4>")
            self.lienzo.unbind_all("<Button-5>")

    def _al_rodar(self, evento) -> None:
        if self.lienzo.winfo_exists():
            self.lienzo.yview_scroll(int(-evento.delta / 120) or (-1 if evento.delta > 0 else 1), "units")

    def arriba(self) -> None:
        self.lienzo.yview_moveto(0)


class Tabla(ttk.Frame):
    """Treeview con encabezados y barra de desplazamiento."""

    def __init__(self, padre, columnas: Sequence[tuple[str, str, int]], alto: int = 12,
                 al_doble_clic: Callable[[str], None] | None = None, **kw):
        super().__init__(padre, **kw)
        ids = [c[0] for c in columnas]
        self.arbol = ttk.Treeview(self, columns=ids, show="headings", height=alto, selectmode="browse")
        for clave, titulo, ancho in columnas:
            self.arbol.heading(clave, text=titulo, anchor="w")
            self.arbol.column(clave, width=ancho, anchor="w", stretch=True)
        barra = ttk.Scrollbar(self, orient="vertical", command=self.arbol.yview)
        barra_h = ttk.Scrollbar(self, orient="horizontal", command=self.arbol.xview)
        self.arbol.configure(yscrollcommand=barra.set, xscrollcommand=barra_h.set)
        self.arbol.grid(row=0, column=0, sticky="nsew")
        barra.grid(row=0, column=1, sticky="ns")
        barra_h.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.arbol.tag_configure("critica", foreground=COLORES["critico"])
        self.arbol.tag_configure("aviso", foreground=COLORES["aviso"])
        if al_doble_clic:
            self.arbol.bind("<Double-1>", lambda e: (s := self.seleccion()) and al_doble_clic(s))

    def llenar(self, filas: Iterable[tuple[str, Sequence, tuple[str, ...]]]) -> None:
        self.arbol.delete(*self.arbol.get_children())
        for iid, valores, etiquetas in filas:
            self.arbol.insert("", "end", iid=iid, values=list(valores), tags=etiquetas)

    def seleccion(self) -> str | None:
        sel = self.arbol.selection()
        return sel[0] if sel else None


class EstadoVista(ttk.Frame):
    """Muestra 'Cargando…', 'vacío' o 'error' en lugar de contenido."""

    def __init__(self, padre, **kw):
        super().__init__(padre, **kw)
        self._etiqueta = ttk.Label(self, style="Suave.TLabel", anchor="center", justify="center")
        self._etiqueta.pack(fill="both", expand=True, pady=24)

    def cargando(self, texto: str = "Cargando…") -> None:
        self._etiqueta.configure(text=f"⏳  {texto}", foreground=COLORES["texto_suave"])

    def vacio(self, texto: str) -> None:
        self._etiqueta.configure(text=f"∅  {texto}", foreground=COLORES["texto_suave"])

    def error(self, texto: str) -> None:
        self._etiqueta.configure(text=f"⛔  {texto}", foreground=COLORES["critico"])


def campo(padre, etiqueta: str, fila: int, ancho: int = 24, estilo_etiqueta: str = "Tarjeta.TLabel",
          valor: str = "", **kw_entry) -> ttk.Entry:
    ttk.Label(padre, text=etiqueta, style=estilo_etiqueta).grid(row=fila, column=0, sticky="w", padx=(0, 10), pady=4)
    entrada = ttk.Entry(padre, width=ancho, **kw_entry)
    if valor:
        entrada.insert(0, valor)
    entrada.grid(row=fila, column=1, sticky="we", pady=4)
    return entrada


def poner_texto(entrada: ttk.Entry, valor) -> None:
    estado = str(entrada.cget("state"))
    if estado == "disabled":
        entrada.configure(state="normal")
    entrada.delete(0, "end")
    if valor is not None:
        entrada.insert(0, f"{valor:g}" if isinstance(valor, float) else str(valor))
    if estado == "disabled":
        entrada.configure(state="disabled")


def habilitar(widgets: Iterable[tk.Widget], activo: bool) -> None:
    for w in widgets:
        try:
            if isinstance(w, ttk.Combobox):
                w.configure(state="readonly" if activo else "disabled")
            else:
                w.configure(state="normal" if activo else "disabled")
        except tk.TclError:
            pass
