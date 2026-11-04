-- =============================================================================
-- Migración: envío automático y vinculación de Telegram (EP09 · HU-37, HU-38)
--
-- Completa lo que dejó pendiente 20261101120000_notificaciones_telegram.sql
-- (tablas codigos_telegram y alerta_envios). Es ADITIVA: no borra ni cambia
-- tablas existentes.
--
-- Contenido:
--   1. generar_codigo_telegram()      -> la app pide un código de 6 dígitos (CA-37.1)
--   2. vincular_telegram()            -> solo service_role (Edge Function telegram-webhook)
--   3. desvincular_telegram()         -> el usuario quita su chat
--   4. Trigger sobre alertas + pg_net -> llama a la Edge Function enviar-alerta (CA-38.1)
--   5. reintentar_alertas() en pg_cron cada minuto (CA-38.3)
--   6. v_latencia_telegram            -> observabilidad de RNF-01/RNF-02 (10 s / 20 s)
--
-- Configuración que NO viaja en la migración (ver README.md, sección Telegram):
--   * Vault: secretos 'telegram_funciones_url' y 'telegram_alertas_secreto'.
--   * Secretos de Edge Functions: TELEGRAM_BOT_TOKEN, ALERTAS_WEBHOOK_SECRETO,
--     TELEGRAM_WEBHOOK_SECRETO.
-- Sin el Vault configurado, las alertas se guardan igual con estado 'pendiente'
-- (RNF-17): nunca falla el INSERT de una alerta por culpa de Telegram.
-- =============================================================================

create extension if not exists pg_net with schema extensions;
create extension if not exists pgcrypto with schema extensions;


-- -----------------------------------------------------------------------------
-- 1. Código de vinculación (HU-37). Uno vigente por usuario, 10 minutos.
--    Se genera con bytes aleatorios criptográficos, no con random().
-- -----------------------------------------------------------------------------
create function public.generar_codigo_telegram()
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_codigo text;
  v_expira timestamptz;
  v_intento integer := 0;
begin
  if not exists (select 1 from public.usuarios where id = auth.uid()) then
    raise exception 'Esta cuenta no puede vincular Telegram' using errcode = '42501';
  end if;

  -- El código anterior sin usar del usuario y los vencidos de todos se descartan:
  -- así los números quedan libres para el índice único de códigos activos.
  delete from public.codigos_telegram c
   where c.usado_en is null and (c.usuario_id = auth.uid() or c.expira_en < now());

  loop
    v_intento := v_intento + 1;
    v_codigo := lpad(((('x' || encode(extensions.gen_random_bytes(4), 'hex'))::bit(32)::bigint) % 1000000)::text, 6, '0');
    begin
      insert into public.codigos_telegram (usuario_id, codigo)
      values (auth.uid(), v_codigo)
      returning expira_en into v_expira;
      exit;
    exception when unique_violation then
      if v_intento >= 20 then
        raise exception 'No se pudo generar un código. Intente de nuevo.';
      end if;
    end;
  end loop;

  return jsonb_build_object('codigo', v_codigo, 'expira_en', v_expira);
end;
$$;


-- -----------------------------------------------------------------------------
-- 2. Vinculación desde el webhook del bot. El chat_id lo da Telegram (verificado
--    por secret_token en la Edge Function) y el código prueba la cuenta de la app.
--    Límite de 5 códigos fallidos por chat cada 10 minutos contra fuerza bruta.
-- -----------------------------------------------------------------------------
create table if not exists public.telegram_intentos_vinculacion (
  id           bigint generated always as identity primary key,
  chat_id      bigint      not null,
  intentado_en timestamptz not null default now()
);

create index if not exists telegram_intentos_chat_idx
  on public.telegram_intentos_vinculacion (chat_id, intentado_en desc);

alter table public.telegram_intentos_vinculacion enable row level security;  -- sin políticas

create function public.vincular_telegram(p_codigo text, p_chat_id bigint)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_codigo public.codigos_telegram;
begin
  if (select count(*) from public.telegram_intentos_vinculacion t
       where t.chat_id = p_chat_id and t.intentado_en > now() - interval '10 minutes') >= 5 then
    return jsonb_build_object('ok', false, 'motivo', 'demasiados_intentos');
  end if;

  select * into v_codigo from public.codigos_telegram c
   where c.codigo = btrim(p_codigo) and c.usado_en is null and c.expira_en > now()
   for update;

  if not found then
    insert into public.telegram_intentos_vinculacion (chat_id) values (p_chat_id);
    return jsonb_build_object('ok', false, 'motivo', 'codigo_invalido');
  end if;

  -- Un chat no puede quedar en dos cuentas (usuarios.telegram_chat_id es unique).
  if exists (select 1 from public.usuarios u
              where u.telegram_chat_id = p_chat_id and u.id <> v_codigo.usuario_id) then
    return jsonb_build_object('ok', false, 'motivo', 'chat_en_otra_cuenta');
  end if;

  update public.codigos_telegram set usado_en = now() where id = v_codigo.id;
  update public.usuarios
     set telegram_chat_id = p_chat_id, telegram_vinculado_en = now()
   where id = v_codigo.usuario_id;
  delete from public.telegram_intentos_vinculacion t where t.chat_id = p_chat_id;

  return jsonb_build_object('ok', true);
end;
$$;

create function public.desvincular_telegram()
returns void language sql security definer set search_path = '' as $$
  update public.usuarios set telegram_chat_id = null, telegram_vinculado_en = null
   where id = auth.uid();
$$;


-- -----------------------------------------------------------------------------
-- 3. Envío: cada alerta nueva pide a enviar-alerta que la mande (CA-38.1).
--    pg_net es asíncrono: la petición sale después del COMMIT y no bloquea al
--    dispositivo. Cualquier error aquí se convierte en WARNING: la alerta se
--    guarda siempre (RNF-17) y pg_cron la reintenta.
-- -----------------------------------------------------------------------------
create function public.solicitar_envio_alerta(p_alerta bigint)
returns boolean language plpgsql security definer set search_path = '' as $$
declare
  v_url     text;
  v_secreto text;
begin
  select decrypted_secret into v_url
    from vault.decrypted_secrets where name = 'telegram_funciones_url';
  select decrypted_secret into v_secreto
    from vault.decrypted_secrets where name = 'telegram_alertas_secreto';

  if v_url is null or v_secreto is null then
    return false;  -- Configuración pendiente: queda 'pendiente'.
  end if;

  perform net.http_post(
    url                  := rtrim(v_url, '/') || '/enviar-alerta',
    body                 := jsonb_build_object('alerta_id', p_alerta),
    headers              := jsonb_build_object('Content-Type', 'application/json',
                                               'x-alertas-secreto', v_secreto),
    timeout_milliseconds := 15000
  );
  return true;
exception when others then
  raise warning 'No se pudo solicitar el envío de la alerta %: %', p_alerta, sqlerrm;
  return false;
end;
$$;

create function public.alertas_solicitar_envio()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  perform public.solicitar_envio_alerta(new.id);
  return null;
end;
$$;

create trigger alertas_enviar_telegram
  after insert on public.alertas
  for each row execute function public.alertas_solicitar_envio();


-- -----------------------------------------------------------------------------
-- 4. Reintentos (CA-38.3). Cada minuto vuelve a pedir el envío de lo pendiente o
--    fallido de las últimas 24 h. La Edge Function solo reenvía a quien no lo
--    recibió (alerta_envios), así que no hay mensajes duplicados.
-- -----------------------------------------------------------------------------
create function public.reintentar_alertas()
returns integer language plpgsql security definer set search_path = '' as $$
declare
  a record;
  v_total integer := 0;
begin
  for a in
    select al.id from public.alertas al
     where al.estado in ('pendiente', 'fallida')
       and al.creada_en > now() - interval '24 hours'
       and al.creada_en < now() - interval '30 seconds'   -- da tiempo al primer envío
       and al.intentos < 30
     order by al.creada_en
     limit 50
  loop
    if public.solicitar_envio_alerta(a.id) then
      v_total := v_total + 1;
    end if;
  end loop;
  return v_total;
end;
$$;

select cron.schedule('reintentar-alertas', '* * * * *', 'select public.reintentar_alertas()');


-- -----------------------------------------------------------------------------
-- 5. Observabilidad: latencia desde que se crea la alerta hasta que Telegram la
--    acepta, por destinatario. Objetivo: anti-robo <= 10 s, demás <= 20 s.
-- -----------------------------------------------------------------------------
create view public.v_latencia_telegram as
  select e.alerta_id,
         a.tipo,
         a.severidad,
         a.creada_en,
         e.enviado_en,
         e.intentos,
         e.estado,
         extract(epoch from (e.enviado_en - a.creada_en))::numeric(10, 2) as latencia_s,
         case when a.tipo = 'antirrobo' then 10 else 20 end as objetivo_s,
         (e.enviado_en - a.creada_en)
           <= make_interval(secs => case when a.tipo = 'antirrobo' then 10 else 20 end) as cumple
    from public.alerta_envios e
    join public.alertas a on a.id = e.alerta_id;


-- -----------------------------------------------------------------------------
-- 6. Permisos. Postgres da EXECUTE a PUBLIC en funciones nuevas: se quita y se
--    concede solo lo necesario.
-- -----------------------------------------------------------------------------
revoke all on function public.generar_codigo_telegram()           from public, anon, authenticated;
revoke all on function public.vincular_telegram(text, bigint)     from public, anon, authenticated;
revoke all on function public.desvincular_telegram()              from public, anon, authenticated;
revoke all on function public.solicitar_envio_alerta(bigint)      from public, anon, authenticated;
revoke all on function public.alertas_solicitar_envio()           from public, anon, authenticated;
revoke all on function public.reintentar_alertas()                from public, anon, authenticated;

grant execute on function public.generar_codigo_telegram()        to authenticated;
grant execute on function public.desvincular_telegram()           to authenticated;
grant execute on function public.vincular_telegram(text, bigint)  to service_role;
grant execute on function public.solicitar_envio_alerta(bigint)   to service_role;
grant execute on function public.reintentar_alertas()             to service_role;

revoke all on public.telegram_intentos_vinculacion from anon, authenticated;
revoke all on public.v_latencia_telegram from anon, authenticated;
grant all on public.telegram_intentos_vinculacion to service_role;
grant select on public.v_latencia_telegram to service_role;
