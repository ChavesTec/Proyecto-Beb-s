"""Paneles específicos de los seis tipos de dispositivo (EP03-EP08).

Solo se ofrecen controles que existen en el esquema: columnas de `configuracion`,
tipos permitidos de `comandos`, `horarios` y las RPC. Lo que depende de firmware
no presente en el repositorio se indica en pantalla en lugar de simularlo.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from app.config.valores import MAX_SECUENCIAS_MOVIL, PREDETERMINADOS
from app.config.zona import formato_local, hace_cuanto
from app.errores import ErrorValidacion
from app.services import dominio
from app.ui.estilos import COLORES
from app.ui.pantallas.horarios import EditorHorarios
from app.ui.pantallas.tarjeta import g
from app.ui.widgets import Insignia, Tabla, habilitar, poner_texto


class PanelTipo(ttk.Frame):
    COMANDOS_PROPIOS: tuple[str, ...] = ()

    def __init__(self, padre, pantalla, dispositivo: dict):
        super().__init__(padre)
        self.pantalla = pantalla
        self.servicios = pantalla.servicios
        self.d = dispositivo
        self._controles: list[tk.Widget] = []

    # Ganchos del detalle -------------------------------------------------
    def cargar(self) -> None: ...
    def pintar(self, d: dict, config: dict | None, puede: bool) -> None:
        self.d = d
        habilitar(self._controles, puede)
    def al_comando(self, comando: dict) -> None: ...
    def al_alertas(self, alertas: list[dict]) -> None: ...
    def al_eventos(self, eventos: list[dict]) -> None: ...

    # Utilidades ----------------------------------------------------------
    def caja(self, titulo: str) -> ttk.LabelFrame:
        caja = ttk.LabelFrame(self, text=titulo, padding=12)
        caja.pack(fill="x", pady=(0, 12))
        return caja

    def entrada(self, padre, etiqueta: str, fila: int, columna: int = 0, ancho: int = 8) -> ttk.Entry:
        ttk.Label(padre, text=etiqueta, style="Tarjeta.TLabel").grid(row=fila, column=columna, sticky="w", padx=(0, 6), pady=3)
        e = ttk.Entry(padre, width=ancho)
        e.grid(row=fila, column=columna + 1, sticky="w", padx=(0, 18), pady=3)
        self._controles.append(e)
        return e

    def boton(self, padre, texto: str, comando, estilo: str = "TButton", **grid) -> ttk.Button:
        b = ttk.Button(padre, text=texto, style=estilo, command=comando)
        if grid:
            b.grid(**grid)
        self._controles.append(b)
        return b

    def origen(self, config, *columnas) -> str:
        base = PREDETERMINADOS.get(self.d["tipo"], {})
        origenes = {dominio.origen_valor(config, c, base) for c in columnas}
        if origenes == {"predeterminado"}:
            return "Valores predeterminados (no configurados por el usuario)"
        if "sin datos" in origenes:
            return "Sin configuración leída"
        return "Valores guardados por el usuario"

    def guardar(self, cambios: dict, boton=None, exito="Configuración guardada."):
        self.pantalla.guardar_configuracion(cambios, boton, exito)


# ============================================================== cuna (EP03)
class PanelCuna(PanelTipo):
    COMANDOS_PROPIOS = ("audio_reproducir", "audio_detener")

    def __init__(self, padre, pantalla, d):
        super().__init__(padre, pantalla, d)
        caja = self.caja("Umbrales de temperatura y humedad (HU-09)")
        self.t_min = self.entrada(caja, "Temp. mínima (°C)", 0, 0)
        self.t_max = self.entrada(caja, "Temp. máxima (°C)", 0, 2)
        self.h_min = self.entrada(caja, "Humedad mínima (%)", 1, 0)
        self.h_max = self.entrada(caja, "Humedad máxima (%)", 1, 2)
        self.rep = self.entrada(caja, "Repetir alerta cada (min)", 2, 0)
        self.btn_umbrales = self.boton(caja, "Guardar umbrales", self._guardar_umbrales, "Primario.TButton",
                                       row=2, column=2, columnspan=2, sticky="w")
        self.lbl_origen = ttk.Label(caja, style="TarjetaSuave.TLabel")
        self.lbl_origen.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

        luz = self.caja("Luz nocturna (HU-11)")
        self.var_luz = tk.IntVar(value=0)
        self.escala = ttk.Scale(luz, from_=0, to=100, orient="horizontal", length=320,
                                command=lambda v: self.lbl_luz.configure(text=f"{int(float(v))} %"))
        self.escala.grid(row=0, column=0, padx=(0, 10))
        self.lbl_luz = ttk.Label(luz, text="0 %", style="Tarjeta.TLabel", width=16)
        self.lbl_luz.grid(row=0, column=1)
        self.btn_luz = self.boton(luz, "Aplicar intensidad", self._guardar_luz, "Primario.TButton", row=0, column=2, padx=8)
        self.btn_apagar = self.boton(luz, "Apagar (0 %)", lambda: self._guardar_luz(0), row=0, column=3)
        self._controles.append(self.escala)
        ttk.Label(luz, text="0 % apaga la luz. La cuna aplica la última intensidad guardada al reiniciarse.",
                  style="TarjetaSuave.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        self.horarios = EditorHorarios(self, pantalla, d["id"], "movimiento",
                                       "Ventana de vigilancia de movimiento (HU-10)",
                                       "Fuera de estas ventanas la base descarta el movimiento (no se guarda ni alerta). "
                                       "Sin ninguna ventana activa, no se registra movimiento.")
        self.horarios.pack(fill="x", pady=(0, 12))

        audio = self.caja("Audios de la cuna (HU-13)")
        self.tabla_audios = Tabla(audio, [("nombre", "Nombre", 300), ("tamano", "Tamaño", 90), ("fecha", "Subido", 140)], alto=4)
        self.tabla_audios.grid(row=0, column=0, columnspan=5, sticky="we")
        audio.columnconfigure(0, weight=1)
        self.btn_subir = self.boton(audio, "Subir MP3…", self._subir, row=1, column=0, sticky="w", pady=(8, 0))
        self.btn_reproducir = self.boton(audio, "▶ Reproducir en la cuna", self._reproducir, "Primario.TButton",
                                         row=1, column=1, pady=(8, 0), padx=6)
        self.btn_detener = self.boton(audio, "■ Detener", lambda: self.pantalla.enviar_comando("audio_detener"),
                                      row=1, column=2, pady=(8, 0))
        self.btn_borrar = self.boton(audio, "Borrar audio", self._borrar_audio, row=1, column=3, pady=(8, 0), padx=6)
        ttk.Label(audio, text="Solo MP3 de hasta 5 MB. Los audios son de su cuenta y la cuna los descarga con URL firmada.",
                  style="TarjetaSuave.TLabel").grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))
        self._audios: list[dict] = []

        voz = self.caja("Hablar al bebé (HU-12)")
        ttk.Label(voz, text="No disponible en esta versión: el repositorio no contiene el firmware de la cuna ni el canal "
                            "de audio en vivo (Realtime Broadcast) que la arquitectura prevé. No se muestra un botón "
                            "«Hablar» que no transmita voz. La transmisión desde la cuna hacia la app está fuera del alcance.",
                  style="TarjetaSuave.TLabel", wraplength=760, justify="left").pack(anchor="w")

    def cargar(self):
        self.horarios.cargar()
        self._cargar_audios()

    def pintar(self, d, config, puede):
        super().pintar(d, config, puede)
        self.horarios.permitir(puede)
        if not config:
            return
        for e, c in ((self.t_min, "temp_min"), (self.t_max, "temp_max"), (self.h_min, "hum_min"),
                     (self.h_max, "hum_max"), (self.rep, "alerta_repeticion_min")):
            if self.focus_get() is not e:
                poner_texto(e, g(config.get(c)))
        self.lbl_origen.configure(text=self.origen(config, "temp_min", "temp_max", "hum_min", "hum_max",
                                                   "alerta_repeticion_min")
                                  + f" · activos: {g(config['temp_min'])}–{g(config['temp_max'])} °C, "
                                    f"{g(config['hum_min'])}–{g(config['hum_max'])} %")
        self.escala.set(int(config.get("luz_intensidad") or 0))
        self.lbl_luz.configure(text=f"{int(config.get('luz_intensidad') or 0)} % (guardado)")

    def _guardar_umbrales(self):
        try:
            t_min, t_max = dominio.validar_rango(self.t_min.get(), self.t_max.get(), "temperatura")
            h_min, h_max = dominio.validar_rango(self.h_min.get(), self.h_max.get(), "humedad", 0, 100)
            rep = dominio.validar_entero(self.rep.get(), "la repetición", minimo=1, maximo=1440)
        except ErrorValidacion as e:
            self.pantalla.mostrar_error(e)
            return
        self.guardar({"temp_min": t_min, "temp_max": t_max, "hum_min": h_min, "hum_max": h_max,
                      "alerta_repeticion_min": rep}, self.btn_umbrales, "Umbrales guardados.")

    def _guardar_luz(self, valor: int | None = None):
        nivel = int(round(self.escala.get())) if valor is None else valor
        self.guardar({"luz_intensidad": max(0, min(100, nivel))}, self.btn_luz,
                     "Luz apagada." if nivel == 0 else f"Luz nocturna al {nivel} %.")

    def _cargar_audios(self):
        def ok(filas):
            self._audios = filas
            self.tabla_audios.llenar([(a["id"], (a["nombre"], f"{a['tamano_bytes'] / 1048576:.2f} MB",
                                                 formato_local(a["creado_en"])), ()) for a in filas]
                                     or [("vacio", ("No hay audios subidos.", "", ""), ())])
        self.pantalla.tarea(self.servicios.cuenta.audios, ok, al_fallar=lambda e: None)

    def _subir(self):
        ruta = filedialog.askopenfilename(parent=self, title="Elegir MP3",
                                          filetypes=[("Audio MP3", "*.mp3"), ("Todos los archivos", "*.*")])
        if not ruta:
            return
        archivo = Path(ruta)
        try:
            tamano = archivo.stat().st_size
            with archivo.open("rb") as f:
                cabecera = f.read(4)
            dominio.validar_mp3(archivo.name, tamano, cabecera)
        except ErrorValidacion as e:
            self.pantalla.mostrar_error(e)
            return
        except OSError:
            self.pantalla.mostrar_error(ErrorValidacion("No se pudo leer el archivo."))
            return
        contenido = archivo.read_bytes()
        self.pantalla.tarea(lambda: self.servicios.cuenta.subir_audio(archivo.stem, archivo.name, contenido),
                            lambda _: self._cargar_audios(), boton=self.btn_subir, exito=f"«{archivo.stem}» agregado a la lista.")

    def _audio_sel(self) -> dict | None:
        iid = self.tabla_audios.seleccion()
        a = next((a for a in self._audios if a["id"] == iid), None)
        if not a:
            self.pantalla.mostrar_error(ErrorValidacion("Seleccione un audio de la lista."))
        return a

    def _reproducir(self):
        a = self._audio_sel()
        if a:
            # Parámetros propuestos para el firmware (no hay firmware en el repo para confirmarlos).
            self.pantalla.enviar_comando("audio_reproducir", {"audio_id": a["id"], "archivo_path": a["archivo_path"],
                                                              "nombre": a["nombre"]}, self.btn_reproducir)

    def _borrar_audio(self):
        a = self._audio_sel()
        if a and self.pantalla.confirmar("Borrar audio", f"¿Borrar «{a['nombre']}»?"):
            self.pantalla.tarea(lambda: self.servicios.cuenta.borrar_audio(a), lambda _: self._cargar_audios(),
                                exito="Audio borrado.")


# =========================================================== colchón (EP04)
class PanelColchon(PanelTipo):
    COMANDOS_PROPIOS = ("activar_siesta",)

    def __init__(self, padre, pantalla, d):
        super().__init__(padre, pantalla, d)
        estado = self.caja("Modo siesta y alarma anti-robo (HU-15 a HU-19)")
        fila = ttk.Frame(estado, style="Tarjeta.TFrame")
        fila.pack(fill="x")
        izquierda = ttk.Frame(fila, style="Tarjeta.TFrame")
        izquierda.pack(side="left", fill="x", expand=True)
        self.lbl_peso = ttk.Label(izquierda, style="Grande.TLabel", text="— g")
        self.lbl_peso.pack(anchor="w")
        self.lbl_alimentacion = ttk.Label(izquierda, style="TarjetaSuave.TLabel")
        self.lbl_alimentacion.pack(anchor="w")
        self.insignia = Insignia(izquierda, "Modo siesta: —", "neutro")
        self.insignia.pack(anchor="w", pady=6)
        self.lbl_snapshot = ttk.Label(izquierda, style="Tarjeta.TLabel", justify="left")
        self.lbl_snapshot.pack(anchor="w")
        botones = ttk.Frame(fila, style="Tarjeta.TFrame")
        botones.pack(side="right")
        self.btn_activar = ttk.Button(botones, text="Activar modo siesta", style="GrandePrimario.TButton",
                                      command=self._activar)
        self.btn_activar.pack(fill="x")
        self.btn_desactivar = ttk.Button(botones, text="Desactivar modo siesta", style="GrandePeligro.TButton",
                                         command=self._desactivar)
        self.btn_desactivar.pack(fill="x", pady=(8, 0))
        self._controles += [self.btn_activar, self.btn_desactivar]
        self.lbl_resultado = ttk.Label(estado, style="Tarjeta.TLabel", foreground=COLORES["critico"])
        self.lbl_resultado.pack(anchor="w", pady=(8, 0))
        ttk.Label(estado, text="La alarma sonora anti-robo se decide y suena en el propio colchón, aunque no haya "
                               "internet o la cuna esté apagada. Esta app solo supervisa y envía órdenes; no la sustituye.",
                  style="TarjetaSuave.TLabel", wraplength=760, justify="left").pack(anchor="w", pady=(8, 0))

        self.alarmas = self.caja("Alarmas anti-robo recientes")
        self.tabla_alarmas = Tabla(self.alarmas, [("fecha", "Fecha", 130), ("mensaje", "Mensaje", 470),
                                                  ("desactivada", "Desactivada", 220)], alto=4)
        self.tabla_alarmas.pack(fill="x")

        ajustes = self.caja("Ajustes del colchón")
        self.peso_min = self.entrada(ajustes, "Peso mínimo para la siesta (g)", 0, 0)
        self.caida = self.entrada(ajustes, "Caída de peso para la alarma (%)", 0, 2)
        self.btn_ajustes = self.boton(ajustes, "Guardar ajustes", self._guardar, "Primario.TButton", row=1, column=0,
                                      columnspan=2, sticky="w", pady=(6, 0))
        self.lbl_origen = ttk.Label(ajustes, style="TarjetaSuave.TLabel")
        self.lbl_origen.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self._snapshot: dict | None = None
        self._config: dict | None = None
        self._peso_historial: dict | None = None

    def cargar(self):
        ident = self.d["id"]
        self.pantalla.tarea(lambda: self.servicios.dispositivos.ultimo_snapshot(ident), self._al_snapshot,
                            al_fallar=lambda e: None)

    def _al_snapshot(self, snap):
        self._snapshot = snap
        self._pintar_snapshot()

    def _pintar_snapshot(self):
        s = self._snapshot
        activa = bool(self._config and self._config.get("siesta_activa"))
        if s and s.get("desactivado_en") is None:
            self.lbl_snapshot.configure(text=f"Peso base (snapshot): {g(s['peso_base_g'])} g · tomado "
                                             f"{formato_local(s['creado_en'], True)}")
        elif s:
            quien = "usted" if s.get("desactivado_por") == self.servicios.usuario_id else "otro usuario con permiso"
            self.lbl_snapshot.configure(text=f"Última siesta: base {g(s['peso_base_g'])} g, "
                                             f"{formato_local(s['creado_en'])} → desactivada {formato_local(s['desactivado_en'])} por {quien}")
        else:
            self.lbl_snapshot.configure(text="Sin siestas registradas.")
        if activa and not (s and s.get("desactivado_en") is None):
            self.lbl_snapshot.configure(text="Modo siesta activo; cargando snapshot…")

    def pintar(self, d, config, puede):
        super().pintar(d, config, puede)
        self._config = config
        peso = dominio.valor_lectura(d, "peso", "peso_g")
        if peso is not None:
            self.lbl_peso.configure(text=f"{g(peso)} g")
        else:
            ev = self.servicios.instantanea.lecturas_historial.get(d["id"], {}).get("peso")
            self.lbl_peso.configure(text=f"{g(ev['valor'])} g ({hace_cuanto(ev['ocurrido_en'])})" if ev else "Peso: sin datos")
        self.lbl_alimentacion.configure(text=dominio.conexion_colchon(d))
        activa = bool(config and config.get("siesta_activa"))
        self.insignia.cambiar("Modo siesta: ACTIVO" if activa else "Modo siesta: inactivo", "aviso" if activa else "neutro")
        self.btn_activar.configure(state="normal" if puede and not activa else "disabled")
        self.btn_desactivar.configure(state="normal" if puede and activa else "disabled")
        if config:
            for e, c in ((self.peso_min, "peso_minimo_g"), (self.caida, "alarma_caida_pct")):
                if self.focus_get() is not e:
                    poner_texto(e, g(config.get(c)))
            self.lbl_origen.configure(text=self.origen(config, "peso_minimo_g", "alarma_caida_pct"))
        if activa != getattr(self, "_ultima_activa", None):
            self._ultima_activa = activa
            self.cargar()  # Cambió el modo siesta: el snapshot vigente también.
        self._pintar_snapshot()

    def _activar(self):
        if not self.d.get("perfil_id"):
            self.pantalla.mostrar_error(ErrorValidacion("Asigne el colchón a un perfil antes de activar el modo siesta."))
            return
        self.lbl_resultado.configure(text="")
        self.pantalla.enviar_comando("activar_siesta", None, self.btn_activar)

    def al_comando(self, c):
        if c.get("tipo") == "activar_siesta":
            if c.get("estado") == "fallido":
                self.lbl_resultado.configure(text=f"⛔ No se activó: {c.get('resultado') or 'sin detalle'}")
            elif c.get("estado") == "ejecutado":
                self.lbl_resultado.configure(text="")
                self.cargar()

    def _desactivar(self):
        if not self.pantalla.confirmar("Desactivar modo siesta",
                                       "Se apagará la alarma del colchón y quedará registrado quién y cuándo la "
                                       "desactivó. ¿Continuar?"):
            return

        def ok(_):
            self.servicios.aplicar_cambio("configuracion", "UPDATE",
                                          {**(self._config or {}), "dispositivo_id": self.d["id"], "siesta_activa": False}, {})
            self.pantalla._pintar()
            self.pantalla._cargar_comandos()
            self.pantalla._cargar_alertas()
            self.cargar()

        self.pantalla.tarea(lambda: self.servicios.dispositivos.desactivar_siesta(self.d["id"]), ok,
                            boton=self.btn_desactivar, exito="Modo siesta desactivado. Se envió la orden de apagar el buzzer.")

    def al_alertas(self, alertas):
        filas = []
        for a in alertas:
            if a["tipo"] != "antirrobo":
                continue
            if a.get("desactivada_en"):
                quien = "usted" if a.get("desactivada_por") == self.servicios.usuario_id else "otro usuario"
                desact = f"{formato_local(a['desactivada_en'])} por {quien}"
            else:
                desact = "Sin desactivar"
            filas.append((str(a["id"]), (formato_local(a["creada_en"]), a["mensaje"], desact), ("critica",)))
        self.tabla_alarmas.llenar(filas or [("vacio", ("", "Sin alarmas anti-robo registradas", ""), ())])

    def _guardar(self):
        try:
            peso = dominio.validar_decimal(self.peso_min.get(), "el peso mínimo", minimo=0, maximo=50000)
            caida = dominio.validar_decimal(self.caida.get(), "la caída de peso", minimo=0, maximo=100, minimo_exclusivo=True)
        except ErrorValidacion as e:
            self.pantalla.mostrar_error(e)
            return
        self.guardar({"peso_minimo_g": peso, "alarma_caida_pct": caida}, self.btn_ajustes, "Ajustes del colchón guardados.")


# ============================================================= móvil (EP05)
class PanelMovil(PanelTipo):
    def __init__(self, padre, pantalla, d):
        super().__init__(padre, pantalla, d)
        caja = self.caja("Móvil de luces (HU-20, HU-21)")
        self.insignia = Insignia(caja, "—", "neutro")
        self.insignia.grid(row=0, column=0, sticky="w")
        self.btn_encender = self.boton(caja, "Encender", lambda: self._encender(True), "Primario.TButton", row=0, column=1, padx=8)
        self.btn_apagar = self.boton(caja, "Apagar", lambda: self._encender(False), row=0, column=2)
        ttk.Label(caja, text="Secuencia", style="Tarjeta.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.secuencia = ttk.Combobox(caja, state="readonly", width=16,
                                      values=[f"Secuencia {i}" for i in range(1, MAX_SECUENCIAS_MOVIL + 1)])
        self.secuencia.grid(row=1, column=1, sticky="w", pady=(10, 0))
        self.secuencia.bind("<<ComboboxSelected>>", lambda e: self.guardar(
            {"movil_secuencia": self.secuencia.current() + 1}, exito="Secuencia elegida."))
        self._controles.append(self.secuencia)
        ttk.Label(caja, text="Velocidad", style="Tarjeta.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.var_vel = tk.IntVar(value=2)
        fila = ttk.Frame(caja, style="Tarjeta.TFrame")
        fila.grid(row=2, column=1, columnspan=3, sticky="w", pady=(10, 0))
        for valor, texto in ((1, "Lenta"), (2, "Media"), (3, "Rápida")):
            r = ttk.Radiobutton(fila, text=texto, value=valor, variable=self.var_vel, style="Tarjeta.TRadiobutton",
                                command=lambda: self.guardar({"movil_velocidad": self.var_vel.get()}, exito="Velocidad cambiada."))
            r.pack(side="left", padx=(0, 10))
            self._controles.append(r)
        ttk.Label(caja, text=f"Las secuencias las define el firmware del móvil; la base admite cualquier número ≥ 1 "
                             f"(aquí 1 a {MAX_SECUENCIAS_MOVIL}). Cambiar la velocidad no reinicia la secuencia si el "
                             "firmware lo soporta (CA-21.1).", style="TarjetaSuave.TLabel", wraplength=760,
                  justify="left").grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.horarios = EditorHorarios(self, pantalla, d["id"], "movil", "Horarios del móvil (HU-22)",
                                       "En el minuto de inicio se enciende con la secuencia elegida; al terminar se apaga. "
                                       "La base rechaza horarios traslapados.")
        self.horarios.pack(fill="x", pady=(0, 12))

    def cargar(self):
        self.horarios.cargar()

    def pintar(self, d, config, puede):
        super().pintar(d, config, puede)
        self.horarios.permitir(puede)
        if not config:
            return
        encendido = bool(config.get("movil_encendido"))
        self.insignia.cambiar("Encendido" if encendido else "Apagado", "exito" if encendido else "neutro")
        sec = int(config.get("movil_secuencia") or 1)
        if 1 <= sec <= MAX_SECUENCIAS_MOVIL:
            self.secuencia.current(sec - 1)
        else:
            self.secuencia.set(f"Secuencia {sec}")
        self.var_vel.set(int(config.get("movil_velocidad") or 2))

    def _encender(self, valor: bool):
        self.guardar({"movil_encendido": valor}, self.btn_encender if valor else self.btn_apagar,
                     "Móvil encendido." if valor else "Móvil apagado.")


# ========================================================= seguridad (EP06)
class PanelSeguridad(PanelTipo):
    def __init__(self, padre, pantalla, d):
        super().__init__(padre, pantalla, d)
        caja = self.caja("Estado de la seguridad (HU-23)")
        self.insignia = Insignia(caja, "—", "neutro")
        self.insignia.configure(font=("Segoe UI", 14, "bold"))
        self.insignia.pack(side="left", padx=(0, 18))
        self.btn = ttk.Button(caja, text="Armar", style="GrandePrimario.TButton", command=self._alternar)
        self.btn.pack(side="left")
        self._controles.append(self.btn)
        ttk.Button(caja, text="Ver galería de capturas →", style="Enlace.TButton",
                   command=lambda: pantalla.app.navegar("galeria", dispositivo_id=d["id"])).pack(side="right")

        nota = self.caja("Cómo avisa")
        ttk.Label(nota, text="Con la seguridad armada, la puerta y el PIR generan alertas SILENCIOSAS (Telegram, con foto "
                             "si existe). No suena nada en la habitación. La alarma sonora es exclusiva del colchón (anti-robo). "
                             "Desarmada, la base descarta los eventos de puerta y presencia.",
                  style="TarjetaSuave.TLabel", wraplength=760, justify="left").pack(anchor="w")

        ajustes = self.caja("Fotos de evidencia (HU-26)")
        self.intervalo = self.entrada(ajustes, "Intervalo entre fotos (s)", 0, 0)
        self.btn_intervalo = self.boton(ajustes, "Guardar", self._guardar_intervalo, "Primario.TButton", row=0, column=2)
        ttk.Label(ajustes, text="Fotos JPEG 640×480 de hasta 150 KB en Storage privado.", style="TarjetaSuave.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        self.horarios = EditorHorarios(self, pantalla, d["id"], "seguridad", "Armado programado",
                                       "Se arma al inicio del intervalo y se desarma al final. Un desarme manual dura "
                                       "hasta el siguiente intervalo (CA-23.2).")
        self.horarios.pack(fill="x", pady=(0, 12))

        eventos = self.caja("Puerta y presencia recientes")
        self.tabla = Tabla(eventos, [("fecha", "Fecha y hora", 150), ("tipo", "Evento", 120), ("desc", "Descripción", 420)], alto=5)
        self.tabla.pack(fill="x")
        self._armada = False

    def cargar(self):
        self.horarios.cargar()

    def pintar(self, d, config, puede):
        super().pintar(d, config, puede)
        self.horarios.permitir(puede)
        if not config:
            return
        self._armada = bool(config.get("seguridad_armada"))
        self.insignia.cambiar("ARMADA" if self._armada else "Desarmada", "critico" if self._armada else "neutro")
        self.btn.configure(text="Desarmar seguridad" if self._armada else "Armar seguridad",
                           style="GrandePeligro.TButton" if self._armada else "GrandePrimario.TButton")
        if self.focus_get() is not self.intervalo:
            poner_texto(self.intervalo, config.get("seguridad_intervalo_foto_s"))

    def _alternar(self):
        nuevo = not self._armada
        if not nuevo and not self.pantalla.confirmar("Desarmar seguridad",
                                                     "Los sensores dejarán de generar alertas hasta el próximo armado. ¿Continuar?"):
            return
        self.guardar({"seguridad_armada": nuevo}, self.btn, "Seguridad armada." if nuevo else "Seguridad desarmada.")

    def _guardar_intervalo(self):
        try:
            valor = dominio.validar_entero(self.intervalo.get(), "el intervalo", minimo=1, maximo=86400)
        except ErrorValidacion as e:
            self.pantalla.mostrar_error(e)
            return
        self.guardar({"seguridad_intervalo_foto_s": valor}, self.btn_intervalo, "Intervalo guardado.")

    def al_eventos(self, eventos):
        filas = [(str(e["id"]), (e["fecha_hora"], e["tipo"], e.get("descripcion") or ""), ("critica",))
                 for e in eventos if e["tipo"] in ("puerta", "presencia")]
        self.tabla.llenar(filas or [("vacio", ("", "Sin eventos de puerta o presencia", ""), ())])


# =========================================================== juguete (EP07)
class PanelJuguete(PanelTipo):
    def __init__(self, padre, pantalla, d):
        super().__init__(padre, pantalla, d)
        caja = self.caja("Juego de cinco botones (HU-29, HU-30)")
        fila = ttk.Frame(caja, style="Tarjeta.TFrame")
        fila.pack(anchor="w")
        self.botones = []
        for i in range(1, 6):
            lbl = tk.Label(fila, text=str(i), width=4, height=2, font=("Segoe UI", 14, "bold"),
                           bg=COLORES["neutro_suave"], fg=COLORES["texto_suave"], relief="flat")
            lbl.pack(side="left", padx=6)
            self.botones.append(lbl)
        self.lbl_ronda = ttk.Label(caja, style="Tarjeta.TLabel")
        self.lbl_ronda.pack(anchor="w", pady=(8, 0))
        self.lbl_aciertos = ttk.Label(caja, style="Tarjeta.TLabel")
        self.lbl_aciertos.pack(anchor="w")
        ttk.Label(caja, text="Las rondas y los aciertos ocurren en el juguete (lógica local). La base no define una orden "
                             "para iniciar rondas desde la app, así que aquí no hay botón para hacerlo; un clic en el PC "
                             "nunca cuenta como acierto.", style="TarjetaSuave.TLabel", wraplength=760,
                  justify="left").pack(anchor="w", pady=(6, 0))

        ajustes = self.caja("Configurar el juego (HU-31)")
        self.tiempo = self.entrada(ajustes, "Tiempo por ronda (s)", 0, 0)
        self.volumen = self.entrada(ajustes, "Volumen (0–100)", 0, 2)
        self.btn_guardar = self.boton(ajustes, "Guardar", self._guardar, "Primario.TButton", row=0, column=4)
        self.lbl_origen = ttk.Label(ajustes, style="TarjetaSuave.TLabel")
        self.lbl_origen.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))

    def pintar(self, d, config, puede):
        super().pintar(d, config, puede)
        activo = dominio.valor_lectura(d, "boton_activo")
        try:
            activo = int(activo) if activo is not None else None
        except (TypeError, ValueError):
            activo = None
        for i, lbl in enumerate(self.botones, start=1):
            encendido = activo == i
            lbl.configure(bg=COLORES["turquesa"] if encendido else COLORES["neutro_suave"],
                          fg="white" if encendido else COLORES["texto_suave"],
                          text=f"★{i}" if encendido else str(i))
        if activo is None:
            self.lbl_ronda.configure(text="El firmware no informa qué botón está iluminado (no se muestra una ronda inventada).")
        else:
            self.lbl_ronda.configure(text=f"Ronda en curso: botón {activo} iluminado.")
        if config:
            for e, c in ((self.tiempo, "juguete_tiempo_ronda_s"), (self.volumen, "juguete_volumen")):
                if self.focus_get() is not e:
                    poner_texto(e, config.get(c))
            self.lbl_origen.configure(text=self.origen(config, "juguete_tiempo_ronda_s", "juguete_volumen")
                                      + ". La siguiente ronda usa el nuevo tiempo.")

    def al_eventos(self, eventos):
        aciertos = [e for e in eventos if e["tipo"] == "juguete_acierto"]
        if aciertos:
            self.lbl_aciertos.configure(text=f"Aciertos registrados (últimos eventos): {len(aciertos)} · último {aciertos[0]['fecha_hora']}")
        else:
            self.lbl_aciertos.configure(text="Sin aciertos registrados en los eventos recientes.")

    def _guardar(self):
        try:
            tiempo = dominio.validar_entero(self.tiempo.get(), "el tiempo por ronda", minimo=1, maximo=600)
            volumen = dominio.validar_entero(self.volumen.get(), "el volumen", minimo=0, maximo=100)
        except ErrorValidacion as e:
            self.pantalla.mostrar_error(e)
            return
        self.guardar({"juguete_tiempo_ronda_s": tiempo, "juguete_volumen": volumen}, self.btn_guardar,
                     "Ajustes del juego guardados.")


# =========================================================== biberón (EP08)
class PanelBiberon(PanelTipo):
    def __init__(self, padre, pantalla, d):
        super().__init__(padre, pantalla, d)
        caja = self.caja("Temperatura de la leche (HU-32, HU-33)")
        self.lbl_temp = ttk.Label(caja, style="Grande.TLabel", text="— °C")
        self.lbl_temp.grid(row=0, column=0, sticky="w")
        self.insignia = Insignia(caja, "—", "neutro")
        self.insignia.grid(row=0, column=1, padx=12, sticky="w")
        self.t_min = self.entrada(caja, "Mínimo seguro (°C)", 1, 0)
        self.t_max = self.entrada(caja, "Máximo seguro (°C)", 1, 2)
        self.btn = self.boton(caja, "Guardar rango", self._guardar, "Primario.TButton", row=1, column=4)
        self.lbl_origen = ttk.Label(caja, style="TarjetaSuave.TLabel")
        self.lbl_origen.grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ttk.Label(caja, text="Las alertas «Demasiado caliente» y «Demasiado fría» las crea la base al recibir la lectura.",
                  style="TarjetaSuave.TLabel").grid(row=3, column=0, columnspan=5, sticky="w")
        ttk.Button(caja, text="Ir al cronómetro de toma →", style="Enlace.TButton",
                   command=lambda: pantalla.app.navegar("alimentacion")).grid(row=4, column=0, sticky="w", pady=(8, 0))

    def pintar(self, d, config, puede):
        super().pintar(d, config, puede)
        temp = dominio.valor_lectura(d, "temperatura_biberon", "temperatura")
        fuente = ""
        if temp is None:
            ev = self.servicios.instantanea.lecturas_historial.get(d["id"], {}).get("temperatura_biberon")
            if ev:
                temp, fuente = ev.get("valor"), f" ({hace_cuanto(ev['ocurrido_en'])})"
        self.lbl_temp.configure(text=f"{g(temp)} °C{fuente}" if temp is not None else "Sin datos")
        if config:
            for e, c in ((self.t_min, "temp_min"), (self.t_max, "temp_max")):
                if self.focus_get() is not e:
                    poner_texto(e, g(config.get(c)))
            self.lbl_origen.configure(text=self.origen(config, "temp_min", "temp_max"))
            try:
                t = float(temp)
                if t > float(config["temp_max"]):
                    self.insignia.cambiar("Demasiado caliente", "critico")
                elif t < float(config["temp_min"]):
                    self.insignia.cambiar("Demasiado fría", "aviso")
                else:
                    self.insignia.cambiar("En rango", "exito")
            except (TypeError, ValueError):
                self.insignia.cambiar("Sin lectura", "neutro")

    def _guardar(self):
        try:
            t_min, t_max = dominio.validar_rango(self.t_min.get(), self.t_max.get(), "temperatura")
        except ErrorValidacion as e:
            self.pantalla.mostrar_error(e)
            return
        self.guardar({"temp_min": t_min, "temp_max": t_max}, self.btn, "Rango del biberón guardado.")


PANELES = {"cuna": PanelCuna, "colchon": PanelColchon, "movil": PanelMovil, "seguridad": PanelSeguridad,
           "juguete": PanelJuguete, "biberon": PanelBiberon}
