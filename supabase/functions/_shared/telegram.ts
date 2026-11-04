// =============================================================================
// Envío a la API de Bots de Telegram (compartido por enviar-alerta y telegram-webhook).
// Basado en la versión de prueba de Javier Solano (JS): nunca lanza excepciones
// y nunca expone el token en errores ni registros (RNF-15).
// =============================================================================

const TELEGRAM_API = "https://api.telegram.org";

// RNF-01: la alerta anti-robo debe llegar en ≤ 10 s. Si Telegram no responde en
// 8 s se da por fallido y pg_cron lo reintenta (CA-38.3).
const TIMEOUT_MS = 8000;

export type ResultadoEnvio = {
  ok: boolean;
  message_id?: number;      // id del mensaje en Telegram si salió bien
  error?: string;           // descripción del error si falló
  reintentar_en_s?: number; // Telegram lo indica con el error 429
};

/** Envía un mensaje (o una foto con texto) a un chat de Telegram. */
export async function enviarTelegram(
  token: string,
  chatId: string | number,
  texto: string,
  fotoUrl?: string,
): Promise<ResultadoEnvio> {
  // Con foto: sendPhoto (caption máx. 1024). Sin foto: sendMessage (máx. 4096).
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
    return {
      ok: false,
      error: `${datos.error_code}: ${datos.description}`,
      reintentar_en_s: datos.parameters?.retry_after,
    };
  } catch (e) {
    // El mensaje de error de red puede incluir la URL, que contiene el token.
    const mensaje = (e instanceof Error ? e.message : String(e)).replaceAll(token, "***");
    return { ok: false, error: `Sin respuesta de Telegram: ${mensaje}` };
  }
}

/** Comparación en tiempo constante para secretos compartidos. */
export function mismoSecreto(a: string | null, b: string | undefined): boolean {
  if (!a || !b) return false;
  const x = new TextEncoder().encode(a);
  const y = new TextEncoder().encode(b);
  let diferencia = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    diferencia |= (x[i] ?? 0) ^ (y[i] ?? 0);
  }
  return diferencia === 0;
}

/** Arma una respuesta HTTP en JSON. */
export function responder(estado: number, datos: unknown): Response {
  return new Response(JSON.stringify(datos), {
    status: estado,
    headers: { "Content-Type": "application/json" },
  });
}
