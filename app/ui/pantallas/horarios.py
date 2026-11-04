"""Editor de horarios (móvil, seguridad y ventana de movimiento). Traslapes los rechaza la base."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.config.valores import MAX_SECUENCIAS_MOVIL
from app.errores import ErrorValidacion
from app.services import dominio
from app.ui.widgets import Tabla


class EditorHorarios(ttk.LabelFrame):
    def __init__(self, padre, pantalla, dispositivo_id: str, tipo: str, titulo: str, nota: str = ""):
        super().__init__(padre, text=titulo, padding=12)
        self.pantalla = pantalla
        self.dispositivo_id = dispositivo_id
        self.tipo = tipo
        self._horarios: list[dict] = []
        if nota:
            ttk.Label(self, text=nota, style="TarjetaSuave.TLabel", wraplength=640, justify="left").pack(anchor="w")
        self.tabla = Tabla(self, [("horario", "Horario (hora de Costa Rica)", 420), ("estado", "Estado", 90)], alto=4)
        self.tabla.pack(fill="x", pady=6)

        formulario = ttk.Frame(self, style="Tarjeta.TFrame")
        formulario.pack(fill="x")
        self.dias = []
        for i, nombre in enumerate(dominio.NOMBRES_DIAS):
            var = tk.BooleanVar(value=False)
            ttk.Checkbutton(formulario, text=nombre, variable=var, style="Tarjeta.TCheckbutton").grid(row=0, column=i, padx=2)
            self.dias.append(var)
        fila = ttk.Frame(self, style="Tarjeta.TFrame")
        fila.pack(fill="x", pady=(6, 0))
        ttk.Label(fila, text="Inicio (HH:MM)", style="Tarjeta.TLabel").pack(side="left")
        self.inicio = ttk.Entry(fila, width=7)
        self.inicio.pack(side="left", padx=(4, 12))
        ttk.Label(fila, text="Fin (HH:MM)", style="Tarjeta.TLabel").pack(side="left")
        self.fin = ttk.Entry(fila, width=7)
        self.fin.pack(side="left", padx=(4, 12))
        self.secuencia = None
        if tipo == "movil":
            ttk.Label(fila, text="Secuencia", style="Tarjeta.TLabel").pack(side="left")
            self.secuencia = ttk.Spinbox(fila, from_=1, to=MAX_SECUENCIAS_MOVIL, width=4, state="readonly")
            self.secuencia.set(1)
            self.secuencia.pack(side="left", padx=(4, 12))
        self.btn_agregar = ttk.Button(fila, text="Agregar", style="Primario.TButton", command=self._agregar)
        self.btn_agregar.pack(side="left")
        self.btn_alternar = ttk.Button(fila, text="Activar/Desactivar", command=self._alternar)
        self.btn_alternar.pack(side="left", padx=6)
        self.btn_borrar = ttk.Button(fila, text="Borrar", command=self._borrar)
        self.btn_borrar.pack(side="left")
        self._controles = [self.btn_agregar, self.btn_alternar, self.btn_borrar, self.inicio, self.fin]

    def permitir(self, puede: bool) -> None:
        for w in self._controles:
            w.configure(state="normal" if puede else "disabled")

    def cargar(self) -> None:
        def ok(filas):
            self._horarios = filas
            self.tabla.llenar([(h["id"], (dominio.describir_horario(h), "Activo" if h["activo"] else "Inactivo"), ())
                               for h in filas])
            if not filas:
                self.tabla.llenar([("vacio", ("No hay horarios guardados.", ""), ())])
        self.pantalla.tarea(lambda: self.pantalla.servicios.dispositivos.horarios(self.dispositivo_id, self.tipo), ok)

    def _agregar(self) -> None:
        try:
            dias, inicio, fin = dominio.validar_horario([i for i, v in enumerate(self.dias) if v.get()],
                                                        self.inicio.get(), self.fin.get())
        except ErrorValidacion as e:
            self.pantalla.mostrar_error(e)
            return
        datos = {"dispositivo_id": self.dispositivo_id, "tipo": self.tipo, "dias": dias,
                 "hora_inicio": inicio, "hora_fin": fin, "activo": True}
        if self.secuencia is not None:
            datos["secuencia"] = int(self.secuencia.get())
        self.pantalla.tarea(lambda: self.pantalla.servicios.dispositivos.crear_horario(datos),
                            lambda _: self.cargar(), boton=self.btn_agregar, exito="Horario guardado.")

    def _seleccionado(self) -> dict | None:
        iid = self.tabla.seleccion()
        h = next((h for h in self._horarios if h["id"] == iid), None)
        if not h:
            self.pantalla.mostrar_error(ErrorValidacion("Seleccione un horario."))
        return h

    def _alternar(self) -> None:
        h = self._seleccionado()
        if h:
            self.pantalla.tarea(lambda: self.pantalla.servicios.dispositivos.activar_horario(h["id"], not h["activo"]),
                                lambda _: self.cargar(), exito="Horario actualizado.")

    def _borrar(self) -> None:
        h = self._seleccionado()
        if h and self.pantalla.confirmar("Borrar horario", f"¿Borrar el horario {dominio.describir_horario(h)}?"):
            self.pantalla.tarea(lambda: self.pantalla.servicios.dispositivos.borrar_horario(h["id"]),
                                lambda _: self.cargar(), exito="Horario borrado.")
