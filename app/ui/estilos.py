"""Paleta y estilos ttk: azul petróleo, turquesa, blanco y gris cálido; rojo solo para lo crítico."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

COLORES = {
    "petroleo": "#1F5F6B",
    "petroleo_oscuro": "#174851",
    "turquesa": "#3FB8AF",
    "turquesa_suave": "#DDF2F0",
    "fondo": "#F6F4F1",       # gris cálido muy claro
    "tarjeta": "#FFFFFF",
    "borde": "#E2DDD7",
    "texto": "#2E2B28",
    "texto_suave": "#6B6560",
    "exito": "#2E7D5B",
    "exito_suave": "#E3F3EA",
    "aviso": "#9A6B00",
    "aviso_suave": "#FFF4D6",
    "critico": "#B3261E",
    "critico_suave": "#FBE4E2",
    "neutro_suave": "#ECE8E3",
}

FUENTE_BASE = 10


def configurar_estilos(raiz: tk.Tk) -> dict[str, tkfont.Font]:
    c = COLORES
    familia = "Segoe UI" if "Segoe UI" in tkfont.families(raiz) else "DejaVu Sans"
    fuentes = {
        "base": tkfont.Font(raiz, family=familia, size=FUENTE_BASE),
        "negrita": tkfont.Font(raiz, family=familia, size=FUENTE_BASE, weight="bold"),
        "pequena": tkfont.Font(raiz, family=familia, size=FUENTE_BASE - 1),
        "titulo": tkfont.Font(raiz, family=familia, size=FUENTE_BASE + 8, weight="bold"),
        "subtitulo": tkfont.Font(raiz, family=familia, size=FUENTE_BASE + 3, weight="bold"),
        "grande": tkfont.Font(raiz, family=familia, size=FUENTE_BASE + 12, weight="bold"),
    }
    for nombre in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        try:
            tkfont.nametofont(nombre).configure(family=familia, size=FUENTE_BASE)
        except tk.TclError:
            pass

    raiz.configure(bg=c["fondo"])
    estilo = ttk.Style(raiz)
    estilo.theme_use("clam")

    estilo.configure(".", background=c["fondo"], foreground=c["texto"], font=fuentes["base"],
                     bordercolor=c["borde"], focuscolor=c["turquesa"])
    estilo.configure("TFrame", background=c["fondo"])
    # Tarjeta: fondo blanco sin borde (contenedores internos). Caja: la tarjeta exterior con borde.
    estilo.configure("Tarjeta.TFrame", background=c["tarjeta"], borderwidth=0)
    estilo.configure("Caja.TFrame", background=c["tarjeta"], relief="solid", borderwidth=1)
    estilo.configure("Lateral.TFrame", background=c["petroleo"])
    estilo.configure("Encabezado.TFrame", background=c["tarjeta"])

    estilo.configure("TLabel", background=c["fondo"], foreground=c["texto"])
    estilo.configure("Tarjeta.TLabel", background=c["tarjeta"])
    estilo.configure("Suave.TLabel", foreground=c["texto_suave"])
    estilo.configure("TarjetaSuave.TLabel", background=c["tarjeta"], foreground=c["texto_suave"],
                     font=fuentes["pequena"])
    estilo.configure("Titulo.TLabel", font=fuentes["titulo"], foreground=c["petroleo_oscuro"])
    estilo.configure("Subtitulo.TLabel", font=fuentes["subtitulo"], foreground=c["petroleo_oscuro"])
    estilo.configure("TarjetaTitulo.TLabel", background=c["tarjeta"], font=fuentes["subtitulo"],
                     foreground=c["petroleo_oscuro"])
    estilo.configure("Grande.TLabel", background=c["tarjeta"], font=fuentes["grande"],
                     foreground=c["petroleo_oscuro"])
    estilo.configure("Encabezado.TLabel", background=c["tarjeta"])
    estilo.configure("Marca.TLabel", background=c["petroleo"], foreground="white", font=fuentes["subtitulo"])

    estilo.configure("TButton", padding=(12, 6), background=c["neutro_suave"], borderwidth=1)
    estilo.map("TButton", background=[("active", c["borde"]), ("disabled", c["fondo"])],
               foreground=[("disabled", "#A8A29C")])
    estilo.configure("Primario.TButton", background=c["petroleo"], foreground="white",
                     font=fuentes["negrita"], bordercolor=c["petroleo"])
    estilo.map("Primario.TButton", background=[("active", c["petroleo_oscuro"]), ("disabled", "#9FB7BC")],
               foreground=[("disabled", "#EEF3F4")])
    estilo.configure("Peligro.TButton", background=c["critico"], foreground="white",
                     font=fuentes["negrita"], bordercolor=c["critico"])
    estilo.map("Peligro.TButton", background=[("active", "#8E1D17"), ("disabled", "#D9A5A1")])
    estilo.configure("Grande.TButton", padding=(20, 14), font=fuentes["subtitulo"])
    estilo.configure("GrandePrimario.TButton", padding=(20, 14), font=fuentes["subtitulo"],
                     background=c["petroleo"], foreground="white")
    estilo.map("GrandePrimario.TButton", background=[("active", c["petroleo_oscuro"]), ("disabled", "#9FB7BC")])
    estilo.configure("GrandePeligro.TButton", padding=(20, 14), font=fuentes["subtitulo"],
                     background=c["critico"], foreground="white")
    estilo.map("GrandePeligro.TButton", background=[("active", "#8E1D17"), ("disabled", "#D9A5A1")])
    estilo.configure("Enlace.TButton", background=c["tarjeta"], foreground=c["petroleo"], borderwidth=0,
                     padding=(4, 2))
    estilo.map("Enlace.TButton", background=[("active", c["turquesa_suave"])])

    estilo.configure("Nav.TButton", background=c["petroleo"], foreground="white", borderwidth=0,
                     anchor="w", padding=(18, 10), font=fuentes["base"])
    estilo.map("Nav.TButton", background=[("active", c["petroleo_oscuro"])])
    estilo.configure("NavActivo.TButton", background=c["turquesa"], foreground=c["petroleo_oscuro"],
                     borderwidth=0, anchor="w", padding=(18, 10), font=fuentes["negrita"])
    estilo.map("NavActivo.TButton", background=[("active", c["turquesa"])])

    estilo.configure("TEntry", padding=6, fieldbackground="white")
    estilo.configure("TCombobox", padding=4, fieldbackground="white")
    estilo.configure("TSpinbox", padding=4, fieldbackground="white")
    estilo.configure("TCheckbutton", background=c["fondo"])
    estilo.configure("Tarjeta.TCheckbutton", background=c["tarjeta"])
    estilo.configure("TRadiobutton", background=c["fondo"])
    estilo.configure("Tarjeta.TRadiobutton", background=c["tarjeta"])
    estilo.configure("TLabelframe", background=c["tarjeta"], bordercolor=c["borde"])
    estilo.configure("TLabelframe.Label", background=c["tarjeta"], foreground=c["petroleo_oscuro"],
                     font=fuentes["negrita"])
    estilo.configure("Treeview", rowheight=26, fieldbackground="white", background="white")
    estilo.configure("Treeview.Heading", font=fuentes["negrita"], background=c["neutro_suave"])
    estilo.map("Treeview", background=[("selected", c["turquesa_suave"])],
               foreground=[("selected", c["texto"])])
    estilo.configure("Horizontal.TScale", background=c["tarjeta"])
    return fuentes
