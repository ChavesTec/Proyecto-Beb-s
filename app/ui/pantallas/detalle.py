"""Detalle de un dispositivo: lecturas, configuración, órdenes, alertas y eventos."""
from __future__ import annotations

from tkinter import messagebox, ttk

from app.config.valores import COMANDOS_POR_TIPO, NOMBRES_COMANDO, NOMBRES_TIPO
from app.config.zona import formato_local, hace_cuanto
from app.services import dominio
from app.ui.base import Pantalla
from app.ui.pantallas.paneles import PANELES
from app.ui.pantallas.tarjeta import TONO_CONEXION
from app.ui.widgets import Aviso, Insignia, MarcoDesplazable, Tabla


class PantallaDetalle(Pantalla):
    titulo = "Detalle"

    def __init__(self, padre, app):
        super().__init__(padre, app)
        self.dispositivo_id: str | None = None
        self.panel = None
        self._comandos: list[dict] = []
        self._vigilados: dict[int, str] = {}  # comando_id -> tipo (para avisar el resultado)

        cabeza = ttk.Frame(self)
        cabeza.pack(fill="x")
        ttk.Button(cabeza, text="← Volver", command=lambda: self.app.navegar("panel")).pack(side="left")
        self.titulo_lbl = ttk.Label(cabeza, text="", style="Titulo.TLabel")
        self.titulo_lbl.pack(side="left", padx=14)
        self.conexion = Insignia(cabeza, "", "neutro")
        self.conexion.pack(side="left")
        self.permiso = Insignia(cabeza, "", "neutro")
        self.permiso.pack(side="left", padx=8)
        self.subtitulo = ttk.Label(self, style="Suave.TLabel")
        self.subtitulo.pack(anchor="w", pady=(4, 8))
        self.aviso = Aviso(self)

        self.marco = MarcoDesplazable(self)
        self.marco.pack(fill="both", expand=True)
        cuerpo = self.marco.interior

        self.caja_lecturas = ttk.LabelFrame(cuerpo, text="Estado y lecturas en vivo", padding=12)
        self.caja_lecturas.pack(fill="x", pady=(0, 12))
        self.lecturas = ttk.Label(self.caja_lecturas, style="Tarjeta.TLabel", justify="left")
        self.lecturas.pack(anchor="w")

        self.contenedor_panel = ttk.Frame(cuerpo)
        self.contenedor_panel.pack(fill="x")

        self.caja_ordenes = ttk.LabelFrame(cuerpo, text="Órdenes al dispositivo", padding=12)
        self.caja_ordenes.pack(fill="x", pady=(12, 12))
        ttk.Label(self.caja_ordenes, text="Una orden queda «Pendiente» hasta que el dispositivo la marque como "
                                          "ejecutada o fallida.", style="TarjetaSuave.TLabel").pack(anchor="w")
        self.botones_ordenes = ttk.Frame(self.caja_ordenes, style="Tarjeta.TFrame")
        self.botones_ordenes.pack(fill="x", pady=6)
        self.tabla_ordenes = Tabla(self.caja_ordenes, [("orden", "Orden", 260), ("estado", "Estado", 380),
                                                       ("creada", "Enviada", 140), ("ejecutada", "Respuesta", 140)], alto=5)
        self.tabla_ordenes.pack(fill="x")

        self.caja_alertas = ttk.LabelFrame(cuerpo, text="Alertas recientes", padding=12)
        self.caja_alertas.pack(fill="x", pady=(0, 12))
        self.tabla_alertas = Tabla(self.caja_alertas, [("fecha", "Fecha", 130), ("sev", "Gravedad", 100),
                                                       ("mensaje", "Mensaje", 560), ("envio", "Telegram", 170)], alto=5)
        self.tabla_alertas.pack(fill="x")

        self.caja_eventos = ttk.LabelFrame(cuerpo, text="Eventos recientes (historial)", padding=12)
        self.caja_eventos.pack(fill="x")
        self.tabla_eventos = Tabla(self.caja_eventos, [("fecha", "Fecha y hora", 150), ("tipo", "Tipo", 150),
                                                       ("valor", "Valor", 110), ("desc", "Descripción", 480)], alto=6)
        self.tabla_eventos.pack(fill="x")

    # ------------------------------------------------------------ ciclo de vida
    def al_mostrar(self, dispositivo_id: str | None = None, **_):
        if dispositivo_id and dispositivo_id != self.dispositivo_id:
            self.dispositivo_id = dispositivo_id
            self._vigilados.clear()
            self._construir_panel()
            self.marco.arriba()
        self._pintar()
        self._cargar_extra()

    def al_actualizar(self):
        self._pintar()

    def al_cambio(self, tabla, tipo, registro):
        if tabla == "comandos" and registro.get("dispositivo_id") == self.dispositivo_id:
            self._al_comando(registro)
            return
        if tabla == "alertas" and registro.get("dispositivo_id") == self.dispositivo_id:
            self._cargar_alertas()
        if tabla in {"dispositivos", "configuracion"}:
            self._pintar()

    def al_reloj(self):
        self._pintar(solo_estado=True)
        if any(c.get("estado") == "pendiente" for c in self._comandos):
            self._cargar_comandos()  # Respaldo por si Realtime no entrega la actualización.

    # ----------------------------------------------------------------- pintar
    def _dispositivo(self) -> dict | None:
        return self.servicios.instantanea.dispositivo(self.dispositivo_id) if self.dispositivo_id else None

    def _construir_panel(self):
        for hijo in self.contenedor_panel.winfo_children():
            hijo.destroy()
        for hijo in self.botones_ordenes.winfo_children():
            hijo.destroy()
        d = self._dispositivo()
        if not d:
            self.panel = None
            return
        clase = PANELES.get(d["tipo"])
        self.panel = clase(self.contenedor_panel, self, d) if clase else None
        if self.panel:
            self.panel.pack(fill="x")
        manejados = getattr(self.panel, "COMANDOS_PROPIOS", ())
        self._botones_cmd = []
        for tipo in COMANDOS_POR_TIPO.get(d["tipo"], ()):
            if tipo in manejados:
                continue
            b = ttk.Button(self.botones_ordenes, text=NOMBRES_COMANDO[tipo], command=lambda t=tipo: self.enviar_comando(t))
            b.pack(side="left", padx=(0, 8))
            self._botones_cmd.append(b)

    def _pintar(self, solo_estado: bool = False):
        d = self._dispositivo()
        if not d:
            self.titulo_lbl.configure(text="Dispositivo no disponible")
            self.aviso.mostrar("El dispositivo no existe o ya no tiene acceso a él.", "aviso", before=self.marco)
            return
        inst = self.servicios.instantanea
        config = inst.configuraciones.get(d["id"])
        estado = dominio.estado_conexion(d)
        puede = self.servicios.puede_controlar(d)
        self.titulo_lbl.configure(text=d.get("nombre") or NOMBRES_TIPO[d["tipo"]])
        self.conexion.cambiar(dominio.NOMBRES_CONEXION[estado], TONO_CONEXION[estado])
        self.permiso.cambiar("Puede controlar" if puede else "Solo lectura", "info" if puede else "neutro")
        self.subtitulo.configure(text=f"{NOMBRES_TIPO[d['tipo']]} · código {d['codigo']} · perfil: "
                                      f"{inst.nombre_perfil(d.get('perfil_id'))} · última señal "
                                      f"{formato_local(d.get('ultima_senal_en'), True)} ({hace_cuanto(d.get('ultima_senal_en'))})")
        advertencia = dominio.advertencia_critica_desconexion(d, config, estado)
        if advertencia:
            registrada = self.servicios.alerta_fuera_de_linea_registrada(d)
            self.aviso.mostrar(advertencia + (" La base registró la alerta «fuera de línea»." if registrada else
                                              " La base la registrará al cumplirse 60 s sin señal."),
                               "critico", before=self.marco)
        elif estado == dominio.FUERA_DE_LINEA:
            self.aviso.mostrar("Dispositivo fuera de línea: las lecturas mostradas pueden no ser actuales y las "
                               "órdenes quedarán pendientes hasta que vuelva.", "aviso", before=self.marco)
        elif estado == dominio.SIN_DATOS:
            self.aviso.mostrar("Este dispositivo nunca ha enviado señal: no hay lecturas para mostrar.",
                               "info", before=self.marco)
        else:
            self.aviso.ocultar()

        lecturas = dominio.lecturas_de(d)
        texto = "\n".join(f"{l.etiqueta}: {l.valor}" for l in lecturas) or "El dispositivo no ha enviado lecturas en vivo."
        self.lecturas.configure(text=texto)
        if solo_estado:
            return
        for b in getattr(self, "_botones_cmd", []):
            b.configure(state="normal" if puede else "disabled")
        if self.panel:
            self.panel.pintar(d, config, puede)

    # ------------------------------------------------------------- datos extra
    def _cargar_extra(self):
        self._cargar_comandos()
        self._cargar_alertas()
        self._cargar_eventos()
        if self.panel:
            self.panel.cargar()

    def _cargar_comandos(self):
        ident = self.dispositivo_id
        if not ident:
            return

        def ok(filas):
            if ident != self.dispositivo_id:
                return
            for c in filas:
                self._revisar_vigilado(c)
            self._comandos = filas
            self._pintar_comandos()
        self.tarea(lambda: self.servicios.dispositivos.comandos_recientes(ident), ok, al_fallar=lambda e: None)

    def _pintar_comandos(self):
        filas = []
        for c in self._comandos:
            tono = ("critica",) if c.get("estado") == "fallido" else (("aviso",) if c.get("estado") == "pendiente" else ())
            filas.append((str(c["id"]), (NOMBRES_COMANDO.get(c["tipo"], c["tipo"]), dominio.describir_comando(c),
                                         formato_local(c.get("creado_en"), True),
                                         formato_local(c.get("ejecutado_en"), True)), tono))
        self.tabla_ordenes.llenar(filas or [("vacio", ("Sin órdenes recientes", "", "", ""), ())])

    def _al_comando(self, registro: dict):
        self._revisar_vigilado(registro)
        self._comandos = [registro] + [c for c in self._comandos if c["id"] != registro.get("id")]
        self._comandos.sort(key=lambda c: c.get("creado_en") or "", reverse=True)
        self._comandos = self._comandos[:10]
        self._pintar_comandos()
        if self.panel:
            self.panel.al_comando(registro)

    def _revisar_vigilado(self, c: dict):
        tipo = self._vigilados.get(c.get("id"))
        if not tipo or c.get("estado") == "pendiente":
            return
        del self._vigilados[c["id"]]
        nombre = NOMBRES_COMANDO.get(tipo, tipo)
        if c.get("estado") == "fallido":
            # CA-15.2: se muestra exactamente el resultado devuelto por el dispositivo.
            messagebox.showwarning(nombre, c.get("resultado") or "El dispositivo no pudo ejecutar la orden.", parent=self)
        else:
            self.app.notificar(f"{nombre}: ejecutado por el dispositivo.", "exito")

    def _cargar_alertas(self):
        ident = self.dispositivo_id

        def ok(filas):
            if ident != self.dispositivo_id:
                return
            self.tabla_alertas.llenar([
                (str(a["id"]), (formato_local(a["creada_en"]), dominio.NOMBRES_SEVERIDAD.get(a["severidad"], a["severidad"]),
                                a["mensaje"], dominio.NOMBRES_ESTADO_ALERTA.get(a["estado"], a["estado"])),
                 ("critica",) if a["severidad"] == "critica" else ())
                for a in filas] or [("vacio", ("", "", "Sin alertas registradas", ""), ())])
            if self.panel:
                self.panel.al_alertas(filas)
        self.tarea(lambda: self.servicios.historial.alertas_dispositivo(ident, 15), ok, al_fallar=lambda e: None)

    def _cargar_eventos(self):
        ident = self.dispositivo_id

        def ok(filas):
            if ident != self.dispositivo_id:
                return
            self.tabla_eventos.llenar([
                (str(e["id"]), (e["fecha_hora"], e["tipo"],
                                "" if e.get("valor") is None else f"{e['valor']} {e.get('unidad') or ''}",
                                e.get("descripcion") or ""), ())
                for e in filas] or [("vacio", ("", "Sin eventos registrados", "", ""), ())])
            if self.panel:
                self.panel.al_eventos(filas)
        self.tarea(lambda: self.servicios.historial.eventos_dispositivo(ident, limite=25), ok, al_fallar=lambda e: None)

    # ----------------------------------------------------------------- acciones
    def enviar_comando(self, tipo: str, parametros: dict | None = None, boton: ttk.Button | None = None):
        d = self._dispositivo()
        if not d:
            return
        if dominio.estado_conexion(d) != dominio.EN_LINEA and not self.confirmar(
                "Dispositivo sin conexión", "El dispositivo no está en línea. La orden quedará pendiente hasta "
                                            "que se conecte. ¿Enviarla de todos modos?"):
            return

        def ok(c):
            self._vigilados[c["id"]] = tipo
            self._al_comando(c)
            self.app.notificar(f"Orden «{NOMBRES_COMANDO.get(tipo, tipo)}» enviada; esperando al dispositivo.", "info")

        self.tarea(lambda: self.servicios.dispositivos.enviar_comando(d["id"], tipo, parametros), ok, boton=boton)

    def guardar_configuracion(self, cambios: dict, boton: ttk.Button | None = None, exito: str = "Configuración guardada."):
        d = self._dispositivo()
        if not d:
            return

        def ok(fila):
            self.servicios.aplicar_cambio("configuracion", "UPDATE", fila, {})
            self._pintar()
            self.app.notificar(exito + " El dispositivo la recibe por Realtime.", "exito")

        self.tarea(lambda: self.servicios.dispositivos.actualizar_configuracion(d["id"], cambios), ok, boton=boton)
