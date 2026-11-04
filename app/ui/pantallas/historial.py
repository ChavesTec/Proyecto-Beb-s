"""Historial con filtros, páginas de 50 y exportación CSV (HU-39, HU-40)."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.config.valores import TAMANO_PAGINA, TIPOS_EVENTO
from app.config.zona import ahora_utc
from app.errores import ErrorValidacion
from app.repositories.historial import FiltroHistorial, Pagina
from app.services.exportacion import MENSAJE_SIN_DATOS, exportar_csv
from app.ui.base import Pantalla
from app.ui.pantallas.filtros import TODOS, SelectorFechas, SelectorPerfilDispositivo
from app.ui.widgets import EstadoVista, Tabla

MENSAJE_VACIO = "No hay registros para el rango seleccionado"


class PantallaHistorial(Pantalla):
    titulo = "Historial"

    def __init__(self, padre, app):
        super().__init__(padre, app)
        ttk.Label(self, text="Historial de eventos", style="Titulo.TLabel").pack(anchor="w")
        filtros = ttk.LabelFrame(self, text="Filtros", padding=12)
        filtros.pack(fill="x", pady=(10, 8))
        self.sel = SelectorPerfilDispositivo(filtros, self.servicios, 0, 0)
        ttk.Label(filtros, text="Tipo de evento", style="Tarjeta.TLabel").grid(row=0, column=2, sticky="w")
        self.tipo = ttk.Combobox(filtros, state="readonly", width=22, values=[TODOS] + list(TIPOS_EVENTO))
        self.tipo.set(TODOS)
        self.tipo.grid(row=1, column=2, sticky="w", padx=(0, 10))
        self.fechas = SelectorFechas(filtros, 0, 3)
        self.btn_buscar = ttk.Button(filtros, text="Aplicar filtros", style="Primario.TButton", command=self.buscar)
        self.btn_buscar.grid(row=1, column=5, padx=(6, 6))
        self.btn_csv = ttk.Button(filtros, text="Exportar CSV", command=self._exportar)
        self.btn_csv.grid(row=1, column=6)

        self.tabla = Tabla(self, [("fecha", "Fecha y hora (CR)", 150), ("perfil", "Perfil", 140),
                                  ("dispositivo", "Dispositivo", 150), ("tipo", "Tipo", 140), ("valor", "Valor", 80),
                                  ("unidad", "Unidad", 60), ("desc", "Descripción", 380)], alto=18)
        self.tabla.pack(fill="both", expand=True)
        self.estado = EstadoVista(self)

        paginacion = ttk.Frame(self)
        paginacion.pack(fill="x", pady=(8, 0))
        self.btn_ant = ttk.Button(paginacion, text="← Anterior", command=lambda: self._ir(-1))
        self.btn_ant.pack(side="left")
        self.lbl_pagina = ttk.Label(paginacion, text="")
        self.lbl_pagina.pack(side="left", padx=12)
        self.btn_sig = ttk.Button(paginacion, text="Siguiente →", command=lambda: self._ir(1))
        self.btn_sig.pack(side="left")
        self._filtro: FiltroHistorial | None = None
        self._pagina = 0
        self._total: int | None = None
        self._primera = True

    def al_mostrar(self, **_):
        self.sel.llenar(perfil_preferido=self.perfil_id)
        if self._primera:
            self._primera = False
            self.buscar()

    def al_actualizar(self):
        self.sel.llenar()

    def al_cambio(self, tabla, tipo, registro):
        pass  # El historial no se recarga solo: el usuario controla los filtros y la página.

    def _armar_filtro(self) -> FiltroHistorial:
        desde, hasta = self.fechas.rango_utc()
        i = self.tipo.current()
        return FiltroHistorial(perfil_id=self.sel.perfil_id(), dispositivo_id=self.sel.dispositivo_id(),
                               tipos=[TIPOS_EVENTO[i - 1]] if i > 0 else [], desde_utc=desde, hasta_utc=hasta)

    def buscar(self):
        try:
            self._filtro = self._armar_filtro()
        except ErrorValidacion as e:
            self.mostrar_error(e)
            return
        self._pagina = 0
        self._cargar()

    def _ir(self, delta: int):
        if self._filtro is None:
            return
        self._pagina = max(0, self._pagina + delta)
        self._cargar()

    def _cargar(self):
        filtro, pagina = self._filtro, self._pagina
        self.tabla.llenar([("cargando", ("Cargando…", "", "", "", "", "", ""), ())])
        # CA-39.2: un rango que empieza en el futuro no puede tener eventos.
        if filtro.desde_utc and filtro.desde_utc > ahora_utc():
            self._mostrar(Pagina(filas=[], total=0, pagina=0))
            return
        self.tarea(lambda: self.servicios.historial.pagina_historial(filtro, pagina), self._mostrar,
                   boton=self.btn_buscar)

    def _mostrar(self, pagina: Pagina):
        self._total = pagina.total
        if not pagina.filas:
            self.tabla.llenar([("vacio", ("", "", "", "", "", "", MENSAJE_VACIO), ())])
            self.lbl_pagina.configure(text=MENSAJE_VACIO)
            self.btn_ant.configure(state="disabled")
            self.btn_sig.configure(state="disabled")
            return
        self.tabla.llenar([(str(e["id"]), (e["fecha_hora"], e.get("perfil") or "Sin perfil", e["dispositivo"], e["tipo"],
                                            "" if e.get("valor") is None else e["valor"], e.get("unidad") or "",
                                            e.get("descripcion") or ""), ()) for e in pagina.filas])
        total = pagina.total if pagina.total is not None else "?"
        inicio = pagina.pagina * TAMANO_PAGINA + 1
        self.lbl_pagina.configure(text=f"Página {pagina.pagina + 1} de {pagina.paginas} · registros "
                                       f"{inicio}–{inicio + len(pagina.filas) - 1} de {total}")
        self.btn_ant.configure(state="normal" if pagina.pagina > 0 else "disabled")
        hay_mas = (pagina.total is None and len(pagina.filas) == TAMANO_PAGINA) or (
            pagina.total is not None and (pagina.pagina + 1) * TAMANO_PAGINA < pagina.total)
        self.btn_sig.configure(state="normal" if hay_mas else "disabled")

    def _exportar(self):
        """CA-40.1: exporta exactamente el filtro aplicado (todas sus páginas)."""
        try:
            filtro = self._armar_filtro()
        except ErrorValidacion as e:
            self.mostrar_error(e)
            return
        if self._filtro is None or filtro != self._filtro:
            if not messagebox.askyesno("Exportar CSV", "Los filtros del formulario cambiaron y aún no se aplican. "
                                                       "¿Aplicarlos y exportar ese resultado?", parent=self):
                return
            self._filtro = filtro
            self._pagina = 0
            self._cargar()
        elif self._total == 0:
            self.mostrar_error(ErrorValidacion(MENSAJE_SIN_DATOS), "Sin datos")
            return

        def obtenido(filas):
            if not filas:
                self.mostrar_error(ErrorValidacion(MENSAJE_SIN_DATOS), "Sin datos")
                return
            destino = filedialog.asksaveasfilename(parent=self, title="Guardar CSV", defaultextension=".csv",
                                                   initialfile="historial.csv", filetypes=[("CSV", "*.csv")])
            if not destino:
                return
            try:
                cantidad = exportar_csv(filas, Path(destino))
            except OSError as error:
                self.mostrar_error(ErrorValidacion(f"No se pudo escribir el archivo: {error.strerror or error}"))
                return
            self.app.notificar(f"CSV exportado: {cantidad} registros en {destino}", "exito")

        self.tarea(lambda: self.servicios.historial.todo_historial(filtro), obtenido, boton=self.btn_csv)
