"""Registro, asignación y lista de dispositivos (HU-04, HU-05, HU-06)."""
from __future__ import annotations

from tkinter import ttk

from app.config.valores import NOMBRES_TIPO, TIPOS_DISPOSITIVO
from app.config.zona import formato_local, hace_cuanto
from app.errores import ErrorValidacion
from app.services import dominio
from app.ui.base import Pantalla
from app.ui.widgets import EstadoVista, Tabla

SIN_ASIGNAR = "— Sin asignar —"
TODOS = "Todos los tipos"


class PantallaDispositivos(Pantalla):
    titulo = "Dispositivos"

    def __init__(self, padre, app):
        super().__init__(padre, app)
        ttk.Label(self, text="Dispositivos", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(self, text="Registre un dispositivo con el código impreso en él y asígnelo a un perfil. "
                             "Un dispositivo pertenece a un solo perfil a la vez.",
                  style="Suave.TLabel").pack(anchor="w", pady=(2, 12))

        registro = ttk.LabelFrame(self, text="Registrar dispositivo", padding=12)
        registro.pack(fill="x")
        ttk.Label(registro, text="Código", style="Tarjeta.TLabel").grid(row=0, column=0, sticky="w")
        self.codigo = ttk.Entry(registro, width=22)
        self.codigo.grid(row=0, column=1, padx=(6, 18))
        ttk.Label(registro, text="Nombre (opcional)", style="Tarjeta.TLabel").grid(row=0, column=2, sticky="w")
        self.nombre = ttk.Entry(registro, width=28)
        self.nombre.grid(row=0, column=3, padx=(6, 18))
        self.btn_registrar = ttk.Button(registro, text="Registrar", style="Primario.TButton", command=self._registrar)
        self.btn_registrar.grid(row=0, column=4)
        self.codigo.bind("<Return>", lambda e: self._registrar())

        barra = ttk.Frame(self)
        barra.pack(fill="x", pady=(16, 6))
        ttk.Label(barra, text="Tipo:").pack(side="left")
        self.filtro_tipo = ttk.Combobox(barra, state="readonly", width=24,
                                        values=[TODOS] + [NOMBRES_TIPO[t] for t in TIPOS_DISPOSITIVO])
        self.filtro_tipo.set(TODOS)
        self.filtro_tipo.pack(side="left", padx=6)
        self.filtro_tipo.bind("<<ComboboxSelected>>", lambda e: self._pintar())
        import tkinter as tk

        self.var_sin_asignar = tk.BooleanVar(value=False)
        self.solo_sin_asignar = ttk.Checkbutton(barra, text="Solo sin asignar", variable=self.var_sin_asignar,
                                                command=self._pintar)
        self.solo_sin_asignar.pack(side="left", padx=12)

        ttk.Button(barra, text="Abrir detalle", command=self._abrir).pack(side="right")
        ttk.Button(barra, text="Renombrar", command=self._renombrar).pack(side="right", padx=6)
        ttk.Button(barra, text="Asignar / reasignar", style="Primario.TButton",
                   command=self._asignar).pack(side="right", padx=6)

        self.tabla = Tabla(self, [("nombre", "Nombre", 180), ("tipo", "Tipo", 170), ("codigo", "Código", 130),
                                  ("perfil", "Perfil", 160), ("conexion", "Conexión", 110),
                                  ("senal", "Última señal", 200), ("permiso", "Permiso", 110)],
                           alto=14, al_doble_clic=lambda iid: self.app.navegar("detalle", dispositivo_id=iid))
        self.tabla.pack(fill="both", expand=True)
        self.estado = EstadoVista(self)

    def al_mostrar(self, **_):
        self._pintar()

    def al_actualizar(self):
        self._pintar()

    def al_reloj(self):
        self._pintar()

    def _pintar(self):
        inst = self.servicios.instantanea
        i = self.filtro_tipo.current()
        tipo = TIPOS_DISPOSITIVO[i - 1] if i > 0 else None
        lista = dominio.filtrar_dispositivos(inst.dispositivos, perfil_id=self.perfil_id, tipo=tipo,
                                             sin_asignar=self.var_sin_asignar.get())
        seleccion = self.tabla.seleccion()
        filas = []
        for d in lista:
            estado = dominio.estado_conexion(d)
            etiquetas = ("critica",) if estado == dominio.FUERA_DE_LINEA else ()
            permiso = "Propietario" if d.get("propietario_id") == self.servicios.usuario_id else (
                "Control" if self.servicios.puede_controlar(d) else "Solo lectura")
            filas.append((d["id"], (d.get("nombre") or "—", NOMBRES_TIPO.get(d["tipo"], d["tipo"]), d["codigo"],
                                    inst.nombre_perfil(d.get("perfil_id")), dominio.NOMBRES_CONEXION[estado],
                                    f"{formato_local(d.get('ultima_senal_en'), True)} ({hace_cuanto(d.get('ultima_senal_en'))})",
                                    permiso), etiquetas))
        self.tabla.llenar(filas)
        if seleccion and self.tabla.arbol.exists(seleccion):
            self.tabla.arbol.selection_set(seleccion)

    def _seleccionado(self) -> dict | None:
        iid = self.tabla.seleccion()
        if not iid:
            self.mostrar_error(ErrorValidacion("Seleccione un dispositivo de la lista."))
            return None
        return self.servicios.instantanea.dispositivo(iid)

    def _registrar(self):
        codigo = self.codigo.get().strip()
        nombre = self.nombre.get().strip() or None
        if not codigo:
            self.mostrar_error(ErrorValidacion("Ingrese el código del dispositivo."))
            return

        def ok(d):
            self.codigo.delete(0, "end")
            self.nombre.delete(0, "end")
            self.app.notificar(f"Dispositivo registrado: {d.get('nombre') or codigo} "
                               f"({NOMBRES_TIPO.get(d.get('tipo'), d.get('tipo', ''))}).", "exito")
            self.app.recargar()

        self.tarea(lambda: self.servicios.dispositivos.registrar(codigo, nombre), ok, boton=self.btn_registrar)

    def _abrir(self):
        d = self._seleccionado()
        if d:
            self.app.navegar("detalle", dispositivo_id=d["id"])

    def _renombrar(self):
        d = self._seleccionado()
        if not d:
            return
        from tkinter import simpledialog

        nuevo = simpledialog.askstring("Renombrar", "Nuevo nombre del dispositivo:", parent=self,
                                       initialvalue=d.get("nombre") or "")
        if nuevo is None:
            return
        nuevo = nuevo.strip()
        if not nuevo:
            self.mostrar_error(ErrorValidacion("El nombre no puede estar vacío."))
            return
        self.tarea(lambda: self.servicios.dispositivos.renombrar(d["id"], nuevo),
                   lambda _: self.app.recargar(), exito="Nombre actualizado.")

    def _asignar(self):
        d = self._seleccionado()
        if not d:
            return
        if d.get("propietario_id") != self.servicios.usuario_id:
            self.mostrar_error(ErrorValidacion("Solo el propietario del dispositivo puede asignarlo a un perfil."))
            return
        DialogoAsignar(self, d)


class DialogoAsignar:
    def __init__(self, pantalla: PantallaDispositivos, dispositivo: dict):
        import tkinter as tk

        self.pantalla = pantalla
        self.d = dispositivo
        inst = pantalla.servicios.instantanea
        # Solo perfiles propios activos (política dispositivos_editar).
        self.perfiles = [p for p in inst.perfiles if p["propietario_id"] == pantalla.servicios.usuario_id]
        self.ventana = tk.Toplevel(pantalla)
        self.ventana.title("Asignar dispositivo")
        self.ventana.transient(pantalla.winfo_toplevel())
        self.ventana.grab_set()
        cuerpo = ttk.Frame(self.ventana, padding=20)
        cuerpo.pack(fill="both", expand=True)
        ttk.Label(cuerpo, text=f"{dispositivo.get('nombre') or dispositivo['codigo']}", style="Subtitulo.TLabel").pack(anchor="w")
        ttk.Label(cuerpo, text=f"Perfil actual: {inst.nombre_perfil(dispositivo.get('perfil_id'))}").pack(anchor="w", pady=(4, 10))
        self.combo = ttk.Combobox(cuerpo, state="readonly", width=34,
                                  values=[SIN_ASIGNAR] + [p["nombre"] for p in self.perfiles])
        ids = [None] + [p["id"] for p in self.perfiles]
        self.combo.current(ids.index(dispositivo.get("perfil_id")) if dispositivo.get("perfil_id") in ids else 0)
        self.combo.pack(anchor="w")
        ttk.Label(cuerpo, text="Las lecturas y alertas nuevas usarán el perfil elegido.\n"
                               "El historial anterior conserva su perfil original.",
                  style="Suave.TLabel", justify="left").pack(anchor="w", pady=10)
        botones = ttk.Frame(cuerpo)
        botones.pack(fill="x")
        self.btn = ttk.Button(botones, text="Guardar", style="Primario.TButton", command=self._guardar)
        self.btn.pack(side="right")
        ttk.Button(botones, text="Cancelar", command=self.ventana.destroy).pack(side="right", padx=8)

    def _guardar(self):
        i = self.combo.current()
        perfil_id = None if i <= 0 else self.perfiles[i - 1]["id"]
        if perfil_id == self.d.get("perfil_id"):
            self.ventana.destroy()
            return

        def ok(_):
            self.ventana.destroy()
            self.pantalla.app.recargar()

        self.pantalla.tarea(lambda: self.pantalla.servicios.dispositivos.asignar_perfil(self.d["id"], perfil_id),
                            ok, boton=self.btn,
                            exito="Dispositivo sin asignar." if perfil_id is None else "Dispositivo asignado.")
