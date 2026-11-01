// =============================================================================
// Edge Function: enviar-alerta  ·  HU-38 (EP09 Notificaciones por Telegram)
// VERSIÓN DE PRUEBA (Paso 4): envía un texto, o una foto con texto, a un chat.
//
// Entrada (POST, JSON):
//   { "chat_id": 123456789, "texto": "Mensaje", "foto_url": "https://..." }
//   - foto_url es opcional: si viene, se usa sendPhoto; si no, sendMessage.
//
// Más adelante (cuando existan las tablas) esta función recibirá
// { "alerta_id": ... } y buscará sola el texto, la foto y los destinatarios.
// La función enviarTelegram() de abajo se reutiliza tal cual.
// =============================================================================

const TELEGRAM_API = "https://api.telegram.org";

// RNF-01: la alerta anti-robo debe llegar en ≤ 10 s.
// Si Telegram no responde en 8 s, cortamos y lo marcamos como fallido
// (luego pg_cron lo reintenta, CA-38.3).
const TIMEOUT_MS = 8000;

// Resultado de un envío: así sabremos si guardar "enviada" o "fallida" (CA-38.2).
type ResultadoEnvio = {
  ok: boolean;
  message_id?: number;     // id del mensaje en Telegram si salió bien
  error?: string;          // descripción del error si falló
  reintentar_en_s?: number; // Telegram lo indica si enviamos demasiado rápido (error 429)
};

/**
 * Envía un mensaje (o una foto con texto) a un chat de Telegram.
 * Nunca lanza excepciones: siempre devuelve un ResultadoEnvio.
 */
async function enviarTelegram(
  token: string,
  chatId: string | number,
  texto: string,
  fotoUrl?: string,
): Promise<ResultadoEnvio> {
  // Con foto se usa sendPhoto (el texto va como "caption", máx. 1024 caracteres);
  // sin foto, sendMessage (máx. 4096 caracteres).
  const metodo = fotoUrl ? "sendPhoto" : "sendMessage";
  const cuerpo = fotoUrl
    ? { chat_id: chatId, photo: fotoUrl, caption: texto.slice(0, 1024) }
    : { chat_id: chatId, text: texto.slice(0, 4096) };

  try {
    const resp = await fetch(`${TELEGRAM_API}/bot${token}/${metodo}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });

    const datos = await resp.json();

    if (datos.ok) {
      return { ok: true, message_id: datos.result.message_id };
    }

    // Telegram respondió, pero con error (chat inexistente, foto inválida, etc.)
    return {
      ok: false,
      error: `${datos.error_code}: ${datos.description}`,
      reintentar_en_s: datos.parameters?.retry_after,
    };
  } catch (e) {
    // No hubo respuesta (sin internet, tiempo agotado...).
    // Los mensajes de error de red pueden incluir la URL, y la URL contiene
    // el token: lo ocultamos para que nunca aparezca en logs ni respuestas (RNF-15).
    const mensaje = (e instanceof Error ? e.message : String(e)).replaceAll(token, "***");
    return { ok: false, error: `Sin respuesta de Telegram: ${mensaje}` };
  }
}

/** Arma una respuesta HTTP en JSON. */
function responder(estado: number, datos: unknown): Response {
  return new Response(JSON.stringify(datos), {
    status: estado,
    headers: { "Content-Type": "application/json" },
  });
}

// Punto de entrada: Supabase ejecuta esto con cada petición a la función.
Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return responder(405, { ok: false, error: "Usa el método POST" });
  }

  // El token se lee del secreto guardado en Supabase, nunca del código.
  const token = Deno.env.get("TELEGRAM_BOT_TOKEN");
  if (!token) {
    return responder(500, { ok: false, error: "Falta el secreto TELEGRAM_BOT_TOKEN" });
  }

  let entrada: { chat_id?: string | number; texto?: string; foto_url?: string };
  try {
    entrada = await req.json();
  } catch {
    return responder(400, { ok: false, error: "El cuerpo debe ser JSON válido" });
  }

  const { chat_id, texto, foto_url } = entrada;
  if (!chat_id || !texto) {
    return responder(400, { ok: false, error: "Faltan los campos chat_id o texto" });
  }

  const resultado = await enviarTelegram(token, chat_id, texto, foto_url);

  // 200 si salió; 502 ("falló el servicio externo") si Telegram dio error.
  return responder(resultado.ok ? 200 : 502, resultado);
});
