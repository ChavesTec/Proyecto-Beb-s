"""Simula los 3 controladores (cuna, seguridad, colchón, móvil, juguete y biberón).

⚠️ Solo con Supabase LOCAL y después de pruebas\\preparar_base_local.py. Uso:
    .venv\\Scripts\\python.exe pruebas\\simular_dispositivos.py
Detener con Ctrl+C. Mientras corre, los dispositivos se ven «En línea» en la app.

Sigue el contrato de README_BASE_DATOS.md, como lo haría cada firmware:
  * registrar_senal cada 5 s con la lectura en vivo (ultima_lectura);
  * una muestra por minuto en eventos (temperatura, humedad, biberón, peso);
  * lee configuracion y responde los comandos pendientes:
      activar_siesta  -> guarda el snapshot de peso (o falla con el mensaje de la base),
      probar_luz / probar_buzzer / audio_* -> ejecutado,
      tomar_foto      -> sube una foto y registra la presencia (si está armada);
  * el móvil informa el estado que le ordenó la base y el juguete rota el botón iluminado.
Ninguna alerta se inserta a mano: las crean los triggers.
"""
from __future__ import annotations

import random
import sys
import time
from datetime import datetime, timezone

from supabase import create_client

from local_comun import CONTROLADORES, claves_locales, foto_jpeg, leer_credenciales

sys.stdout.reconfigure(encoding="utf-8")
URL, ANON, _ = claves_locales()
credenciales = leer_credenciales()

ahora_iso = lambda: datetime.now(timezone.utc).isoformat()


class Controlador:
    def __init__(self, correo: str):
        self.correo = correo
        self.db = create_client(URL, ANON)
        self.db.auth.sign_in_with_password({"email": correo, "password": credenciales[correo]})
        self.dispositivos = {d["id"]: d for d in self.db.table("dispositivos").select("id, codigo, tipo").execute().data}
        self.temp, self.hum, self.leche, self.peso = 22.0, 50.0, 37.0, 4100.0
        self.boton = 1

    def config(self, dispositivo_id: str) -> dict:
        filas = self.db.table("configuracion").select("*").eq("dispositivo_id", dispositivo_id).execute().data
        return filas[0] if filas else {}

    def lectura(self, d: dict, cfg: dict) -> dict:
        tipo = d["tipo"]
        if tipo == "cuna":
            self.temp = min(27, max(17, self.temp + random.uniform(-0.3, 0.3)))
            self.hum = min(65, max(38, self.hum + random.uniform(-1, 1)))
            return {"temperatura": round(self.temp, 1), "humedad": round(self.hum, 1),
                    "luz_intensidad": cfg.get("luz_intensidad", 0)}
        if tipo == "colchon":
            self.peso = 4100 + random.uniform(-25, 25)
            return {"peso": round(self.peso), "conectado_cuna": True}
        if tipo == "movil":
            return {"encendido": bool(cfg.get("movil_encendido")), "secuencia": cfg.get("movil_secuencia", 1),
                    "velocidad": cfg.get("movil_velocidad", 2)}
        if tipo == "juguete":
            return {"boton_activo": self.boton}
        if tipo == "biberon":
            self.leche = min(41, max(34, self.leche + random.uniform(-0.2, 0.2)))
            return {"temperatura_biberon": round(self.leche, 1)}
        return {"camara": "lista", "armada": bool(cfg.get("seguridad_armada"))}

    def muestra(self, d: dict) -> None:
        tipos = {"cuna": [("temperatura", self.temp, "°C"), ("humedad", self.hum, "%")],
                 "biberon": [("temperatura_biberon", self.leche, "°C")], "colchon": [("peso", self.peso, "g")]}
        for tipo, valor, unidad in tipos.get(d["tipo"], []):
            self.db.table("eventos").insert({"dispositivo_id": d["id"], "tipo": tipo, "valor": round(valor, 1),
                                             "unidad": unidad}).execute()

    def comandos(self, d: dict) -> None:
        pendientes = self.db.table("comandos").select("id, tipo, parametros").eq("dispositivo_id", d["id"]) \
            .eq("estado", "pendiente").order("creado_en").execute().data
        for c in pendientes:
            estado, resultado = "ejecutado", None
            try:
                if c["tipo"] == "activar_siesta":
                    self.db.table("snapshots_peso").insert({"dispositivo_id": d["id"],
                                                            "peso_base_g": round(self.peso)}).execute()
                    resultado = f"Snapshot de {round(self.peso)} g"
                elif c["tipo"] == "tomar_foto":
                    ruta = f"{d['id']}/manual-{int(time.time())}.jpg"
                    self.db.storage.from_("capturas").upload(ruta, foto_jpeg("Foto pedida desde la app"),
                                                             {"content-type": "image/jpeg"})
                    self.db.table("eventos").insert({"dispositivo_id": d["id"], "tipo": "presencia",
                                                     "foto_path": ruta, "descripcion": "Foto pedida desde la app"}).execute()
                    resultado = "Foto tomada (se guarda solo con la seguridad armada)"
                elif c["tipo"] == "desactivar_siesta":
                    resultado = "Buzzer apagado"
            except Exception as error:   # p. ej. «No se detecta al bebé»
                estado, resultado = "fallido", getattr(error, "message", None) or str(error)[:200]
            self.db.table("comandos").update({"estado": estado, "resultado": resultado,
                                              "ejecutado_en": ahora_iso()}).eq("id", c["id"]).execute()
            print(f"  {d['codigo']}: {c['tipo']} -> {estado}" + (f" ({resultado})" if resultado else ""))

    def vuelta(self, n: int) -> None:
        if n % 2 == 0:
            self.boton = self.boton % 5 + 1
        for d in self.dispositivos.values():
            cfg = self.config(d["id"])
            self.db.rpc("registrar_senal", {"p_dispositivo": d["id"], "p_lectura": self.lectura(d, cfg)}).execute()
            self.comandos(d)
            if n % 12 == 0:   # una muestra por minuto para el historial
                self.muestra(d)
            if d["tipo"] == "juguete" and random.random() < 0.08:
                self.db.table("eventos").insert({"dispositivo_id": d["id"], "tipo": "juguete_acierto",
                                                 "descripcion": f"Acierto en el botón {self.boton}"}).execute()


def principal() -> None:
    controladores = [Controlador(c) for c in CONTROLADORES]
    total = sum(len(c.dispositivos) for c in controladores)
    print(f"Simulando {total} dispositivos de {len(controladores)} controladores. Ctrl+C para detener.")
    n = 0
    while True:
        inicio = time.time()
        for c in controladores:
            try:
                c.vuelta(n)
            except Exception as error:   # Un fallo de red no detiene la simulación.
                print(f"  {c.correo}: {type(error).__name__}: {str(error)[:120]}")
        n += 1
        time.sleep(max(0.5, 5 - (time.time() - inicio)))


if __name__ == "__main__":
    try:
        principal()
    except KeyboardInterrupt:
        print("Simulación detenida. En 60 s los dispositivos pasarán a «Fuera de línea».")
