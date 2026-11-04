"""Alertas con filtros y estado de envío (EP09)."""
from __future__ import annotations

from tkinter import ttk

from app.config.valores import ESTADOS_ALERTA, SEVERIDADES, TAMANO_PAGINA, TIPOS_ALERTA
from app.config.zona import formato_local
from app.errores import ErrorValidacion
from app.repositories.historial import FiltroAlertas, Pagina
from app.services import dominio
from app.ui.base import Pantalla
from app.ui.pantallas.filtros import TODOS, SelectorFechas, SelectorPerfilDispositivo
from app.ui.widgets import Tabla


class PantallaAlertas(Pantalla):
    titulo = "Alertas"

    def __init__(self, padre, app):
        super().__init__(padre, app)
        ttk.Label(self, text="Alertas", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(self, text="Las alertas las crea la base de datos a partir de las lecturas. Las críticas se marcan "
                             "con ⛔ y en rojo.", style="Suave.TLabel").pack(anchor="w")
        filtros = ttk.LabelFrame(self, text="Filtros", padding=12)
        filtros.pack(fill="x", pady=(10, 8))
        self.sel = SelectorPerfilDispositivo(filtros, self.servicios, 0, 0)
        self.tipo = self._combo(filtros, "Tipo", [dominio.NOMBRES_TIPO_ALERTA[t] for t in TIPOS_ALERTA], 2)
        self.severidad = self._combo(filtros, "Gravedad", [dominio.NOMBRES_SEVERIDAD[s] for s in SEVERIDADES], 3)
        self.estado = self._combo(filtros, "Envío", [dominio.NOMBRES_ESTADO_ALERTA[e] for e in ESTADOS_ALERTA], 4)
        self.fechas = SelectorFechas(filtros, 2, 0)
        self.btn = ttk.Button(filtros, text="Aplicar filtros", style="Primario.TButton", command=self.buscar)
        self.btn.grid(row=3, column=2, sticky="w")

        self.tabla = Tabla(self, [("fecha", "Fecha y hora (CR)", 140), ("sev", "Gravedad", 110), ("tipo", "Tipo", 160),
                                  ("perfil", "Perfil", 130), ("disp", "Dispositivo", 140), ("mensaje", "Mensaje", 420),
                                  ("envio", "Telegram", 190)], alto=16)
        self.tabla.pack(fill="both", expand=True)
        pag = ttk.Frame(self)
        pag.pack(fill="x", pady=(8, 0))
        self.btn_ant = ttk.Button(pag, text="← Anterior", command=lambda: self._ir(-1))
        self.btn_ant.pack(side="left")
        self.lbl = ttk.Label(pag)
        self.lbl.pack(side="left", padx=12)
        self.btn_sig = ttk.Button(pag, text="Siguiente →", command=lambda: self._ir(1))
        self.btn_sig.pack(side="left")
        ttk.Label(pag, text="«Pendiente de envío» significa que la base aún no confirma el envío por Telegram.",
                  style="Suave.TLabel").pack(side="right")
        self._filtro: FiltroAlertas | None = None
        self._pagina = 0

    def _combo(self, padre, titulo, valores, columna):
        ttk.Label(padre, text=titulo, style="Tarjeta.TLabel").grid(row=0, column=columna, sticky="w")
        c = ttk.Combobox(padre, state="readonly", width=24, values=[TODOS] + valores)
        c.set(TODOS)
        c.grid(row=1, column=columna, sticky="w", padx=(0, 10))
        return c

    def al_mostrar(self, **_):
        self.sel.llenar(perfil_preferido=self.perfil_id)
        self.buscar()

    def al_actualizar(self):
        self.sel.llenar()

    def al_cambio(self, tabla, tipo, registro):
        if tabla == "alertas" and self._pagina == 0 and self._filtro is not None:
            self._cargar()

    def buscar(self):
        try:
            desde, hasta = self.fechas.rango_utc()
        except ErrorValidacion as e:
            self.mostrar_error(e)
            return

        def valor(combo, opciones):
            i = combo.current()
            return opciones[i - 1] if i > 0 else None

        self._filtro = FiltroAlertas(perfil_id=self.sel.perfil_id(), dispositivo_id=self.sel.dispositivo_id(),
                                     tipo=valor(self.tipo, TIPOS_ALERTA), severidad=valor(self.severidad, SEVERIDADES),
                                     estado=valor(self.estado, ESTADOS_ALERTA), desde_utc=desde, hasta_utc=hasta)
        self._pagina = 0
        self._cargar()

    def _ir(self, delta):
        self._pagina = max(0, self._pagina + delta)
        self._cargar()

    def _cargar(self):
        f, p = self._filtro, self._pagina
        self.tarea(lambda: self.servicios.historial.pagina_alertas(f, p), self._mostrar, boton=self.btn)

    def _mostrar(self, pagina: Pagina):
        inst = self.servicios.instantanea
        filas = []
        for a in pagina.filas:
            d = inst.dispositivo(a.get("dispositivo_id")) if a.get("dispositivo_id") else None
            critica = a["severidad"] == "critica"
            sev = ("⛔ " if critica else "⚠ " if a["severidad"] == "advertencia" else "ℹ ") + \
                dominio.NOMBRES_SEVERIDAD.get(a["severidad"], a["severidad"])
            envio = dominio.NOMBRES_ESTADO_ALERTA.get(a["estado"], a["estado"])
            if a.get("intentos"):
                envio += f" ({a['intentos']} intento/s)"
            filas.append((str(a["id"]), (formato_local(a["creada_en"]), sev,
                                         dominio.NOMBRES_TIPO_ALERTA.get(a["tipo"], a["tipo"]),
                                         inst.nombre_perfil(a.get("perfil_id")),
                                         (d.get("nombre") or d["codigo"]) if d else "—", a["mensaje"], envio),
                          ("critica",) if critica else ()))
        self.tabla.llenar(filas or [("vacio", ("", "", "", "", "", "No hay alertas para los filtros seleccionados", ""), ())])
        self.lbl.configure(text=f"Página {pagina.pagina + 1} de {pagina.paginas} · {pagina.total or 0} alertas")
        self.btn_ant.configure(state="normal" if pagina.pagina > 0 else "disabled")
        self.btn_sig.configure(state="normal" if (pagina.total or 0) > (pagina.pagina + 1) * TAMANO_PAGINA else "disabled")
