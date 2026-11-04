"""Cuenta del usuario y vinculación de Telegram (HU-37)."""
from __future__ import annotations

import webbrowser
from tkinter import ttk

from app.config.zona import formato_local
from app.errores import ErrorApp
from app.ui.base import Pantalla
from app.ui.widgets import Aviso, Insignia


class PantallaCuenta(Pantalla):
    titulo = "Cuenta"

    def __init__(self, padre, app):
        super().__init__(padre, app)
        ttk.Label(self, text="Cuenta y Telegram", style="Titulo.TLabel").pack(anchor="w")

        datos = ttk.LabelFrame(self, text="Mi cuenta", padding=14)
        datos.pack(fill="x", pady=(12, 12))
        self.lbl_cuenta = ttk.Label(datos, style="Tarjeta.TLabel", justify="left")
        self.lbl_cuenta.pack(anchor="w")

        tg = ttk.LabelFrame(self, text="Alertas por Telegram", padding=14)
        tg.pack(fill="x")
        self.insignia = Insignia(tg, "—", "neutro")
        self.insignia.pack(anchor="w")
        self.aviso = Aviso(tg)
        self.lbl_estado = ttk.Label(tg, style="Tarjeta.TLabel", justify="left")
        self.lbl_estado.pack(anchor="w", pady=(6, 10))
        botones = ttk.Frame(tg, style="Tarjeta.TFrame")
        botones.pack(anchor="w")
        self.btn_codigo = ttk.Button(botones, text="Generar código de vinculación", style="Primario.TButton",
                                     command=self._generar)
        self.btn_codigo.pack(side="left")
        ttk.Button(botones, text="Comprobar vinculación", command=self._comprobar).pack(side="left", padx=8)
        self.btn_bot = ttk.Button(botones, text="Abrir el bot en Telegram", command=self._abrir_bot)
        self.btn_bot.pack(side="left")
        self.btn_desvincular = ttk.Button(botones, text="Desvincular", style="Peligro.TButton", command=self._desvincular)
        self.btn_desvincular.pack(side="left", padx=8)
        self.lbl_codigo = ttk.Label(tg, style="Grande.TLabel", text="")
        self.lbl_codigo.pack(anchor="w", pady=(14, 0))
        self.lbl_instrucciones = ttk.Label(tg, style="TarjetaSuave.TLabel", justify="left")
        self.lbl_instrucciones.pack(anchor="w")
        ttk.Label(self, text="El token del bot nunca está en esta aplicación: el envío y la vinculación los hacen las "
                             "Edge Functions de Supabase con sus secretos.", style="Suave.TLabel").pack(anchor="w", pady=12)

    def al_mostrar(self, **_):
        self._pintar()

    def al_actualizar(self):
        self._pintar()

    def _pintar(self):
        u = self.servicios.instantanea.usuario
        if not u:
            self.lbl_cuenta.configure(text="No se pudo leer la cuenta.")
            return
        self.lbl_cuenta.configure(text=f"Correo: {u['correo']}\nRol: {u['rol']}")
        if u.get("telegram_chat_id"):
            self.insignia.cambiar("Telegram vinculado", "exito")
            self.lbl_estado.configure(text=f"Vinculado el {formato_local(u.get('telegram_vinculado_en'))}. Recibirá las "
                                           "alertas de los perfiles a los que tiene acceso.")
            self.aviso.ocultar()
            self.btn_desvincular.configure(state="normal")
            self.lbl_codigo.configure(text="")
            self.lbl_instrucciones.configure(text="")
        else:
            self.insignia.cambiar("Sin vincular", "aviso")
            self.aviso.mostrar("No recibirás alertas por Telegram", "aviso", before=self.lbl_estado)
            self.lbl_estado.configure(text="Genere un código y envíelo al bot para vincular su chat. El código vence en 10 minutos.")
            self.btn_desvincular.configure(state="disabled")
        bot = self.app.config.telegram_bot_usuario if self.app.config else None
        self.btn_bot.configure(state="normal" if bot else "disabled")

    def _abrir_bot(self, codigo: str | None = None):
        bot = self.app.config.telegram_bot_usuario
        if bot:
            webbrowser.open(f"https://t.me/{bot}" + (f"?start={codigo}" if codigo else ""))

    def _generar(self):
        def ok(datos):
            codigo = datos.get("codigo")
            if not codigo:
                self.mostrar_error(ErrorApp("La base no devolvió un código."))
                return
            bot = self.app.config.telegram_bot_usuario
            self.lbl_codigo.configure(text=f"Código: {codigo}")
            self.lbl_instrucciones.configure(
                text=f"Vence: {formato_local(datos.get('expira_en'), True)}.\n"
                     f"Abra el bot {'@' + bot if bot else 'del proyecto'} y envíe:  /start {codigo}\n"
                     "Luego presione «Comprobar vinculación». El bot confirma la vinculación en el chat.")

        def fallo(error: ErrorApp):
            if error.codigo in {"PGRST202", "42883"}:
                error = ErrorApp("La vinculación de Telegram aún no está instalada en la base de datos (falta la "
                                 "migración 20261104000000_telegram_envio.sql). Consulte README.md.", "error", error.codigo)
            self.mostrar_error(error)

        self.tarea(self.servicios.cuenta.generar_codigo_telegram, ok, fallo, boton=self.btn_codigo)

    def _comprobar(self):
        self.app.recargar()
        self.app.notificar("Comprobando la vinculación…", "info")

    def _desvincular(self):
        if not self.confirmar("Desvincular Telegram", "Dejará de recibir alertas por Telegram. ¿Continuar?"):
            return
        self.tarea(self.servicios.cuenta.desvincular_telegram, lambda _: self.app.recargar(),
                   boton=self.btn_desvincular, exito="Telegram desvinculado.")
