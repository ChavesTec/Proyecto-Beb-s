"""Ventana principal: sesión, navegación lateral, encabezado, Realtime y polling."""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from app.config.settings import Configuracion, ErrorConfiguracion, cargar_configuracion
from app.config.valores import SEGUNDOS_POLLING_DEGRADADO, SEGUNDOS_POLLING_NORMAL
from app.config.zona import formato_local
from app.errores import ErrorApp
from app.infrastructure.realtime import ServicioRealtime
from app.infrastructure.supabase_client import ConexionSupabase
from app.services.contexto import Servicios
from app.ui.acceso import PantallaAcceso, PantallaConfiguracionFaltante
from app.ui.estilos import COLORES, configurar_estilos
from app.ui.tareas import Ejecutor
from app.ui.widgets import Aviso, Insignia

log = logging.getLogger(__name__)

TODOS_PERFILES = "Todos los perfiles"

NAVEGACION = (
    ("panel", "▦  Panel"),
    ("dispositivos", "⚙  Dispositivos"),
    ("perfiles", "☺  Perfiles"),
    ("alertas", "⚠  Alertas"),
    ("historial", "☰  Historial"),
    ("galeria", "▣  Galería"),
    ("alimentacion", "◔  Alimentación"),
    ("cuenta", "✉  Cuenta y Telegram"),
)


class Aplicacion:
    def __init__(self) -> None:
        self.raiz = tk.Tk()
        self.raiz.title("Ecosistema Bebé — Panel de control")
        self.raiz.geometry("1320x840")
        self.raiz.minsize(1024, 680)
        self.fuentes = configurar_estilos(self.raiz)
        self.ejecutor = Ejecutor(self.raiz)
        self.ejecutor.al_error_global(self._error_global)
        self.raiz.protocol("WM_DELETE_WINDOW", self.cerrar)

        self.config: Configuracion | None = None
        self.conexion: ConexionSupabase | None = None
        self.servicios: Servicios | None = None
        self.realtime: ServicioRealtime | None = None

        self.perfil_seleccionado: str | None = None
        self._estado_realtime = "detenido"
        self._conectado_supabase: bool | None = None
        self._vista: tk.Widget | None = None
        self._pantallas: dict[str, Any] = {}
        self._actual: str | None = None
        self._id_polling: str | None = None
        self._id_reloj: str | None = None
        self._cargando = False
        self._sesion_activa = False

        self._arrancar()

    # ================================================================ arranque
    def _arrancar(self) -> None:
        try:
            self.config = cargar_configuracion()
        except ErrorConfiguracion as error:
            self._mostrar(PantallaConfiguracionFaltante(self.raiz, str(error), self._reintentar_config))
            return
        self.conexion = ConexionSupabase(self.config)
        self.servicios = Servicios(self.conexion)
        self.realtime = ServicioRealtime(
            self.config.supabase_url, self.config.supabase_anon_key,
            al_cambio=lambda *a: self.ejecutor.en_hilo_ui(self._al_cambio_realtime, *a),
            al_estado=lambda estado, detalle: self.ejecutor.en_hilo_ui(self._al_estado_realtime, estado, detalle),
        )
        self.conexion.al_cambiar_token(self._al_token)
        self.mostrar_acceso()

    def _reintentar_config(self) -> None:
        self._arrancar()

    def _mostrar(self, vista: tk.Widget) -> None:
        if self._vista is not None:
            self._vista.destroy()
        self._vista = vista
        vista.pack(fill="both", expand=True)

    def ejecutar(self) -> None:
        self.raiz.mainloop()

    # ================================================================== sesión
    def mostrar_acceso(self, mensaje: str | None = None, tono: str = "aviso") -> None:
        """CA-02.3: sin sesión, toda pantalla privada se destruye y se vuelve al inicio."""
        self._sesion_activa = False
        self._detener_temporizadores()
        self._pantallas.clear()
        self._actual = None
        self._mostrar(PantallaAcceso(self.raiz, self, mensaje, tono))

    def sesion_iniciada(self) -> None:
        self._sesion_activa = True
        self.perfil_seleccionado = None
        self._construir_marco()
        token = self.conexion.token_acceso()
        if token:
            self.realtime.iniciar(token)
        self.recargar(primera=True)
        self._programar_reloj()

    def cerrar_sesion(self) -> None:
        if not messagebox.askyesno("Cerrar sesión", "¿Desea cerrar la sesión?", parent=self.raiz):
            return
        self._salir_de_sesion("Sesión cerrada.", "info")

    def _salir_de_sesion(self, mensaje: str, tono: str) -> None:
        self._sesion_activa = False
        self.realtime.detener(espera_s=0.5)
        conexion = self.conexion
        self.servicios.limpiar()
        self.mostrar_acceso(mensaje, tono)
        self.ejecutor.ejecutar(conexion.cerrar_sesion)

    def _error_global(self, error: ErrorApp) -> bool:
        if error.tipo == "sesion" and self._sesion_activa:
            self._salir_de_sesion(error.mensaje, "aviso")
            return True
        if error.tipo == "sin_conexion":
            self.marcar_conexion(False)
        return False

    def _al_token(self, token: str | None) -> None:
        # Llega desde el hilo de Auth: solo se reenvía a Realtime (no toca widgets).
        if self.realtime and token and self._sesion_activa:
            self.realtime.actualizar_token(token)

    # ============================================================ marco privado
    def _construir_marco(self) -> None:
        marco = ttk.Frame(self.raiz)

        lateral = ttk.Frame(marco, style="Lateral.TFrame", width=230)
        lateral.pack(side="left", fill="y")
        lateral.pack_propagate(False)
        ttk.Label(lateral, text="Ecosistema Bebé", style="Marca.TLabel").pack(anchor="w", padx=18, pady=(22, 20))
        self._botones_nav: dict[str, ttk.Button] = {}
        for clave, texto in NAVEGACION:
            b = ttk.Button(lateral, text=texto, style="Nav.TButton", command=lambda c=clave: self.navegar(c))
            b.pack(fill="x")
            self._botones_nav[clave] = b
        ttk.Button(lateral, text="⎋  Cerrar sesión", style="Nav.TButton",
                   command=self.cerrar_sesion).pack(side="bottom", fill="x", pady=(0, 16))

        derecha = ttk.Frame(marco)
        derecha.pack(side="left", fill="both", expand=True)

        encabezado = ttk.Frame(derecha, style="Encabezado.TFrame", padding=(20, 10))
        encabezado.pack(fill="x")
        ttk.Label(encabezado, text="Perfil:", style="Encabezado.TLabel").pack(side="left")
        self.selector_perfil = ttk.Combobox(encabezado, state="readonly", width=28, values=[TODOS_PERFILES])
        self.selector_perfil.set(TODOS_PERFILES)
        self.selector_perfil.pack(side="left", padx=(6, 18))
        self.selector_perfil.bind("<<ComboboxSelected>>", self._al_elegir_perfil)

        self.insignia_supabase = Insignia(encabezado, "Supabase: comprobando", "neutro")
        self.insignia_supabase.pack(side="left", padx=4)
        self.insignia_realtime = Insignia(encabezado, "En vivo: iniciando", "neutro")
        self.insignia_realtime.pack(side="left", padx=4)
        self.etq_actualizado = ttk.Label(encabezado, text="", style="Encabezado.TLabel",
                                         foreground=COLORES["texto_suave"])
        self.etq_actualizado.pack(side="left", padx=10)

        usuario = self.conexion.usuario
        ttk.Label(encabezado, text=f"👤 {usuario.correo if usuario else ''}", style="Encabezado.TLabel").pack(side="right")
        ttk.Button(encabezado, text="↻ Actualizar", command=lambda: self.recargar()).pack(side="right", padx=10)
        tk.Frame(derecha, height=1, bg=COLORES["borde"]).pack(fill="x")

        self.contenedor_avisos = ttk.Frame(derecha, padding=(20, 8, 20, 0))
        self.contenedor_avisos.pack(fill="x")
        self.aviso_telegram = Aviso(self.contenedor_avisos)
        self.aviso_global = Aviso(self.contenedor_avisos)
        self.notificacion = Aviso(self.contenedor_avisos)
        self._id_notificacion: str | None = None

        self.contenido = ttk.Frame(derecha)
        self.contenido.pack(fill="both", expand=True)
        self._mostrar(marco)
        self.navegar("panel")

    def navegar(self, clave: str, **parametros: Any) -> None:
        if not self._sesion_activa:
            self.mostrar_acceso("Inicie sesión para continuar.")
            return
        if self._actual and self._actual in self._pantallas:
            self._pantallas[self._actual].al_ocultar()
            self._pantallas[self._actual].pack_forget()
        pantalla = self._pantallas.get(clave)
        if pantalla is None:
            pantalla = self._crear_pantalla(clave)
            self._pantallas[clave] = pantalla
        self._actual = clave
        pantalla.pack(fill="both", expand=True)
        menu = "dispositivos" if clave == "detalle" else clave
        for c, b in self._botones_nav.items():
            b.configure(style="NavActivo.TButton" if c == menu else "Nav.TButton")
        pantalla.al_mostrar(**parametros)

    def _crear_pantalla(self, clave: str):
        from app.ui.pantallas.alertas import PantallaAlertas
        from app.ui.pantallas.alimentacion import PantallaAlimentacion
        from app.ui.pantallas.cuenta import PantallaCuenta
        from app.ui.pantallas.detalle import PantallaDetalle
        from app.ui.pantallas.dispositivos import PantallaDispositivos
        from app.ui.pantallas.galeria import PantallaGaleria
        from app.ui.pantallas.historial import PantallaHistorial
        from app.ui.pantallas.panel import PantallaPanel
        from app.ui.pantallas.perfiles import PantallaPerfiles

        clases = {
            "panel": PantallaPanel, "dispositivos": PantallaDispositivos, "detalle": PantallaDetalle,
            "perfiles": PantallaPerfiles, "alertas": PantallaAlertas, "historial": PantallaHistorial,
            "galeria": PantallaGaleria, "alimentacion": PantallaAlimentacion, "cuenta": PantallaCuenta,
        }
        return clases[clave](self.contenido, self)

    # ============================================================ datos y estado
    def recargar(self, primera: bool = False) -> None:
        if not self._sesion_activa or self._cargando:
            return
        self._cargando = True

        def listo(_):
            self.marcar_conexion(True)
            self._refrescar_encabezado()
            self._avisar_pantalla()

        def fallo(error: ErrorApp):
            if error.tipo == "sin_conexion":
                self.marcar_conexion(False)
            else:
                self.notificar(error.mensaje, "critico")

        def fin():
            self._cargando = False
            self._programar_polling()

        self.ejecutor.ejecutar(self.servicios.cargar_instantanea, listo, fallo, fin)

    def _avisar_pantalla(self) -> None:
        if self._actual and self._actual in self._pantallas:
            self._pantallas[self._actual].al_actualizar()

    def _refrescar_encabezado(self) -> None:
        if not self._sesion_activa:
            return
        inst = self.servicios.instantanea
        nombres = [TODOS_PERFILES] + [p["nombre"] for p in inst.perfiles]
        self._ids_perfil = [None] + [p["id"] for p in inst.perfiles]
        self.selector_perfil.configure(values=nombres)
        if self.perfil_seleccionado not in self._ids_perfil:
            self.perfil_seleccionado = None
        self.selector_perfil.current(self._ids_perfil.index(self.perfil_seleccionado))
        self.etq_actualizado.configure(text=f"Actualizado {formato_local(inst.cargada_en, True)}")

        # CA-37.2: aviso si no hay chat de Telegram vinculado.
        if inst.usuario is not None and not inst.usuario.get("telegram_chat_id"):
            self.aviso_telegram.mostrar("No recibirás alertas por Telegram. Vincule su chat en «Cuenta y Telegram».",
                                        "aviso")
        else:
            self.aviso_telegram.ocultar()

    def _al_elegir_perfil(self, _evento=None) -> None:
        indice = self.selector_perfil.current()
        self.perfil_seleccionado = self._ids_perfil[indice] if indice >= 0 else None
        self._avisar_pantalla()

    def seleccionar_perfil(self, perfil_id: str | None) -> None:
        self.perfil_seleccionado = perfil_id
        self._refrescar_encabezado()

    def marcar_conexion(self, conectado: bool) -> None:
        if not self._sesion_activa or self._conectado_supabase == conectado:
            self._conectado_supabase = conectado
            return
        self._conectado_supabase = conectado
        try:
            if conectado:
                self.insignia_supabase.cambiar("Supabase: conectado", "exito")
                self.aviso_global.ocultar()
            else:
                self.insignia_supabase.cambiar("Supabase: sin conexión", "critico")
                self.aviso_global.mostrar("Sin conexión con Supabase. Los datos mostrados pueden estar "
                                          "desactualizados; se reintentará automáticamente.", "critico")
        except tk.TclError:
            pass

    def _al_estado_realtime(self, estado: str, detalle: str) -> None:
        self._estado_realtime = estado
        if not self._sesion_activa:
            return
        textos = {
            "conectado": ("En vivo: activo", "exito"),
            "conectando": ("En vivo: conectando", "neutro"),
            "reconectando": ("En vivo: reconectando", "aviso"),
            "degradado": ("En vivo: degradado (consulta cada %d s)" % SEGUNDOS_POLLING_DEGRADADO, "aviso"),
            "detenido": ("En vivo: detenido", "neutro"),
        }
        texto, tono = textos.get(estado, (f"En vivo: {estado}", "neutro"))
        try:
            self.insignia_realtime.cambiar(texto, tono)
        except tk.TclError:
            return
        if estado == "conectado":
            self.recargar()  # Reconciliar lo que pudo cambiar mientras no había conexión.
        self._programar_polling()

    def _al_cambio_realtime(self, tabla: str, tipo: str, registro: dict, anterior: dict) -> None:
        if not self._sesion_activa:
            return
        if tabla == "alertas" and tipo == "INSERT" and registro.get("severidad") == "critica":
            self.notificar(f"ALERTA CRÍTICA: {registro.get('mensaje', '')}", "critico", segundos=20)
        if tabla == "dispositivos" and tipo == "UPDATE" and registro.get("perfil_id") != anterior.get("perfil_id", registro.get("perfil_id")):
            self.recargar()
            return
        if self.servicios.aplicar_cambio(tabla, tipo, registro, anterior):
            if self._actual and self._actual in self._pantallas:
                self._pantallas[self._actual].al_cambio(tabla, tipo, registro)

    # ============================================================ temporizadores
    def _programar_polling(self) -> None:
        if self._id_polling:
            self.raiz.after_cancel(self._id_polling)
            self._id_polling = None
        if not self._sesion_activa:
            return
        segundos = SEGUNDOS_POLLING_NORMAL if self._estado_realtime == "conectado" else SEGUNDOS_POLLING_DEGRADADO
        self._id_polling = self.raiz.after(segundos * 1000, self.recargar)

    def _programar_reloj(self) -> None:
        """Cada 5 s repinta estados dependientes del tiempo (fuera de línea a los 60 s)."""
        if not self._sesion_activa:
            return
        if self._actual in {"panel", "dispositivos", "detalle"} and self._actual in self._pantallas:
            pantalla = self._pantallas[self._actual]
            if hasattr(pantalla, "al_reloj"):
                pantalla.al_reloj()
        self._id_reloj = self.raiz.after(5000, self._programar_reloj)

    def _detener_temporizadores(self) -> None:
        for ident in (self._id_polling, self._id_reloj):
            if ident:
                try:
                    self.raiz.after_cancel(ident)
                except tk.TclError:
                    pass
        self._id_polling = self._id_reloj = None

    # ============================================================ notificaciones
    def notificar(self, texto: str, tono: str = "info", segundos: int = 6) -> None:
        if not self._sesion_activa:
            return
        try:
            self.notificacion.mostrar(texto, tono)
        except tk.TclError:
            return
        if self._id_notificacion:
            self.raiz.after_cancel(self._id_notificacion)
        self._id_notificacion = self.raiz.after(segundos * 1000, self.notificacion.ocultar)

    # ================================================================== cierre
    def cerrar(self) -> None:
        self._sesion_activa = False
        self._detener_temporizadores()
        if self.realtime:
            self.realtime.detener(espera_s=2)
        self.ejecutor.cerrar()
        self.raiz.destroy()
