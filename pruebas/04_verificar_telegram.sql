-- =============================================================================
-- Pruebas de la migración 20261104000000_telegram_envio.sql
-- ⚠️ SOLO en una base LOCAL (supabase start): crea cuentas y datos de prueba
-- dentro de una transacción que se deshace al final (ROLLBACK).
--
-- docker cp pruebas\04_verificar_telegram.sql supabase_db_proyecto-bebes:/tmp/t.sql
-- docker exec -e PGPASSWORD=postgres supabase_db_proyecto-bebes psql -U supabase_admin -h localhost -d postgres -f /tmp/t.sql
-- =============================================================================
\set ON_ERROR_STOP on
begin;

create temp table resultados (nombre text, ok boolean);

do $$
declare
  v_ana uuid := gen_random_uuid();
  v_beto uuid := gen_random_uuid();
  v_codigo jsonb;
  v_res jsonb;
  i integer;
begin
  insert into auth.users (id, email, raw_app_meta_data) values
    (v_ana, 'ana-tg@ecosistema.test', '{}'), (v_beto, 'beto-tg@ecosistema.test', '{}');

  -- generar_codigo_telegram usa auth.uid(): se simula la sesión de Ana.
  perform set_config('request.jwt.claims', json_build_object('sub', v_ana, 'role', 'authenticated')::text, true);
  perform set_config('request.jwt.claim.sub', v_ana::text, true);
  v_codigo := public.generar_codigo_telegram();
  insert into resultados values ('CA-37.1 genera un código de 6 dígitos', (v_codigo ->> 'codigo') ~ '^[0-9]{6}$');
  insert into resultados values ('El código vence en unos 10 minutos',
    (v_codigo ->> 'expira_en')::timestamptz between now() + interval '9 minutes' and now() + interval '11 minutes');

  perform public.generar_codigo_telegram();
  insert into resultados values ('Un solo código vigente por usuario',
    (select count(*) from public.codigos_telegram where usuario_id = v_ana and usado_en is null) = 1);

  v_codigo := public.generar_codigo_telegram();
  v_res := public.vincular_telegram('000000', 111);
  insert into resultados values ('Código incorrecto no vincula', not (v_res ->> 'ok')::boolean);

  v_res := public.vincular_telegram(v_codigo ->> 'codigo', 111);
  insert into resultados values ('CA-37.1 código correcto vincula el chat',
    (v_res ->> 'ok')::boolean and (select telegram_chat_id from public.usuarios where id = v_ana) = 111);

  v_res := public.vincular_telegram(v_codigo ->> 'codigo', 222);
  insert into resultados values ('Un código no se reutiliza', not (v_res ->> 'ok')::boolean);

  -- Beto intenta vincular el mismo chat de Ana.
  perform set_config('request.jwt.claims', json_build_object('sub', v_beto, 'role', 'authenticated')::text, true);
  perform set_config('request.jwt.claim.sub', v_beto::text, true);
  v_codigo := public.generar_codigo_telegram();
  v_res := public.vincular_telegram(v_codigo ->> 'codigo', 111);
  insert into resultados values ('Un chat no queda en dos cuentas', v_res ->> 'motivo' = 'chat_en_otra_cuenta');

  for i in 1..5 loop
    perform public.vincular_telegram('999999', 333);
  end loop;
  v_res := public.vincular_telegram(v_codigo ->> 'codigo', 333);
  insert into resultados values ('Límite de intentos por chat', v_res ->> 'motivo' = 'demasiados_intentos');

  update public.codigos_telegram set expira_en = now() - interval '1 second' where usuario_id = v_beto;
  v_res := public.vincular_telegram(v_codigo ->> 'codigo', 444);
  insert into resultados values ('Código vencido no vincula', v_res ->> 'motivo' = 'codigo_invalido');

  perform set_config('request.jwt.claims', json_build_object('sub', v_ana, 'role', 'authenticated')::text, true);
  perform set_config('request.jwt.claim.sub', v_ana::text, true);
  perform public.desvincular_telegram();
  insert into resultados values ('Desvincular deja el chat en NULL',
    (select telegram_chat_id from public.usuarios where id = v_ana) is null);

  -- Sin Vault configurado, insertar una alerta no falla y queda pendiente (RNF-17).
  insert into public.alertas (tipo, severidad, mensaje) values ('recordatorio', 'informativa', 'Prueba');
  insert into resultados values ('RNF-17 la alerta se guarda aunque no haya configuración de envío',
    (select estado from public.alertas order by id desc limit 1) = 'pendiente');
end;
$$;

insert into resultados
select 'authenticated no puede ejecutar vincular_telegram',
       not has_function_privilege('authenticated', 'public.vincular_telegram(text, bigint)', 'execute');
insert into resultados
select 'anon no puede generar códigos',
       not has_function_privilege('anon', 'public.generar_codigo_telegram()', 'execute');
insert into resultados
select 'authenticated no lee la vista de latencia',
       not has_table_privilege('authenticated', 'public.v_latencia_telegram', 'select');
insert into resultados
select 'Tarea pg_cron de reintentos programada',
       exists (select 1 from cron.job where jobname = 'reintentar-alertas');

select case when ok then 'ok   ' else 'FALLA' end || ' ' || nombre from resultados;
select count(*) || ' pruebas, ' || count(*) filter (where not ok) || ' fallas' from resultados;

rollback;


-- =============================================================================
-- Medición de latencia (RNF-01/RNF-02) tras enviar alertas REALES. No borra nada.
-- Ejecutar en el proyecto donde se hicieron las pruebas cronometradas:
--
-- select tipo, count(*) as envios,
--        round(avg(latencia_s), 2) as promedio_s,
--        percentile_cont(0.95) within group (order by latencia_s) as p95_s,
--        max(objetivo_s) as objetivo_s,
--        count(*) filter (where cumple) as cumplen
--   from public.v_latencia_telegram
--  where estado = 'enviada' and creada_en > now() - interval '1 day'
--  group by tipo order by tipo;
-- =============================================================================
