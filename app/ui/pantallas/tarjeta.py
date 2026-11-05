"""Tarjeta de un dispositivo (o de un tipo sin dispositivo) para el panel."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.config.valores import NOMBRES_TIPO
from app.config.zona import formato_local, hace_cuanto
from app.services import dominio
from app.services.contexto import Instantanea
from app.ui.estilos import COLORES
from app.ui.widgets import Insignia

TONO_CONEXION = {dominio.EN_LINEA: "exito", dominio.FUERA_DE_LINEA: "critico", dominio.SIN_DATOS: "neutro"}

ICONOS = {"cuna": "🛏", "colchon": "▭", "movil": "✺", "seguridad": "🛡", "juguete": "◉", "biberon": "🍼"}


def g(valor) -> str:
    """Número compacto aunque llegue como texto (Realtime puede mandar numeric como string)."""
    try:
        return f"{float(valor):g}"
    except (TypeError, ValueError):
        return "—" if valor is None else str(valor)


def resumen_tipo(d: dict, config: dict | None, lecturas: dict[str, dict]) -> list[str]:
    """Líneas de estado según los datos reales disponibles (sin inventar valores)."""
    lineas: list[str] = []
    tipo = d.get("tipo")
    vivo = {l.etiqueta: l.valor for l in dominio.lecturas_de(d)}

    def lectura(clave_vivo: str, tipo_evento: str, unidad: str) -> str:
        if clave_vivo in vivo:
            return vivo[clave_vivo]
        ev = lecturas.get(tipo_evento)
        if ev and ev.get("valor") is not None:
            return f"{g(ev['valor'])} {ev.get('unidad') or unidad} ({hace_cuanto(ev.get('ocurrido_en'))}, historial)"
        return "sin datos"

    if tipo == "cuna":
        lineas.append(f"Temperatura: {lectura('Temperatura', 'temperatura', '°C')}")
        lineas.append(f"Humedad: {lectura('Humedad', 'humedad', '%')}")
        if config:
            lineas.append(f"Rango: {g(config['temp_min'])}–{g(config['temp_max'])} °C · "
                          f"{g(config['hum_min'])}–{g(config['hum_max'])} %")
            lineas.append(f"Luz nocturna: {config['luz_intensidad']} %")
    elif tipo == "colchon":
        lineas.append(f"Peso: {lectura('Peso', 'peso', 'g')}")
        lineas.append(dominio.conexion_colchon(d))
        if config:
            lineas.append("Modo siesta: ACTIVO" if config.get("siesta_activa") else "Modo siesta: inactivo")
    elif tipo == "movil":
        if config:
            from app.config.valores import nombre_secuencia, nombre_velocidad

            lineas.append(("Ordenado: encendido" if config.get("movil_encendido") else "Ordenado: apagado")
                          + f" · {nombre_secuencia(config['movil_secuencia'])} · {nombre_velocidad(config['movil_velocidad'])}")
    elif tipo == "seguridad":
        if config:
            lineas.append("Seguridad: ARMADA" if config.get("seguridad_armada") else "Seguridad: desarmada")
        for t, nombre in (("puerta", "Última puerta"), ("presencia", "Última presencia")):
            ev = lecturas.get(t)
            lineas.append(f"{nombre}: {formato_local(ev['ocurrido_en']) if ev else 'sin registros'}")
    elif tipo == "juguete":
        ev = lecturas.get("juguete_acierto")
        lineas.append(f"Último acierto: {formato_local(ev['ocurrido_en']) if ev else 'sin registros'}")
        if "Botón iluminado" in vivo:
            lineas.append(f"Botón iluminado: {vivo['Botón iluminado']}")
        if config:
            lineas.append(f"Ronda: {config['juguete_tiempo_ronda_s']} s · volumen {config['juguete_volumen']}")
    elif tipo == "biberon":
        lineas.append(f"Leche: {lectura('Temperatura de la leche', 'temperatura_biberon', '°C')}")
        if config:
            lineas.append(f"Rango seguro: {g(config['temp_min'])}–{g(config['temp_max'])} °C")
    return lineas


class TarjetaDispositivo(ttk.Frame):
    def __init__(self, padre, al_abrir, ancho: int = 300):
        super().__init__(padre, style="Caja.TFrame", padding=14)
        self._al_abrir = al_abrir
        self._dispositivo: dict | None = None
        cabeza = ttk.Frame(self, style="Tarjeta.TFrame")
        cabeza.pack(fill="x")
        self.icono = tk.Label(cabeza, bg=COLORES["tarjeta"], fg=COLORES["petroleo"], font=("Segoe UI Emoji", 18))
        self.icono.pack(side="left", padx=(0, 8))
        textos = ttk.Frame(cabeza, style="Tarjeta.TFrame")
        textos.pack(side="left", fill="x", expand=True)
        self.nombre = ttk.Label(textos, style="TarjetaTitulo.TLabel")
        self.nombre.pack(anchor="w")
        self.subtitulo = ttk.Label(textos, style="TarjetaSuave.TLabel")
        self.subtitulo.pack(anchor="w")
        self.conexion = Insignia(self, "", "neutro")
        self.conexion.pack(anchor="w", pady=(8, 2))
        self.senal = ttk.Label(self, style="TarjetaSuave.TLabel")
        self.senal.pack(anchor="w")
        self.advertencia = tk.Label(self, bg=COLORES["critico_suave"], fg=COLORES["critico"], justify="left",
                                    font=("Segoe UI", 9, "bold"), anchor="w", padx=6, pady=4, wraplength=ancho - 20)
        self.cuerpo = ttk.Label(self, style="Tarjeta.TLabel", justify="left", wraplength=ancho - 20)
        self.cuerpo.pack(anchor="w", pady=(8, 4), fill="x")
        self.alertas = ttk.Label(self, style="TarjetaSuave.TLabel")
        self.alertas.pack(anchor="w")
        self.boton = ttk.Button(self, text="Abrir detalle →", style="Enlace.TButton",
                                command=lambda: self._dispositivo and self._al_abrir(self._dispositivo["id"]))
        self.boton.pack(anchor="e", pady=(6, 0))

    def mostrar(self, d: dict, inst: Instantanea, alertas: list[dict], aviso: str | None,
                alerta_registrada: bool, puede_controlar: bool) -> None:
        self._dispositivo = d
        tipo = d["tipo"]
        self.icono.configure(text=ICONOS.get(tipo, "•"))
        self.nombre.configure(text=d.get("nombre") or NOMBRES_TIPO[tipo])
        permiso = "" if puede_controlar else " · solo lectura"
        self.subtitulo.configure(text=f"{NOMBRES_TIPO[tipo]} · {d['codigo']} · {inst.nombre_perfil(d.get('perfil_id'))}{permiso}")
        estado = dominio.estado_conexion(d)
        self.conexion.cambiar(dominio.NOMBRES_CONEXION[estado], TONO_CONEXION[estado])
        self.senal.configure(text=f"Última señal: {formato_local(d.get('ultima_senal_en'), True)} "
                                  f"({hace_cuanto(d.get('ultima_senal_en'))})")
        if aviso:
            extra = (" La base ya registró la alerta «fuera de línea»." if alerta_registrada
                     else " Aún no hay alerta registrada; pg_cron la crea al detectar 60 s sin señal.")
            self.advertencia.configure(text="⛔ " + aviso + extra)
            self.advertencia.pack(anchor="w", fill="x", pady=(6, 0), before=self.cuerpo)
        else:
            self.advertencia.pack_forget()
        lineas = resumen_tipo(d, inst.configuraciones.get(d["id"]), inst.lecturas_historial.get(d["id"], {}))
        self.cuerpo.configure(text="\n".join(lineas) or "Sin lecturas disponibles.")
        criticas = sum(1 for a in alertas if a.get("severidad") == "critica")
        if alertas:
            self.alertas.configure(text=f"⚠ {len(alertas)} alerta(s) en 24 h" + (f", {criticas} crítica(s)" if criticas else ""),
                                   foreground=COLORES["critico"] if criticas else COLORES["aviso"])
        else:
            self.alertas.configure(text="Sin alertas en 24 h", foreground=COLORES["texto_suave"])


class TarjetaVacia(ttk.Frame):
    def __init__(self, padre, tipo: str, al_registrar, ancho: int = 300):
        super().__init__(padre, style="Caja.TFrame", padding=14)
        cabeza = ttk.Frame(self, style="Tarjeta.TFrame")
        cabeza.pack(fill="x")
        tk.Label(cabeza, text=ICONOS.get(tipo, "•"), bg=COLORES["tarjeta"], fg=COLORES["texto_suave"],
                 font=("Segoe UI Emoji", 18)).pack(side="left", padx=(0, 8))
        ttk.Label(cabeza, text=NOMBRES_TIPO[tipo], style="TarjetaTitulo.TLabel").pack(side="left")
        Insignia(self, "Sin dispositivo", "neutro").pack(anchor="w", pady=(8, 4))
        ttk.Label(self, text="No hay un dispositivo de este tipo para el filtro actual.",
                  style="TarjetaSuave.TLabel", wraplength=ancho - 20).pack(anchor="w")
        ttk.Button(self, text="Registrar dispositivo →", style="Enlace.TButton",
                   command=al_registrar).pack(anchor="e", pady=(10, 0))
