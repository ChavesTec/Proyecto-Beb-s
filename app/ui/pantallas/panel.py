"""Panel principal: resumen del ecosistema y una tarjeta por cada uno de los seis tipos."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.config.valores import NOMBRES_TIPO, TIPOS_DISPOSITIVO
from app.services import dominio
from app.ui.base import Pantalla
from app.ui.estilos import COLORES
from app.ui.pantallas.tarjeta import TarjetaDispositivo, TarjetaVacia
from app.ui.widgets import Aviso, EstadoVista, MarcoDesplazable

ANCHO_TARJETA = 310
TODOS_TIPOS = "Todos los tipos"


class PantallaPanel(Pantalla):
    titulo = "Panel"

    def __init__(self, padre, app):
        super().__init__(padre, app)
        barra = ttk.Frame(self)
        barra.pack(fill="x")
        ttk.Label(barra, text="Panel del ecosistema", style="Titulo.TLabel").pack(side="left")
        self.filtro_tipo = ttk.Combobox(barra, state="readonly", width=26,
                                        values=[TODOS_TIPOS] + [NOMBRES_TIPO[t] for t in TIPOS_DISPOSITIVO])
        self.filtro_tipo.set(TODOS_TIPOS)
        self.filtro_tipo.pack(side="right")
        self.filtro_tipo.bind("<<ComboboxSelected>>", lambda e: self._pintar())
        ttk.Label(barra, text="Tipo:").pack(side="right", padx=6)

        self.resumen = ttk.Frame(self)
        self.resumen.pack(fill="x", pady=(14, 10))
        self._cifras: dict[str, tk.Label] = {}
        for clave, titulo, color in (("total", "Dispositivos", COLORES["petroleo"]),
                                     (dominio.EN_LINEA, "En línea", COLORES["exito"]),
                                     (dominio.FUERA_DE_LINEA, "Fuera de línea", COLORES["critico"]),
                                     (dominio.SIN_DATOS, "Sin datos", COLORES["texto_suave"]),
                                     ("alertas_24h", "Alertas 24 h", COLORES["aviso"]),
                                     ("criticas_24h", "Críticas 24 h", COLORES["critico"])):
            caja = ttk.Frame(self.resumen, style="Caja.TFrame", padding=(16, 10))
            caja.pack(side="left", padx=(0, 10), fill="x", expand=True)
            cifra = tk.Label(caja, text="—", bg=COLORES["tarjeta"], fg=color, font=("Segoe UI", 20, "bold"))
            cifra.pack(anchor="w")
            ttk.Label(caja, text=titulo, style="TarjetaSuave.TLabel").pack(anchor="w")
            self._cifras[clave] = cifra

        self.avisos = Aviso(self)
        self.estado = EstadoVista(self)
        self.marco = MarcoDesplazable(self)
        self.marco.pack(fill="both", expand=True)
        self._tarjetas: list[ttk.Frame] = []
        self._columnas = 0
        self.marco.lienzo.bind("<Configure>", self._al_redimensionar, add="+")
        self.estado.cargando("Cargando dispositivos…")

    def al_mostrar(self, **_):
        self._pintar()

    def al_actualizar(self):
        self._pintar()

    def al_cambio(self, tabla, tipo, registro):
        if tabla in {"dispositivos", "configuracion", "alertas"}:
            self._pintar()

    def al_reloj(self):
        """Solo refresca las tarjetas existentes (estado de conexión y "hace X s")."""
        inst = self.servicios.instantanea
        for tarjeta in self._tarjetas:
            if isinstance(tarjeta, TarjetaDispositivo) and tarjeta._dispositivo:
                d = inst.dispositivo(tarjeta._dispositivo["id"])
                if d:
                    self._mostrar_tarjeta(tarjeta, d)

    def _al_redimensionar(self, evento):
        columnas = max(1, evento.width // (ANCHO_TARJETA + 16))
        if columnas != self._columnas:
            self._columnas = columnas
            self._ubicar()

    def _tipo_filtrado(self) -> str | None:
        i = self.filtro_tipo.current()
        return TIPOS_DISPOSITIVO[i - 1] if i > 0 else None

    def _pintar(self):
        inst = self.servicios.instantanea
        if inst.cargada_en is None:
            return
        r = self.servicios.resumen(self.perfil_id)
        for clave, etiqueta in self._cifras.items():
            etiqueta.configure(text=str(r.get(clave, 0)))
        if not inst.perfiles:
            self.avisos.mostrar("Aún no hay perfiles de bebé. Cree uno en «Perfiles» para asignar dispositivos.",
                                "info", before=self.marco)
        elif r["total"] == 0:
            self.avisos.mostrar("No hay dispositivos para este perfil. Registre uno con su código en «Dispositivos».",
                                "info", before=self.marco)
        else:
            self.avisos.ocultar()

        for t in self._tarjetas:
            t.destroy()
        self._tarjetas = []
        tipos = [self._tipo_filtrado()] if self._tipo_filtrado() else list(TIPOS_DISPOSITIVO)
        dispositivos = dominio.filtrar_dispositivos(inst.dispositivos, perfil_id=self.perfil_id)
        for tipo in tipos:
            del_tipo = [d for d in dispositivos if d["tipo"] == tipo]
            if not del_tipo:
                self._tarjetas.append(TarjetaVacia(self.marco.interior, tipo,
                                                   lambda: self.app.navegar("dispositivos"), ANCHO_TARJETA))
                continue
            for d in del_tipo:
                tarjeta = TarjetaDispositivo(self.marco.interior, self._abrir, ANCHO_TARJETA)
                self._mostrar_tarjeta(tarjeta, d)
                self._tarjetas.append(tarjeta)
        self._ubicar()

    def _mostrar_tarjeta(self, tarjeta: TarjetaDispositivo, d: dict) -> None:
        inst = self.servicios.instantanea
        config = inst.configuraciones.get(d["id"])
        aviso = dominio.advertencia_critica_desconexion(d, config, dominio.estado_conexion(d))
        tarjeta.mostrar(d, inst, self.servicios.alertas_de(d["id"]), aviso,
                        self.servicios.alerta_fuera_de_linea_registrada(d) if aviso else False,
                        self.servicios.puede_controlar(d))

    def _ubicar(self):
        columnas = max(self._columnas, 1)
        for i in range(8):
            self.marco.interior.columnconfigure(i, weight=1 if i < columnas else 0, uniform="tarjetas" if i < columnas else "")
        for i, tarjeta in enumerate(self._tarjetas):
            tarjeta.grid(row=i // columnas, column=i % columnas, sticky="nsew", padx=(0, 12), pady=(0, 12))

    def _abrir(self, dispositivo_id: str):
        self.app.navegar("detalle", dispositivo_id=dispositivo_id)
