-- =============================================================================
-- ⚠️ SOLO PARA EL PROYECTO DE PRUEBAS (pruebas-telegram-js).
-- ⚠️ NO entregar ni ejecutar en el proyecto oficial del equipo.
--
-- Crea versiones mínimas de usuarios y alertas para poder probar la migración
-- de Telegram antes de que exista la base de datos real del compañero.
-- =============================================================================

create table if not exists public.usuarios (
  id     uuid primary key default gen_random_uuid(),
  correo text not null unique
);

create table if not exists public.alertas (
  id        bigint generated always as identity primary key,
  perfil_id uuid,
  tipo      text not null,
  mensaje   text not null,
  creada_en timestamptz not null default now()
);

alter table public.usuarios enable row level security;
alter table public.alertas  enable row level security;

-- Un usuario de prueba
insert into public.usuarios (correo)
values ('prueba@ecosistema.test')
on conflict (correo) do nothing;
