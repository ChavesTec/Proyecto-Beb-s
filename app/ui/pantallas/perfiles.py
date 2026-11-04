"""Perfiles de bebé: crear, editar, seleccionar, eliminar y compartir (HU-03, CA-17.1, CA-18.2)."""
from __future__ import annotations

from datetime import date
from tkinter import ttk

from app.config.zona import formato_local
from app.errores import ErrorValidacion
from app.services import dominio
from app.ui.base import Pantalla
from app.ui.widgets import Tabla, campo


def _edad(fecha_texto: str) -> str:
    try:
        nacimiento = date.fromisoformat(fecha_texto)
    except (TypeError, ValueError):
        return "—"
    dias = (date.today() - nacimiento).days
    if dias < 0:
        return "—"
    meses = dias // 30
    return f"{dias} días" if meses < 1 else (f"{meses} meses" if meses < 24 else f"{dias // 365} años")


class PantallaPerfiles(Pantalla):
    titulo = "Perfiles"

    def __init__(self, padre, app):
        super().__init__(padre, app)
        ttk.Label(self, text="Perfiles de bebé", style="Titulo.TLabel").pack(anchor="w")
        cuerpo = ttk.Frame(self)
        cuerpo.pack(fill="both", expand=True, pady=(12, 0))

        izquierda = ttk.Frame(cuerpo)
        izquierda.pack(side="left", fill="both", expand=True)
        self.tabla = Tabla(izquierda, [("nombre", "Nombre", 180), ("nacimiento", "Nacimiento", 110),
                                       ("edad", "Edad", 90), ("rol", "Mi acceso", 150),
                                       ("dispositivos", "Dispositivos", 90)], alto=12)
        self.tabla.pack(fill="both", expand=True)
        self.tabla.arbol.bind("<<TreeviewSelect>>", lambda e: self._al_seleccionar())
        botones = ttk.Frame(izquierda)
        botones.pack(fill="x", pady=8)
        ttk.Button(botones, text="Usar en el panel", style="Primario.TButton", command=self._usar).pack(side="left")
        self.btn_eliminar = ttk.Button(botones, text="Eliminar perfil", style="Peligro.TButton", command=self._eliminar)
        self.btn_eliminar.pack(side="right")

        derecha = ttk.Frame(cuerpo, width=380)
        derecha.pack(side="left", fill="y", padx=(18, 0))

        formulario = ttk.LabelFrame(derecha, text="Crear o editar perfil", padding=14)
        formulario.pack(fill="x")
        self.nombre = campo(formulario, "Nombre", 0)
        self.fecha = campo(formulario, "Fecha de nacimiento\n(AAAA-MM-DD)", 1)
        fila = ttk.Frame(formulario, style="Tarjeta.TFrame")
        fila.grid(row=2, column=0, columnspan=2, sticky="we", pady=(10, 0))
        self.btn_crear = ttk.Button(fila, text="Crear nuevo", style="Primario.TButton", command=self._crear)
        self.btn_crear.pack(side="left")
        self.btn_editar = ttk.Button(fila, text="Guardar cambios", command=self._editar)
        self.btn_editar.pack(side="left", padx=8)
        ttk.Button(fila, text="Limpiar", command=self._limpiar).pack(side="left")

        compartir = ttk.LabelFrame(derecha, text="Compartir perfil seleccionado", padding=14)
        compartir.pack(fill="x", pady=(14, 0))
        self.correo = campo(compartir, "Correo de la persona", 0)
        import tkinter as tk

        self.var_control = tk.BooleanVar(value=False)
        ttk.Checkbutton(compartir, text="Puede controlar dispositivos", variable=self.var_control,
                        style="Tarjeta.TCheckbutton").grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(compartir, text="La persona debe tener ya una cuenta. Sin control, solo ve lecturas,\n"
                                  "alertas, historial y fotos.", style="TarjetaSuave.TLabel",
                  justify="left").grid(row=2, column=0, columnspan=2, sticky="w")
        self.btn_compartir = ttk.Button(compartir, text="Compartir", style="Primario.TButton", command=self._compartir)
        self.btn_compartir.grid(row=3, column=0, sticky="w", pady=(8, 0))

        self.accesos = ttk.LabelFrame(derecha, text="Personas con acceso", padding=10)
        self.accesos.pack(fill="both", expand=True, pady=(14, 0))
        self.tabla_accesos = Tabla(self.accesos, [("usuario", "Usuario", 150), ("control", "Control", 70),
                                                   ("desde", "Desde", 110)], alto=4)
        self.tabla_accesos.pack(fill="both", expand=True)
        fila = ttk.Frame(self.accesos, style="Tarjeta.TFrame")
        fila.pack(fill="x", pady=(6, 0))
        ttk.Button(fila, text="Alternar control", command=self._alternar_control).pack(side="left")
        ttk.Button(fila, text="Quitar acceso", command=self._quitar).pack(side="left", padx=6)
        self._accesos: list[dict] = []

    # ------------------------------------------------------------------
    def al_mostrar(self, **_):
        self._pintar()

    def al_actualizar(self):
        self._pintar()

    def _pintar(self):
        inst = self.servicios.instantanea
        uid = self.servicios.usuario_id
        filas = []
        for p in inst.perfiles:
            if p["propietario_id"] == uid:
                rol = "Propietario"
            else:
                rol = "Compartido · control" if inst.accesos.get(p["id"]) else "Compartido · lectura"
            cuantos = sum(1 for d in inst.dispositivos if d.get("perfil_id") == p["id"])
            filas.append((p["id"], (p["nombre"], p["fecha_nacimiento"], _edad(p["fecha_nacimiento"]), rol, cuantos), ()))
        seleccion = self.tabla.seleccion()
        self.tabla.llenar(filas)
        if seleccion and self.tabla.arbol.exists(seleccion):
            self.tabla.arbol.selection_set(seleccion)
        elif self.perfil_id and self.tabla.arbol.exists(self.perfil_id):
            self.tabla.arbol.selection_set(self.perfil_id)

    def _perfil(self, exigir=True) -> dict | None:
        iid = self.tabla.seleccion()
        perfil = next((p for p in self.servicios.instantanea.perfiles if p["id"] == iid), None)
        if perfil is None and exigir:
            self.mostrar_error(ErrorValidacion("Seleccione un perfil de la lista."))
        return perfil

    def _al_seleccionar(self):
        p = self._perfil(exigir=False)
        if not p:
            return
        self._limpiar(mantener_seleccion=True)
        self.nombre.insert(0, p["nombre"])
        self.fecha.insert(0, p["fecha_nacimiento"])
        propio = p["propietario_id"] == self.servicios.usuario_id
        for b in (self.btn_editar, self.btn_eliminar, self.btn_compartir):
            b.configure(state="normal" if propio else "disabled")
        self._cargar_accesos(p) if propio else self.tabla_accesos.llenar([])

    def _cargar_accesos(self, p: dict):
        def ok(filas):
            self._accesos = filas
            uid = self.servicios.usuario_id
            self.tabla_accesos.llenar([
                (a["usuario_id"], ("Usted (propietario)" if a["usuario_id"] == uid else f"Usuario {a['usuario_id'][:8]}…",
                                   "Sí" if a["puede_controlar"] else "No", formato_local(a["creado_en"])), ())
                for a in filas])
        self.tarea(lambda: self.servicios.perfiles.accesos_de_perfil(p["id"]), ok)

    def _limpiar(self, mantener_seleccion: bool = False):
        self.nombre.delete(0, "end")
        self.fecha.delete(0, "end")
        if not mantener_seleccion:
            self.tabla.arbol.selection_remove(self.tabla.arbol.selection())
            self.tabla_accesos.llenar([])

    def _usar(self):
        p = self._perfil()
        if p:
            self.app.seleccionar_perfil(p["id"])
            self.app.navegar("panel")

    def _crear(self):
        try:
            nombre, fecha = dominio.validar_perfil(self.nombre.get(), self.fecha.get())
        except ErrorValidacion as e:
            self.mostrar_error(e)
            return

        def ok(perfil):
            self._limpiar()
            self.app.recargar()

        self.tarea(lambda: self.servicios.perfiles.crear(nombre, fecha), ok, boton=self.btn_crear,
                   exito=f"Perfil «{nombre}» creado.")

    def _editar(self):
        p = self._perfil()
        if not p:
            return
        try:
            nombre, fecha = dominio.validar_perfil(self.nombre.get(), self.fecha.get())
        except ErrorValidacion as e:
            self.mostrar_error(e)
            return
        self.tarea(lambda: self.servicios.perfiles.editar(p["id"], nombre, fecha),
                   lambda _: self.app.recargar(), boton=self.btn_editar, exito="Perfil actualizado.")

    def _eliminar(self):
        p = self._perfil()
        if not p:
            return
        asignados = sum(1 for d in self.servicios.instantanea.dispositivos if d.get("perfil_id") == p["id"])
        if not self.confirmar("Eliminar perfil",
                              f"¿Eliminar el perfil «{p['nombre']}»?\n\n"
                              f"• {asignados} dispositivo(s) quedarán «sin asignar».\n"
                              "• El historial, las alertas y las fotos se conservan.\n"
                              "• Sus recordatorios se desactivan.\n\nEsta acción no se puede deshacer desde la app."):
            return

        def ok(_):
            if self.app.perfil_seleccionado == p["id"]:
                self.app.seleccionar_perfil(None)
            self._limpiar()
            self.app.recargar()

        self.tarea(lambda: self.servicios.perfiles.eliminar(p["id"]), ok, boton=self.btn_eliminar,
                   exito="Perfil eliminado. Sus dispositivos quedaron sin asignar.")

    def _compartir(self):
        p = self._perfil()
        if not p:
            return
        try:
            correo = dominio.validar_correo(self.correo.get())
        except ErrorValidacion as e:
            self.mostrar_error(e)
            return
        control = self.var_control.get()

        def ok(_):
            self.correo.delete(0, "end")
            self._cargar_accesos(p)

        self.tarea(lambda: self.servicios.perfiles.compartir(p["id"], correo, control), ok, boton=self.btn_compartir,
                   exito=f"Perfil compartido con {correo} ({'con control' if control else 'solo lectura'}).")

    def _acceso_sel(self) -> tuple[dict, dict] | None:
        p = self._perfil()
        iid = self.tabla_accesos.seleccion()
        acceso = next((a for a in self._accesos if a["usuario_id"] == iid), None)
        if not p or not acceso:
            self.mostrar_error(ErrorValidacion("Seleccione una persona de la lista de accesos."))
            return None
        if acceso["usuario_id"] == self.servicios.usuario_id:
            self.mostrar_error(ErrorValidacion("El acceso del propietario no se puede cambiar."))
            return None
        return p, acceso

    def _alternar_control(self):
        sel = self._acceso_sel()
        if sel:
            p, a = sel
            self.tarea(lambda: self.servicios.perfiles.cambiar_control(p["id"], a["usuario_id"], not a["puede_controlar"]),
                       lambda _: self._cargar_accesos(p), exito="Permiso actualizado.")

    def _quitar(self):
        sel = self._acceso_sel()
        if sel and self.confirmar("Quitar acceso", "¿Quitar el acceso de esta persona al perfil?"):
            p, a = sel
            self.tarea(lambda: self.servicios.perfiles.quitar_acceso(p["id"], a["usuario_id"]),
                       lambda _: self._cargar_accesos(p), exito="Acceso retirado.")
