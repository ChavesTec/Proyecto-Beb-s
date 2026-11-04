"""Pantallas públicas: inicio de sesión, registro y configuración faltante (HU-01, HU-02)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from app.errores import ErrorApp
from app.services import dominio
from app.ui.estilos import COLORES
from app.ui.widgets import Aviso

if TYPE_CHECKING:  # pragma: no cover
    from app.ui.aplicacion import Aplicacion


class PantallaAcceso(ttk.Frame):
    def __init__(self, padre, app: "Aplicacion", mensaje_inicial: str | None = None,
                 tono_inicial: str = "aviso"):
        super().__init__(padre)
        self.app = app
        self._modo = "login"

        lateral = tk.Frame(self, bg=COLORES["petroleo"], width=380)
        lateral.pack(side="left", fill="y")
        lateral.pack_propagate(False)
        tk.Label(lateral, text="Ecosistema\nBebé", bg=COLORES["petroleo"], fg="white", justify="left",
                 font=("Segoe UI", 26, "bold")).pack(anchor="w", padx=36, pady=(80, 12))
        tk.Label(lateral, text="Monitoreo y control de la cuna, el colchón, el móvil,\n"
                               "la seguridad, el juguete y el biberón.",
                 bg=COLORES["petroleo"], fg=COLORES["turquesa_suave"], justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", padx=36)
        tk.Label(lateral, text=f"Proyecto: {app.config.supabase_url}" if app.config else "",
                 bg=COLORES["petroleo"], fg="#9FC9CF", font=("Segoe UI", 8), wraplength=320,
                 justify="left").pack(side="bottom", anchor="w", padx=36, pady=20)

        centro = ttk.Frame(self)
        centro.pack(side="left", fill="both", expand=True)
        caja = ttk.Frame(centro, style="Caja.TFrame", padding=32)
        caja.place(relx=0.5, rely=0.5, anchor="center")

        self.titulo = ttk.Label(caja, text="Iniciar sesión", style="TarjetaTitulo.TLabel")
        self.titulo.grid(row=0, column=0, columnspan=2, sticky="w")
        self._contenedor_aviso = ttk.Frame(caja, style="Tarjeta.TFrame")
        self._contenedor_aviso.grid(row=1, column=0, columnspan=2, sticky="we", pady=(10, 4))
        self.aviso = Aviso(self._contenedor_aviso)

        ttk.Label(caja, text="Correo", style="Tarjeta.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 2))
        self.correo = ttk.Entry(caja, width=36)
        self.correo.grid(row=3, column=0, columnspan=2, sticky="we")
        ttk.Label(caja, text="Contraseña (mínimo 8 caracteres)", style="Tarjeta.TLabel").grid(
            row=4, column=0, sticky="w", pady=(10, 2))
        self.clave = ttk.Entry(caja, width=36, show="•")
        self.clave.grid(row=5, column=0, columnspan=2, sticky="we")
        self.etq_confirmar = ttk.Label(caja, text="Confirmar contraseña", style="Tarjeta.TLabel")
        self.confirmar = ttk.Entry(caja, width=36, show="•")

        self.boton = ttk.Button(caja, text="Entrar", style="Primario.TButton", command=self._enviar)
        self.boton.grid(row=8, column=0, columnspan=2, sticky="we", pady=(18, 6))
        self.alternar = ttk.Button(caja, text="¿No tiene cuenta? Regístrese", style="Enlace.TButton",
                                   command=self._cambiar_modo)
        self.alternar.grid(row=9, column=0, columnspan=2)
        self._caja = caja

        for w in (self.correo, self.clave, self.confirmar):
            w.bind("<Return>", lambda e: self._enviar())
        self.correo.focus_set()
        if mensaje_inicial:
            self.aviso.mostrar(mensaje_inicial, tono_inicial)

    def _cambiar_modo(self) -> None:
        self.aviso.ocultar()
        if self._modo == "login":
            self._modo = "registro"
            self.titulo.configure(text="Crear cuenta de administrador")
            self.etq_confirmar.grid(row=6, column=0, sticky="w", pady=(10, 2))
            self.confirmar.grid(row=7, column=0, columnspan=2, sticky="we")
            self.boton.configure(text="Crear cuenta")
            self.alternar.configure(text="¿Ya tiene cuenta? Inicie sesión")
        else:
            self._modo = "login"
            self.titulo.configure(text="Iniciar sesión")
            self.etq_confirmar.grid_remove()
            self.confirmar.grid_remove()
            self.boton.configure(text="Entrar")
            self.alternar.configure(text="¿No tiene cuenta? Regístrese")

    def _enviar(self) -> None:
        self.aviso.ocultar()
        try:
            correo = dominio.validar_correo(self.correo.get())
            if self._modo == "registro":
                clave = dominio.validar_clave(self.clave.get(), self.confirmar.get())
            else:
                clave = self.clave.get()
                if not clave:
                    raise ErrorApp("Ingrese su contraseña.", "validacion")
        except ErrorApp as error:
            self.aviso.mostrar(error.mensaje, "aviso")
            return

        texto = self.boton.cget("text")
        self.boton.configure(state="disabled", text="Conectando…")
        restaurar = lambda: self.boton.winfo_exists() and self.boton.configure(state="normal", text=texto)

        if self._modo == "login":
            self.app.ejecutor.ejecutar(lambda: self.app.conexion.iniciar_sesion(correo, clave),
                                       lambda usuario: self.app.sesion_iniciada(),
                                       self._fallo, restaurar)
        else:
            self.app.ejecutor.ejecutar(lambda: self.app.conexion.registrar(correo, clave),
                                       self._registrado, self._fallo, restaurar)

    def _registrado(self, resultado) -> None:
        usuario, requiere_confirmacion = resultado
        if requiere_confirmacion:
            self._cambiar_modo()
            self.clave.delete(0, "end")
            self.aviso.mostrar("Cuenta creada. Revise su correo para confirmarla y luego inicie sesión.", "exito")
            return
        self.app.sesion_iniciada()

    def _fallo(self, error: ErrorApp) -> None:
        self.clave.delete(0, "end")
        self.confirmar.delete(0, "end")
        self.aviso.mostrar(error.mensaje, "critico" if error.tipo == "sin_conexion" else "aviso")


class PantallaConfiguracionFaltante(ttk.Frame):
    """Se muestra cuando falta .env o es inválido: nunca se simula una conexión."""

    def __init__(self, padre, mensaje: str, al_reintentar):
        super().__init__(padre, padding=40)
        ttk.Label(self, text="Falta configurar la conexión con Supabase", style="Titulo.TLabel").pack(anchor="w")
        aviso = Aviso(self)
        aviso.mostrar(mensaje, "aviso")
        pasos = (
            "1. Copie el archivo .env.example como .env en la carpeta del proyecto.\n"
            "2. Complete SUPABASE_URL y SUPABASE_ANON_KEY con los datos de Project Settings → API.\n"
            "3. Use solo la clave pública anon/publishable. Nunca la clave service_role.\n"
            "4. Presione Reintentar."
        )
        ttk.Label(self, text=pasos, justify="left").pack(anchor="w", pady=12)
        ttk.Button(self, text="Reintentar", style="Primario.TButton", command=al_reintentar).pack(anchor="w")
