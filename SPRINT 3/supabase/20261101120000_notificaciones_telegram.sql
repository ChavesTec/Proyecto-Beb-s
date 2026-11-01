-- =============================================================================
-- Migración: Notificaciones por Telegram (EP09 · HU-37 y HU-38)
-- Autor: Javier Solano (JS)
--
-- REQUISITO: se ejecuta DESPUÉS de la migración base, porque necesita que ya
-- existan public.usuarios (id uuid) y public.alertas (id bigint).
--   * Si en la migración base alertas.id es uuid, cambiar "alerta_id bigint"
--     por "alerta_id uuid" en la sección 3. Es el único ajuste posible.
--
-- Contenido:
--   1. Columnas que Telegram necesita en usuarios y alertas (el "contrato").
--      Usan IF NOT EXISTS: si la migración base ya las creó, no hacen nada.
--   2. Tabla codigos_telegram  -> códigos de 6 dígitos para vincular (HU-37)
--   3. Tabla alerta_envios     -> un envío por destinatario de cada alerta (HU-38)
--   4. Seguridad (RLS, RNF-14)
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. Contrato con las tablas base
-- -----------------------------------------------------------------------------

-- Chat de Telegram de cada usuario. NULL = no ha vinculado (CA-37.2: la app
-- muestra "No recibirás alertas por Telegram").
-- bigint porque los chat_id de Telegram pueden superar el rango de integer.
alter table public.usuarios
  add column if not exists telegram_chat_id     bigint unique,
  add column if not exists telegram_vinculado_en timestamptz;

-- Estado general de la alerta (CA-38.2).
--   pendiente -> recién creada, aún no se envía
--   enviada   -> llegó a todos los destinatarios
--   fallida   -> al menos un destinatario no la recibió (pg_cron la reintenta)
--   sin_destinatarios -> nadie con acceso al perfil tiene Telegram vinculado
--                        (la alerta igual queda guardada, RNF-17)
alter table public.alertas
  add column if not exists estado    text not null default 'pendiente',
  add column if not exists intentos  integer not null default 0,
  add column if not exists enviada_en timestamptz;

-- La regla de valores válidos va aparte para poder agregarla aunque la
-- columna ya existiera.
alter table public.alertas
  drop constraint if exists alertas_estado_valido;
alter table public.alertas
  add constraint alertas_estado_valido
  check (estado in ('pendiente', 'enviada', 'fallida', 'sin_destinatarios'));


-- -----------------------------------------------------------------------------
-- 2. codigos_telegram (HU-37)
--    La app genera un código, el usuario lo envía al bot y el webhook
--    guarda su chat_id en usuarios.
-- -----------------------------------------------------------------------------
create table if not exists public.codigos_telegram (
  id          bigint generated always as identity primary key,
  usuario_id  uuid        not null references public.usuarios (id) on delete cascade,
  codigo      char(6)     not null check (codigo ~ '^[0-9]{6}$'),
  creado_en   timestamptz not null default now(),
  expira_en   timestamptz not null default now() + interval '10 minutes',
  usado_en    timestamptz            -- NULL = todavía no se ha usado
);

comment on table public.codigos_telegram is
  'Códigos de 6 dígitos (vigencia 10 min) para vincular un chat de Telegram a un usuario. HU-37.';

-- Dos códigos sin usar nunca pueden ser iguales, así el bot sabe de quién es.
create unique index if not exists codigos_telegram_codigo_activo_uq
  on public.codigos_telegram (codigo)
  where usado_en is null;

create index if not exists codigos_telegram_usuario_idx
  on public.codigos_telegram (usuario_id);


-- -----------------------------------------------------------------------------
-- 3. alerta_envios (HU-38)
--    Una fila por cada persona que debe recibir una alerta. Si hay dos padres
--    y a uno no le llega, solo se reintenta el suyo (sin mensajes duplicados).
-- -----------------------------------------------------------------------------
create table if not exists public.alerta_envios (
  id                   bigint generated always as identity primary key,
  alerta_id            bigint      not null references public.alertas (id) on delete cascade,
  usuario_id           uuid        not null references public.usuarios (id) on delete cascade,
  chat_id              bigint      not null,            -- chat al que se envió
  estado               text        not null default 'pendiente'
                         check (estado in ('pendiente', 'enviada', 'fallida')),
  intentos             integer     not null default 0,
  ultimo_error         text,                            -- p. ej. "400: chat not found"
  telegram_message_id  bigint,                          -- id del mensaje si salió
  proximo_intento_en   timestamptz not null default now(), -- respeta el "espere X s" de Telegram
  creado_en            timestamptz not null default now(),
  enviado_en           timestamptz,

  -- Una misma alerta nunca se le registra dos veces a la misma persona.
  constraint alerta_envios_unico unique (alerta_id, usuario_id)
);

comment on table public.alerta_envios is
  'Registro de cada envío de una alerta por Telegram, por destinatario. HU-38 (CA-38.2, CA-38.3).';

-- Para que pg_cron encuentre rápido los envíos pendientes de reintento.
create index if not exists alerta_envios_reintentos_idx
  on public.alerta_envios (proximo_intento_en)
  where estado <> 'enviada';


-- -----------------------------------------------------------------------------
-- 4. Seguridad (RNF-14, RNF-15)
--    RLS activado y SIN políticas: ni la app ni los dispositivos pueden leer
--    ni escribir estas tablas directamente. Solo las Edge Functions (que usan
--    la clave service_role) y las funciones SQL del sistema las tocan.
--    La app pedirá su código mediante una función SQL (siguiente paso, HU-37).
-- -----------------------------------------------------------------------------
alter table public.codigos_telegram enable row level security;
alter table public.alerta_envios    enable row level security;
