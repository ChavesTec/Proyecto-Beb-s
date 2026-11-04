// =============================================================================
// Edge Function: telegram-webhook  ·  HU-37 (CA-37.1)
//
// Telegram la llama con cada mensaje al bot. Se registra con setWebhook y un
// secret_token; Telegram lo devuelve en X-Telegram-Bot-Api-Secret-Token y aquí
// se compara con el secreto TELEGRAM_WEBHOOK_SECRETO. Sin ese encabezado, 401.
//
// El usuario envía "/start 123456" (o solo "123456") con el código que le
// muestra la app. vincular_telegram() valida el código (vigente, sin usar) y
// guarda el chat de QUIEN ENVÍA el mensaje: nadie puede vincular el chat de
// otra persona, porque el chat_id viene de Telegram y no del cuerpo de la app.
// Se despliega con verify_jwt = false (Telegram no manda JWT).
// =============================================================================

import { createClient } from "npm:@supabase/supabase-js@2.45.4";
import { enviarTelegram, mismoSecreto, responder } from "../_shared/telegram.ts";

const MENSAJES: Record<string, string> = {
  ok: "✅ Listo: este chat quedó vinculado. Aquí recibirás las alertas del Ecosistema Bebé.",
  codigo_invalido: "❌ Código no válido o vencido. Genera uno nuevo en la app (Cuenta y Telegram) y envíalo aquí.",
  chat_en_otra_cuenta: "⚠️ Este chat ya está vinculado a otra cuenta. Desvincúlalo desde esa cuenta primero.",
  demasiados_intentos: "⏳ Demasiados intentos. Espera 10 minutos y vuelve a intentarlo.",
  ayuda: "Hola 👋 Para recibir alertas, abre la app de escritorio → «Cuenta y Telegram», genera un código y envíalo aquí así:\n/start 123456",
  privado: "Por seguridad, la vinculación solo funciona en un chat privado con el bot.",
};

Deno.serve(async (req) => {
  if (req.method !== "POST") return responder(405, { ok: false });
  if (!mismoSecreto(req.headers.get("x-telegram-bot-api-secret-token"), Deno.env.get("TELEGRAM_WEBHOOK_SECRETO"))) {
    return responder(401, { ok: false });
  }
  const token = Deno.env.get("TELEGRAM_BOT_TOKEN");
  const url = Deno.env.get("SUPABASE_URL");
  const servicio = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!token || !url || !servicio) return responder(500, { ok: false });

  let actualizacion: any;
  try {
    actualizacion = await req.json();
  } catch {
    return responder(200, { ok: true }); // A Telegram siempre 200: si no, reintenta sin fin.
  }
  const mensaje = actualizacion?.message;
  const texto: string | undefined = mensaje?.text?.trim();
  const chatId: number | undefined = mensaje?.chat?.id;
  if (!texto || !chatId) return responder(200, { ok: true });

  if (mensaje.chat.type !== "private") {
    await enviarTelegram(token, chatId, MENSAJES.privado);
    return responder(200, { ok: true });
  }

  const coincidencia = texto.match(/^\/start(?:@\w+)?\s+(\d{6})$/) ?? texto.match(/^(\d{6})$/);
  if (!coincidencia) {
    await enviarTelegram(token, chatId, MENSAJES.ayuda);
    return responder(200, { ok: true });
  }

  const db = createClient(url, servicio, { auth: { persistSession: false, autoRefreshToken: false } });
  const { data, error } = await db.rpc("vincular_telegram", { p_codigo: coincidencia[1], p_chat_id: chatId });
  const motivo = error ? null : (data?.ok ? "ok" : data?.motivo);
  await enviarTelegram(token, chatId, MENSAJES[motivo ?? ""] ?? "No se pudo vincular en este momento. Intenta más tarde.");
  return responder(200, { ok: true });
});
