// =============================================================================
// Edge Function: enviar-alerta  ·  HU-38 (EP09 Notificaciones por Telegram)
//
// La invoca la base con pg_net (trigger alertas_enviar_telegram y la tarea
// reintentar-alertas de pg_cron). Entrada (POST, JSON): { "alerta_id": 123 }
// Autenticación: encabezado x-alertas-secreto = secreto ALERTAS_WEBHOOK_SECRETO
// (el mismo valor guardado en Vault como 'telegram_alertas_secreto').
//
// Flujo:
//   1. Lee la alerta y sus destinatarios: usuarios con acceso al perfil y chat
//      de Telegram vinculado (CA-38.1, CA-17.1).
//   2. Registra un envío por destinatario en alerta_envios (único por alerta y
//      usuario) y solo manda a quien aún no lo recibió: sin duplicados.
//   3. Con foto (CA-27.1) usa una URL firmada de 5 min del bucket privado.
//   4. Marca la alerta 'enviada', 'fallida' o 'sin_destinatarios' (CA-38.2).
//
// Secretos: TELEGRAM_BOT_TOKEN, ALERTAS_WEBHOOK_SECRETO. SUPABASE_URL y
// SUPABASE_SERVICE_ROLE_KEY los inyecta Supabase. Ninguno va en el repositorio.
// La primera versión de prueba (chat_id + texto) se retiró: permitía mandar
// mensajes arbitrarios por el bot a cualquiera con un JWT válido.
// =============================================================================

import { createClient } from "npm:@supabase/supabase-js@2.45.4";
import { enviarTelegram, mismoSecreto, responder } from "../_shared/telegram.ts";

const ICONOS: Record<string, string> = { critica: "🚨", advertencia: "⚠️", informativa: "🔔" };
const ARRENDAMIENTO_S = 60; // Un envío "tomado" no lo toma otra invocación durante 60 s.

type Envio = {
  id: number;
  usuario_id: string;
  chat_id: number;
  estado: string;
  intentos: number;
  enviado_en: string | null;
};

function espera(intentos: number, retryAfter?: number): number {
  if (retryAfter && retryAfter > 0) return retryAfter;
  return Math.min(5 * 2 ** Math.max(intentos - 1, 0), 300);
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return responder(405, { ok: false, error: "Usa el método POST" });
  }
  const secreto = Deno.env.get("ALERTAS_WEBHOOK_SECRETO");
  if (!mismoSecreto(req.headers.get("x-alertas-secreto"), secreto)) {
    return responder(401, { ok: false, error: "No autorizado" });
  }
  const token = Deno.env.get("TELEGRAM_BOT_TOKEN");
  const url = Deno.env.get("SUPABASE_URL");
  const servicio = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!token || !url || !servicio) {
    return responder(500, { ok: false, error: "Faltan secretos de la función" });
  }

  let alertaId: number;
  try {
    const entrada = await req.json();
    alertaId = Number(entrada?.alerta_id);
    if (!Number.isInteger(alertaId) || alertaId <= 0) throw new Error();
  } catch {
    return responder(400, { ok: false, error: "Se espera { alerta_id: número }" });
  }

  const db = createClient(url, servicio, { auth: { persistSession: false, autoRefreshToken: false } });

  const { data: alerta, error: errAlerta } = await db
    .from("alertas")
    .select("id, perfil_id, tipo, severidad, mensaje, foto_path, estado, intentos, creada_en")
    .eq("id", alertaId)
    .maybeSingle();
  if (errAlerta) return responder(500, { ok: false, error: "No se pudo leer la alerta" });
  if (!alerta) return responder(404, { ok: false, error: "La alerta no existe" });
  if (alerta.estado === "enviada") return responder(200, { ok: true, estado: "enviada" });

  // 1. Destinatarios actuales: acceso al perfil + chat vinculado.
  let destinatarios: { usuario_id: string; chat_id: number }[] = [];
  if (alerta.perfil_id) {
    const { data, error } = await db
      .from("acceso_perfil")
      .select("usuario_id, usuarios!inner(telegram_chat_id)")
      .eq("perfil_id", alerta.perfil_id)
      .not("usuarios.telegram_chat_id", "is", null);
    if (error) return responder(500, { ok: false, error: "No se pudieron leer los destinatarios" });
    destinatarios = (data ?? []).map((fila: any) => ({
      usuario_id: fila.usuario_id,
      chat_id: Array.isArray(fila.usuarios) ? fila.usuarios[0]?.telegram_chat_id : fila.usuarios?.telegram_chat_id,
    })).filter((d) => d.chat_id);
  }

  // 2. Un envío por destinatario; los que ya existen se conservan.
  if (destinatarios.length) {
    const { error } = await db.from("alerta_envios").upsert(
      destinatarios.map((d) => ({ alerta_id: alertaId, usuario_id: d.usuario_id, chat_id: d.chat_id })),
      { onConflict: "alerta_id,usuario_id", ignoreDuplicates: true },
    );
    if (error) return responder(500, { ok: false, error: "No se pudieron registrar los envíos" });
  }

  const { data: envios, error: errEnvios } = await db
    .from("alerta_envios")
    .select("id, usuario_id, chat_id, estado, intentos, enviado_en")
    .eq("alerta_id", alertaId);
  if (errEnvios) return responder(500, { ok: false, error: "No se pudieron leer los envíos" });

  if (!envios?.length) {
    await db.from("alertas")
      .update({ estado: "sin_destinatarios", intentos: (alerta.intentos ?? 0) + 1 })
      .eq("id", alertaId);
    return responder(200, { ok: true, estado: "sin_destinatarios" });
  }

  // 3. Foto con URL firmada de corta duración (bucket privado).
  let fotoUrl: string | undefined;
  if (alerta.foto_path) {
    const { data } = await db.storage.from("capturas").createSignedUrl(alerta.foto_path, 300);
    fotoUrl = data?.signedUrl;
  }
  const texto = `${ICONOS[alerta.severidad] ?? "🔔"} ${alerta.mensaje}`;

  const ahora = new Date();
  for (const envio of envios as Envio[]) {
    if (envio.estado === "enviada") continue;
    // Toma atómica del envío: evita que dos invocaciones manden el mismo mensaje.
    const { data: tomado } = await db
      .from("alerta_envios")
      .update({ proximo_intento_en: new Date(ahora.getTime() + ARRENDAMIENTO_S * 1000).toISOString() })
      .eq("id", envio.id)
      .neq("estado", "enviada")
      .lte("proximo_intento_en", ahora.toISOString())
      .select("id");
    if (!tomado?.length) continue;

    let resultado = await enviarTelegram(token, envio.chat_id, texto, fotoUrl);
    if (!resultado.ok && fotoUrl) {
      // Si la foto falla, el aviso sale igual como texto.
      resultado = await enviarTelegram(token, envio.chat_id, `${texto}\n(La foto no pudo adjuntarse.)`);
    }
    const intentos = envio.intentos + 1;
    envio.intentos = intentos;
    if (resultado.ok) {
      envio.estado = "enviada";
      envio.enviado_en = new Date().toISOString();
      await db.from("alerta_envios").update({
        estado: "enviada", intentos, enviado_en: envio.enviado_en,
        telegram_message_id: resultado.message_id, ultimo_error: null,
      }).eq("id", envio.id);
    } else {
      envio.estado = "fallida";
      await db.from("alerta_envios").update({
        estado: "fallida", intentos, ultimo_error: resultado.error?.slice(0, 500),
        proximo_intento_en: new Date(Date.now() + espera(intentos, resultado.reintentar_en_s) * 1000).toISOString(),
      }).eq("id", envio.id);
    }
  }

  // 4. Estado general de la alerta.
  const todas = (envios as Envio[]).every((e) => e.estado === "enviada");
  const enviadaEn = (envios as Envio[]).map((e) => e.enviado_en).filter(Boolean).sort().pop() ?? null;
  await db.from("alertas").update({
    estado: todas ? "enviada" : "fallida",
    intentos: (alerta.intentos ?? 0) + 1,
    enviada_en: todas ? enviadaEn : null,
  }).eq("id", alertaId);

  return responder(200, { ok: true, estado: todas ? "enviada" : "fallida", destinatarios: envios.length });
});
