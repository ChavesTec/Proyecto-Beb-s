# Notificaciones por Telegram (EP09 · HU-37 y HU-38)

Responsable: **Javier Solano (JS)** · Bot: [@ecosistema_bebe_g1_bot](https://t.me/ecosistema_bebe_g1_bot)
Código del servidor completado por **LM** sobre la base de **Andrés Guzmán (AG)**.

Este módulo envía por Telegram cada alerta que registra la base de datos y permite
que cada usuario vincule su chat con un código de 6 dígitos.

> **Todos:** abran el bot y presionen **Iniciar**. Un bot no puede escribirle a
> alguien que no le ha hablado primero.

---

## Estado (probado el 05/11/2026)

Prueba de punta a punta en un proyecto Supabase en la nube (sandbox de JS), con las
7 migraciones de `Development` sin cambios, el bot real y un teléfono real.

| Criterio | Resultado | Evidencia |
|---|---|---|
| CA-37.1 Vincular con código | ✅ | Código generado desde la app → enviado al bot → "✅ Listo" y `telegram_chat_id` guardado |
| CA-37.2 Aviso "No recibirás alertas por Telegram" | ✅ | Visible en la app sin vinculación; desaparece al vincular |
| CA-38.1 Cada alerta se envía sola | ✅ | Insertar un **evento** basta: llegan temperatura, anti-robo y presencia |
| CA-38.2 Estado "enviada" / "fallida" | ✅ | `alertas.estado` y `alerta_envios.estado` |
| CA-38.3 Reintentos | ✅ | Fallo real (URL del Vault mal escrita): las alertas llegaron solas al corregirla. Ver límite abajo |
| CA-27.1 Alerta con foto | ✅ | `sendPhoto` con URL firmada del bucket privado |
| RNF-01 Anti-robo ≤ 10 s | ✅ | **2.33 s** |
| RNF-02 Demás alertas ≤ 20 s | ✅ | **2.23 s** (temperatura) |
| Proyecto oficial de Supabase | ⏳ | Pendiente: aplicar migraciones y repetir la configuración (abajo) |

---

## Cómo funciona

**Envío (HU-38):**

```
dispositivo inserta en eventos
  → trigger de la base (AG) crea la fila en alertas
  → trigger alertas_enviar_telegram (pg_net) llama a la Edge Function enviar-alerta
  → enviar-alerta busca a quienes tienen acceso al perfil y Telegram vinculado
  → envía sendMessage o sendPhoto y guarda el resultado en alerta_envios
  → alertas.estado = 'enviada' | 'fallida' | 'sin_destinatarios'
pg_cron (cada minuto) vuelve a pedir el envío de lo 'pendiente' o 'fallido'
```

**Vinculación (HU-37):**

```
app → rpc generar_codigo_telegram() → código de 6 dígitos (vigencia 10 min)
usuario → envía "/start 123456" (o solo "123456") al bot
Telegram → Edge Function telegram-webhook → vincular_telegram() guarda el chat_id
bot → "✅ Listo: este chat quedó vinculado"
```

---

## Archivos

| Archivo | Autor | Qué hace |
|---|---|---|
| `supabase/migrations/20261101120000_notificaciones_telegram.sql` | JS | Tablas `codigos_telegram` y `alerta_envios`; columnas de Telegram en `usuarios` y `alertas` |
| `supabase/migrations/20261104000000_telegram_envio.sql` | LM | Código de vinculación, trigger con `pg_net`, reintentos con `pg_cron`, vista `v_latencia_telegram` |
| `supabase/functions/_shared/telegram.ts` | JS / LM | Envío a la API de Telegram (nunca expone el token) |
| `supabase/functions/enviar-alerta/index.ts` | LM (base JS) | Recibe `{ alerta_id }` y envía a todos los destinatarios sin duplicados |
| `supabase/functions/telegram-webhook/index.ts` | LM | Recibe los mensajes del bot y vincula el chat |
| `pruebas/04_verificar_telegram.sql` | LM | Pruebas de la migración en Supabase local |

---

## Para quienes generan alertas (cuna, colchón, seguridad, biberón)

- **Inserten en `eventos`, nunca en `alertas`.** La base crea la alerta y Telegram la
  envía sola. Hacer las dos cosas manda mensajes dobles.
- **Alertas con foto (HU-27):** subir la foto al bucket `capturas`, dentro de la carpeta
  con el **id del dispositivo** (`capturas/<dispositivo_id>/foto.jpg`), y poner esa ruta
  en `eventos.foto_path`. Solo JPG de hasta 150 KB.
- **Puerta y presencia** solo se registran con la seguridad **armada** (CA-23.2).
- Una misma alerta no se repite antes de `alerta_repeticion_min` (10 min por defecto;
  anti-robo: 1 min), para no mandar un mensaje por minuto.

---

## Configurar Telegram en un proyecto Supabase

Se hace **una vez por proyecto**. Nada de esto viaja con Git: subir el código no basta.
Requiere el proyecto **en la nube**: con Supabase local (Docker), Telegram no puede
llegar al webhook.

1. **Aplicar las 7 migraciones** en orden (`supabase db push`, o SQL Editor).
2. **Vault** (SQL Editor). Cambiar **solo** `<REF>` por el identificador del proyecto:
   ```sql
   select vault.create_secret('https://<REF>.supabase.co/functions/v1', 'telegram_funciones_url');
   select vault.create_secret(encode(extensions.gen_random_bytes(32), 'hex'), 'telegram_alertas_secreto');
   select decrypted_secret from vault.decrypted_secrets where name = 'telegram_alertas_secreto';
   ```
   La última consulta muestra la clave para el paso 3.
3. **Secretos de Edge Functions** (Edge Functions → Secrets):

   | Nombre | Valor |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | Token de @BotFather |
   | `ALERTAS_WEBHOOK_SECRETO` | **Exactamente** el valor de `telegram_alertas_secreto` del Vault |
   | `TELEGRAM_WEBHOOK_SECRETO` | Otra clave al azar: `select encode(extensions.gen_random_bytes(32), 'hex');` |

4. **Desplegar las funciones** con los nombres exactos `enviar-alerta` y
   `telegram-webhook` (`supabase functions deploy <nombre>`), y dejar **Enforce JWT
   Verification apagado** en las dos. Ni la base ni Telegram envían un JWT: cada
   función valida su propia clave.
5. **Registrar el webhook** (en el navegador, una vez):
   ```
   https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<REF>.supabase.co/functions/v1/telegram-webhook&secret_token=<TELEGRAM_WEBHOOK_SECRETO>
   ```
   Esperado: `"Webhook was set"`. Un bot tiene **un solo** webhook: registrarlo en otro
   proyecto deja de enviar los mensajes del bot al anterior.
6. **Vincular** cada teléfono de nuevo: los chats vinculados viven en cada base.

### Errores que ya nos pasaron

| Síntoma | Causa | Solución |
|---|---|---|
| No llega nada; `net._http_response` muestra **405** | En el Vault quedó la dirección del **dashboard** (`supabase.com/dashboard/...`) en vez de la de las funciones | `vault.update_secret(...)` con `https://<REF>.supabase.co/functions/v1` |
| **401** en `net._http_response` | `ALERTAS_WEBHOOK_SECRETO` no coincide con el Vault (secretos cruzados o con espacios) | Copiar de nuevo el valor del Vault. En Secrets, el *digest* debe coincidir con `left(encode(extensions.digest(decrypted_secret, 'sha256'), 'hex'), 12)` |
| El bot no responde | Webhook sin registrar o clave distinta | `https://api.telegram.org/bot<TOKEN>/getWebhookInfo` → `last_error_message` |
| La función no aparece o no la encuentra la base | Se desplegó con el nombre por defecto | Debe llamarse exactamente `enviar-alerta` |

### Consultas útiles

```sql
-- Últimas alertas, su envío y su latencia (objetivo: anti-robo 10 s, demás 20 s)
select a.id, a.tipo, a.estado, l.latencia_s, l.objetivo_s, l.cumple, e.ultimo_error
  from public.alertas a
  left join public.alerta_envios e       on e.alerta_id = a.id
  left join public.v_latencia_telegram l on l.alerta_id = a.id
 order by a.id desc limit 10;

-- Respuestas de la llamada de la base a enviar-alerta (200 = bien)
select id, status_code, left(content::text, 200), error_msg, created
  from net._http_response order by id desc limit 10;
```

---

## Decisiones de diseño y límites conocidos

- **Límite real de los reintentos: unos 30 minutos.** `reintentar_alertas()` solo vuelve
  a pedir alertas con menos de 30 intentos y de menos de 24 h. Como `enviar-alerta` suma
  un intento a la alerta **cada vez que se invoca** (una vez por minuto, aunque la espera
  entre envíos impida reenviar), una alerta que falla sin parar llega a 30 intentos en
  ~30 min y deja de reintentarse. El equipo decidió mantener este comportamiento. Si
  Telegram o la red fallan más tiempo, esas alertas quedan `fallida` en la base y en la
  app, pero no llegan por Telegram. CA-38.3 dice "hasta enviarse"; el límite evita
  reenviar avisos viejos.
- **Clave compartida en lugar de JWT** en las dos funciones, porque las llaman la base
  (`pg_net`) y Telegram, que no tienen JWT.
- **`sin_destinatarios`:** si nadie con acceso al perfil vinculó Telegram, la alerta se
  guarda (RNF-17) pero no se reintenta.
- **Códigos:** 6 dígitos con bytes aleatorios criptográficos, vigencia de 10 min, uno
  activo por usuario, máximo 5 códigos fallidos por chat cada 10 min.
- **Solo chats privados:** el bot no vincula grupos.

---

## Seguridad: qué NO se sube al repositorio

- El token del bot, las dos claves de los webhooks y la clave `service_role`.
- El archivo `.env` (usar `.env.example`, que solo lleva la clave **pública**).

---

## Pendiente

- Configurar Telegram en el **proyecto oficial** cuando exista (pasos de arriba).
- `SUPABASE_SERVICE_ROLE_KEY` aparece como *deprecated* en Supabase. Sigue funcionando;
  más adelante conviene pasar a las nuevas claves secretas.
- Quitar la carpeta `SPRINT 3/pruebas/`: son las pruebas del sandbox del 01/11, ya
  reemplazadas por `pruebas/04_verificar_telegram.sql`.
