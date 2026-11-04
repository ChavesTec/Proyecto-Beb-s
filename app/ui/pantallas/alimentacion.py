"""Cronómetro de toma, cantidad ingerida y recordatorios (HU-34 a HU-36)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.config.zona import ahora_utc, formato_local, parsear_fecha_iso
from app.errores import ErrorValidacion
from app.services import dominio
from app.ui.base import Pantalla
from app.ui.widgets import Aviso, Tabla


class PantallaAlimentacion(Pantalla):
    titulo = "Alimentación"

    def __init__(self, padre, app):
        super().__init__(padre, app)
        ttk.Label(self, text="Alimentación", style="Titulo.TLabel").pack(anchor="w")
        self.aviso = Aviso(self)
        cuerpo = ttk.Frame(self)
        cuerpo.pack(fill="both", expand=True, pady=(10, 0))

        izquierda = ttk.Frame(cuerpo)
        izquierda.pack(side="left", fill="both", expand=True)
        crono = ttk.LabelFrame(izquierda, text="Cronómetro de toma", padding=14)
        crono.pack(fill="x")
        self.lbl_reloj = ttk.Label(crono, text="00:00:00", style="Grande.TLabel")
        self.lbl_reloj.grid(row=0, column=0, rowspan=2, padx=(0, 20))
        self.lbl_estado = ttk.Label(crono, text="", style="TarjetaSuave.TLabel")
        self.lbl_estado.grid(row=0, column=1, columnspan=2, sticky="w")
        ttk.Label(crono, text="Biberón (opcional)", style="Tarjeta.TLabel").grid(row=1, column=1, sticky="w")
        self.biberon = ttk.Combobox(crono, state="readonly", width=24)
        self.biberon.grid(row=1, column=2, sticky="w")
        self.btn_inicio = ttk.Button(crono, text="▶ Inicio", style="GrandePrimario.TButton", command=self._iniciar)
        self.btn_inicio.grid(row=2, column=0, pady=(12, 0), sticky="w")
        self.btn_parada = ttk.Button(crono, text="■ Parada", style="GrandePeligro.TButton", command=self._detener)
        self.btn_parada.grid(row=2, column=1, pady=(12, 0), sticky="w")

        tomas = ttk.LabelFrame(izquierda, text="Tomas registradas", padding=12)
        tomas.pack(fill="both", expand=True, pady=(12, 0))
        self.tabla = Tabla(tomas, [("inicio", "Inicio", 140), ("fin", "Fin", 140), ("duracion", "Duración", 90),
                                   ("ml", "Cantidad (ml)", 100)], alto=10)
        self.tabla.pack(fill="both", expand=True)
        fila = ttk.Frame(tomas, style="Tarjeta.TFrame")
        fila.pack(fill="x", pady=(8, 0))
        ttk.Label(fila, text="Cantidad ingerida (ml) de la toma seleccionada:", style="Tarjeta.TLabel").pack(side="left")
        self.ml = ttk.Entry(fila, width=8)
        self.ml.pack(side="left", padx=6)
        self.btn_ml = ttk.Button(fila, text="Guardar cantidad", style="Primario.TButton", command=self._guardar_ml)
        self.btn_ml.pack(side="left")

        derecha = ttk.LabelFrame(cuerpo, text="Recordatorios por Telegram (HU-36)", padding=12)
        derecha.pack(side="left", fill="y", padx=(16, 0))
        self.var_tipo = tk.StringVar(value="intervalo")
        ttk.Radiobutton(derecha, text="Cada N minutos desde la última toma", value="intervalo",
                        variable=self.var_tipo, style="Tarjeta.TRadiobutton").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(derecha, text="Todos los días a una hora fija", value="hora_fija",
                        variable=self.var_tipo, style="Tarjeta.TRadiobutton").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(derecha, text="Minutos", style="Tarjeta.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.intervalo = ttk.Entry(derecha, width=8)
        self.intervalo.insert(0, "180")
        self.intervalo.grid(row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Label(derecha, text="Hora (HH:MM)", style="Tarjeta.TLabel").grid(row=3, column=0, sticky="w")
        self.hora = ttk.Entry(derecha, width=8)
        self.hora.grid(row=3, column=1, sticky="w")
        self.btn_rec = ttk.Button(derecha, text="Agregar recordatorio", style="Primario.TButton", command=self._agregar_rec)
        self.btn_rec.grid(row=4, column=0, columnspan=2, sticky="w", pady=8)
        self.tabla_rec = Tabla(derecha, [("desc", "Recordatorio", 220), ("estado", "Estado", 80),
                                         ("ultimo", "Último aviso creado", 130)], alto=6)
        self.tabla_rec.grid(row=5, column=0, columnspan=2, sticky="nsew")
        fila = ttk.Frame(derecha, style="Tarjeta.TFrame")
        fila.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(fila, text="Activar/Desactivar", command=self._alternar_rec).pack(side="left")
        ttk.Button(fila, text="Borrar", command=self._borrar_rec).pack(side="left", padx=6)
        ttk.Label(derecha, text="«Último aviso creado» indica que la base generó la alerta del recordatorio.\n"
                                "Su entrega por Telegram se ve en «Alertas» (estado de envío).",
                  style="TarjetaSuave.TLabel", justify="left").grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self._en_curso: dict | None = None
        self._tomas: list[dict] = []
        self._recordatorios: list[dict] = []
        self._biberones: list[str | None] = [None]
        self._id_reloj = None
        self._perfil_cargado = None

    # ---------------------------------------------------------------
    def al_mostrar(self, **_):
        self._cargar()
        self._tic()

    def al_ocultar(self):
        if self._id_reloj:
            self.after_cancel(self._id_reloj)
            self._id_reloj = None

    def al_actualizar(self):
        if self.perfil_id != self._perfil_cargado:
            self._cargar()

    def al_cambio(self, tabla, tipo, registro):
        pass

    def _cargar(self):
        perfil = self.perfil_id
        self._perfil_cargado = perfil
        inst = self.servicios.instantanea
        biberones = [d for d in inst.dispositivos if d["tipo"] == "biberon" and (not perfil or d.get("perfil_id") == perfil)]
        self._biberones = [None] + [d["id"] for d in biberones]
        self.biberon.configure(values=["Ninguno"] + [d.get("nombre") or d["codigo"] for d in biberones])
        self.biberon.current(1 if biberones else 0)
        if not perfil:
            self.aviso.mostrar("Seleccione un perfil en la parte superior para registrar tomas y recordatorios.", "info")
            for b in (self.btn_inicio, self.btn_parada, self.btn_ml, self.btn_rec):
                b.configure(state="disabled")
            self.tabla.llenar([])
            self.tabla_rec.llenar([])
            self._en_curso = None
            return
        puede = self.servicios.puede_controlar_perfil(perfil)
        if puede:
            self.aviso.ocultar()
        else:
            self.aviso.mostrar("Tiene acceso de solo lectura a este perfil: no puede registrar tomas ni recordatorios.", "aviso")
        for b in (self.btn_ml, self.btn_rec):
            b.configure(state="normal" if puede else "disabled")

        def ok(datos):
            if perfil != self.perfil_id:
                return
            self._tomas, self._en_curso, self._recordatorios = datos
            self._pintar(puede)

        alim = self.servicios.alimentacion
        self.tarea(lambda: (alim.tomas(perfil), alim.toma_en_curso(perfil), alim.recordatorios(perfil)), ok)

    def _pintar(self, puede: bool):
        en_curso = self._en_curso is not None
        self.btn_inicio.configure(state="normal" if puede and not en_curso else "disabled")
        self.btn_parada.configure(state="normal" if puede and en_curso else "disabled")
        self.lbl_estado.configure(text=f"Toma en curso desde {formato_local(self._en_curso['inicio'], True)}"
                                  if en_curso else "Sin toma en curso.")
        self.tabla.llenar([(str(t["id"]), (formato_local(t["inicio"], True), formato_local(t.get("fin"), True, "en curso"),
                                           dominio.formato_duracion(t.get("duracion_s")),
                                           "" if t.get("cantidad_ml") is None else t["cantidad_ml"]), ())
                           for t in self._tomas] or [("vacio", ("Sin tomas registradas", "", "", ""), ())])
        filas = []
        for r in self._recordatorios:
            desc = (f"Cada {r['intervalo_min']} min desde la última toma" if r["tipo"] == "intervalo"
                    else f"Todos los días a las {str(r['hora'])[:5]}")
            filas.append((r["id"], (desc, "Activo" if r["activo"] else "Inactivo", formato_local(r.get("ultimo_envio_en"))), ()))
        self.tabla_rec.llenar(filas or [("vacio", ("Sin recordatorios", "", ""), ())])

    def _tic(self):
        if self._en_curso:
            inicio = parsear_fecha_iso(self._en_curso["inicio"])
            self.lbl_reloj.configure(text=dominio.formato_duracion((ahora_utc() - inicio).total_seconds()))
        else:
            self.lbl_reloj.configure(text="00:00:00")
        self._id_reloj = self.after(1000, self._tic)

    def _iniciar(self):
        perfil = self.perfil_id
        i = self.biberon.current()
        biberon = self._biberones[i] if 0 <= i < len(self._biberones) else None
        self.tarea(lambda: self.servicios.alimentacion.iniciar_toma(perfil, biberon), lambda _: self._cargar(),
                   boton=self.btn_inicio, exito="Toma iniciada.")

    def _detener(self):
        toma = self._en_curso
        if not toma:
            return
        # Si el reloj del PC va atrasado respecto al servidor, fin no puede quedar antes del inicio.
        fin = max(ahora_utc(), parsear_fecha_iso(toma["inicio"]))
        self.tarea(lambda: self.servicios.alimentacion.finalizar_toma(toma["id"], fin), lambda _: self._cargar(),
                   boton=self.btn_parada, exito="Toma guardada con inicio, fin y duración.")

    def _guardar_ml(self):
        iid = self.tabla.seleccion()
        toma = next((t for t in self._tomas if str(t["id"]) == iid), None)
        try:
            if not toma:
                raise ErrorValidacion("Seleccione una toma de la lista.")
            if not toma.get("fin"):
                raise ErrorValidacion("Solo se puede registrar la cantidad de una toma finalizada.")
            cantidad = dominio.validar_cantidad_ml(self.ml.get())
        except ErrorValidacion as e:
            self.mostrar_error(e)
            return
        self.tarea(lambda: self.servicios.alimentacion.registrar_cantidad(toma["id"], cantidad),
                   lambda _: (self.ml.delete(0, "end"), self._cargar()), boton=self.btn_ml, exito="Cantidad guardada.")

    def _agregar_rec(self):
        tipo = self.var_tipo.get()
        try:
            if tipo == "intervalo":
                minutos = dominio.validar_entero(self.intervalo.get(), "el intervalo", minimo=1, maximo=24 * 60)
                hora = None
            else:
                minutos = None
                hora = dominio.parsear_hora(self.hora.get()).strftime("%H:%M")
        except ErrorValidacion as e:
            self.mostrar_error(e)
            return
        perfil = self.perfil_id
        self.tarea(lambda: self.servicios.alimentacion.crear_recordatorio(perfil, tipo, minutos, hora),
                   lambda _: self._cargar(), boton=self.btn_rec, exito="Recordatorio creado.")

    def _rec_sel(self):
        iid = self.tabla_rec.seleccion()
        r = next((r for r in self._recordatorios if r["id"] == iid), None)
        if not r:
            self.mostrar_error(ErrorValidacion("Seleccione un recordatorio."))
        return r

    def _alternar_rec(self):
        r = self._rec_sel()
        if r:
            self.tarea(lambda: self.servicios.alimentacion.activar_recordatorio(r["id"], not r["activo"]),
                       lambda _: self._cargar(), exito="Recordatorio actualizado.")

    def _borrar_rec(self):
        r = self._rec_sel()
        if r and self.confirmar("Borrar recordatorio", "¿Borrar este recordatorio?"):
            self.tarea(lambda: self.servicios.alimentacion.borrar_recordatorio(r["id"]), lambda _: self._cargar(),
                       exito="Recordatorio borrado.")
