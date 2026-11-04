# Notificaciones por Telegram (EP09 · HU-37 y HU-38)

Responsable: **Javier Solano (JS)**
Bot: [@ecosistema_bebe_g1_bot](https://t.me/ecosistema_bebe_g1_bot)

Este módulo envía por Telegram las alertas que se registran en la base de datos
y permite que cada usuario vincule su chat con un código.

> **Todos:** abran el bot y presionen **Iniciar**. Un bot no puede escribirle a
> alguien que no le ha hablado primero.

> **Actualización (2026-11-04):** la vinculación con código, el webhook, el trigger
> sobre `alertas` con `pg_net` y los reintentos ya están implementados en
> `supabase/migrations/20261104000000_telegram_envio.sql`,
> `supabase/functions/enviar-alerta/` y `supabase/functions/telegram-webhook/`.
> Configuración y estado de las pruebas: README.md e IMPLEMENTACION_ESTADO.md.
> La tabla de abajo es el estado original del sprint.

---

## Estado actual

| Parte | Historia | Estado |
|---|---|---|
| Bot creado en @BotFather | HU-37 / HU-38 | ✅ Listo |
| Edge Function `enviar-alerta` (texto y foto) | HU-38 | ✅ Probada (versión con datos fijos) |
| Tablas `codigos_telegram` y `alerta_envios` | HU-37 / HU-38 | ✅ Probadas en el proyecto de pruebas |
| Función SQL para generar el código | HU-37 (CA-37.1) | ⏳ Pendiente |
| Edge Function `telegram-webhook` (vincular chat) | HU-37 (CA-37.1) | ⏳ Pendiente |
| Trigger: cada alerta nueva se envía sola | HU-38 (CA-38.1) | ⏳ Espera la base de datos oficial |
| Destinatarios y estado "enviada / fallida" | HU-38 (CA-38.1, 38.2) | ⏳ Espera la base de datos oficial |
| Reintentos automáticos con `pg_cron` | HU-38 (CA-38.3) | ⏳ Espera la base de datos oficial |
| Aviso "No recibirás alertas por Telegram" en la app | HU-37 (CA-37.2) | ⏳ Se integra con la app (LM) |

---

## Archivos

```
supabase/
├── functions/
│   └── enviar-alerta/index.ts                       ← envía mensajes y fotos a Telegram
└── migrations/
    └── 20261101120000_notificaciones_telegram.sql   ← tablas y columnas de Telegram
pruebas/
├── 00_tablas_minimas_SOLO_SANDBOX.sql               ← ⚠️ NO correr en el proyecto oficial
└── 01_verificar_tablas_telegram.sql                 ← pruebas de las tablas
```

### `enviar-alerta/index.ts` (TypeScript, Deno)
Recibe un `chat_id`, un texto y, opcionalmente, una `foto_url`. Usa `sendMessage`
o `sendPhoto` según corresponda. Si Telegram no responde en 8 s, lo da por
fallido (para cumplir RNF-01: anti-robo ≤ 10 s). Nunca expone el token en
errores ni registros.

Cuando exista la base oficial, recibirá `{ "alerta_id": ... }` y buscará sola
el texto, la foto y los destinatarios. La lógica de envío no cambia.

### `20261101120000_notificaciones_telegram.sql`
- Agrega a `usuarios`: `telegram_chat_id`, `telegram_vinculado_en`.
- Agrega a `alertas`: `estado`, `intentos`, `enviada_en`.
- Crea `codigos_telegram`: códigos de 6 dígitos, vigencia de 10 minutos.
- Crea `alerta_envios`: un registro por destinatario de cada alerta; evita
  mensajes duplicados.
- Activa RLS **sin políticas** en las dos tablas nuevas: solo las Edge
  Functions (clave `service_role`) pueden usarlas (RNF-14).

Las columnas se agregan con `IF NOT EXISTS`: si la migración base ya las creó,
no hace nada. Se puede ejecutar más de una vez sin problema.

---

## Orden de instalación en el proyecto oficial

1. **Migración base** de la base de datos (compañero responsable de la BD).
2. Activar las extensiones **`pg_net`** y **`pg_cron`**
   (Dashboard → Database → Extensions).
3. **Esta migración**: `20261101120000_notificaciones_telegram.sql`
   (SQL Editor o `supabase db push`).
4. Agregar el secreto del bot (Edge Functions → Secrets):
   - `TELEGRAM_BOT_TOKEN` → lo pone JS directamente. **Nunca** se sube a Git
     ni se comparte por chat (RNF-15).
5. Desplegar la función `enviar-alerta`
   (Dashboard → Edge Functions, o `supabase functions deploy enviar-alerta`).
   Dejar **Verify JWT activado**.

---

## Contrato con la base de datos

Esta migración asume lo siguiente de las tablas base. Si algo es distinto,
avisar a JS: el ajuste es de pocas líneas.

| Tabla | Columna | Tipo esperado |
|---|---|---|
| `usuarios` | `id` | `uuid` |
| `alertas` | `id` | `bigint` (si es `uuid`, se cambia una línea en la sección 3) |
| `alertas` | `perfil_id`, `dispositivo_id`, `tipo`, `mensaje`, `foto_path` | según la migración base |
| `acceso_perfil` | `usuario_id`, `perfil_id` | para saber a quién enviarle cada alerta |

Valores válidos de `alertas.estado`:
`pendiente`, `enviada`, `fallida`, `sin_destinatarios`.
Si la migración base ya define `estado` con otros valores, hay que acordarlos
antes de correr esta migración.

---

## Cómo probar la función de envío

En Supabase → Edge Functions → `enviar-alerta` → **Test**, método `POST`:

```json
{ "chat_id": TU_CHAT_ID, "texto": "🚨 Prueba de alerta" }
```

```json
{ "chat_id": TU_CHAT_ID, "texto": "📷 Movimiento detectado", "foto_url": "https://picsum.photos/640/480" }
```

Respuesta esperada: `"ok": true` y el mensaje llega a Telegram.
Con un `chat_id` inexistente, la respuesta es `"ok": false` con el error de
Telegram (así se detectan los envíos fallidos).

Para conocer tu `chat_id`: escríbele al bot y abre
`https://api.telegram.org/bot<TOKEN>/getUpdates` (solo funciona mientras no
esté registrado el webhook).

---

## Para quienes generan alertas (cuna, colchón, seguridad, biberón)

No necesitan llamar a Telegram. Solo **insertar una fila en `alertas`**; el
trigger se encarga del envío. Para alertas con foto (HU-27), guardar la ruta de
la imagen de Storage en `foto_path`.

---

## Qué NO se sube al repositorio

- El token del bot.
- Contraseñas de la base de datos o la clave `service_role`.
- Archivos `.env` (usar `.env.example` sin valores reales).
