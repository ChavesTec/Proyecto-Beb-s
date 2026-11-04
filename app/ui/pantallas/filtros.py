"""Controles de filtro compartidos (perfil, dispositivo, fechas)."""
from __future__ import annotations

from datetime import date, timedelta
from tkinter import ttk

from app.config.valores import NOMBRES_TIPO
from app.config.zona import parsear_fecha_local, rango_local_a_utc
from app.errores import ErrorValidacion

TODOS = "Todos"


class SelectorPerfilDispositivo:
    """Dos combos: perfil (incluye eliminados, por el historial) y dispositivo."""

    def __init__(self, padre, servicios, fila: int = 0, columna: int = 0, incluir_eliminados: bool = True):
        self.servicios = servicios
        self.incluir_eliminados = incluir_eliminados
        ttk.Label(padre, text="Perfil", style="Tarjeta.TLabel").grid(row=fila, column=columna, sticky="w")
        self.perfil = ttk.Combobox(padre, state="readonly", width=24)
        self.perfil.grid(row=fila + 1, column=columna, sticky="w", padx=(0, 10))
        ttk.Label(padre, text="Dispositivo", style="Tarjeta.TLabel").grid(row=fila, column=columna + 1, sticky="w")
        self.dispositivo = ttk.Combobox(padre, state="readonly", width=28)
        self.dispositivo.grid(row=fila + 1, column=columna + 1, sticky="w", padx=(0, 10))
        self._perfiles: list[str | None] = [None]
        self._dispositivos: list[str | None] = [None]

    def llenar(self, perfil_preferido: str | None = None, dispositivo_preferido: str | None = None) -> None:
        inst = self.servicios.instantanea
        actual_p = self.perfil_id() if self.perfil.get() else perfil_preferido
        actual_d = self.dispositivo_id() if self.dispositivo.get() else dispositivo_preferido
        perfiles = inst.todos_perfiles if self.incluir_eliminados else inst.perfiles
        self._perfiles = [None] + [p["id"] for p in perfiles]
        self.perfil.configure(values=[TODOS] + [p["nombre"] + (" (eliminado)" if p.get("eliminado_en") else "")
                                                for p in perfiles])
        self.perfil.current(self._perfiles.index(actual_p) if actual_p in self._perfiles else 0)
        self._dispositivos = [None] + [d["id"] for d in inst.dispositivos]
        self.dispositivo.configure(values=[TODOS] + [f"{d.get('nombre') or d['codigo']} · {NOMBRES_TIPO.get(d['tipo'], d['tipo'])}"
                                                     for d in inst.dispositivos])
        self.dispositivo.current(self._dispositivos.index(actual_d) if actual_d in self._dispositivos else 0)

    def perfil_id(self) -> str | None:
        i = self.perfil.current()
        return self._perfiles[i] if 0 <= i < len(self._perfiles) else None

    def dispositivo_id(self) -> str | None:
        i = self.dispositivo.current()
        return self._dispositivos[i] if 0 <= i < len(self._dispositivos) else None

    def fijar_perfil(self, perfil_id: str | None) -> None:
        if perfil_id in self._perfiles:
            self.perfil.current(self._perfiles.index(perfil_id))

    def fijar_dispositivo(self, dispositivo_id: str | None) -> None:
        if dispositivo_id in self._dispositivos:
            self.dispositivo.current(self._dispositivos.index(dispositivo_id))


class SelectorFechas:
    def __init__(self, padre, fila: int = 0, columna: int = 0, dias_atras: int | None = 7):
        ttk.Label(padre, text="Desde (AAAA-MM-DD)", style="Tarjeta.TLabel").grid(row=fila, column=columna, sticky="w")
        self.desde = ttk.Entry(padre, width=12)
        self.desde.grid(row=fila + 1, column=columna, sticky="w", padx=(0, 10))
        ttk.Label(padre, text="Hasta (incluido)", style="Tarjeta.TLabel").grid(row=fila, column=columna + 1, sticky="w")
        self.hasta = ttk.Entry(padre, width=12)
        self.hasta.grid(row=fila + 1, column=columna + 1, sticky="w", padx=(0, 10))
        if dias_atras is not None:
            self.desde.insert(0, (date.today() - timedelta(days=dias_atras)).isoformat())
            self.hasta.insert(0, date.today().isoformat())

    def rango_utc(self):
        """Valida y convierte días locales de Costa Rica a UTC. Lanza ErrorValidacion."""
        try:
            desde = parsear_fecha_local(self.desde.get()) if self.desde.get().strip() else None
            hasta = parsear_fecha_local(self.hasta.get()) if self.hasta.get().strip() else None
            return rango_local_a_utc(desde, hasta)
        except ValueError as error:
            raise ErrorValidacion(str(error)) from None
