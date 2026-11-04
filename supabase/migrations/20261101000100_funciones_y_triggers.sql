-- =============================================================================
-- Migración base 2 de 5: funciones y triggers.
-- Autor: Andrés Guzmán (AG)
--
-- Las funciones SECURITY DEFINER usan search_path = '' y nombres completos para
-- que nadie pueda sustituir una tabla o función desde otro esquema.
-- El envío a Telegram NO está aquí: es el trigger sobre alertas de EP09.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. Permisos: las usan las políticas RLS y las funciones de abajo
-- -----------------------------------------------------------------------------

create function public.tiene_acceso_perfil(p_perfil uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.acceso_perfil a
    where a.perfil_id = p_perfil and a.usuario_id = auth.uid()
  );
$$;

create function public.puede_controlar_perfil(p_perfil uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1
    from public.acceso_perfil a
    join public.perfiles_bebe p on p.id = a.perfil_id
    where a.perfil_id = p_perfil
      and a.usuario_id = auth.uid()
      and a.puede_controlar
      and p.eliminado_en is null
  );
$$;

create function public.es_propietario_perfil(p_perfil uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.perfiles_bebe p
    where p.id = p_perfil and p.propietario_id = auth.uid()
  );
$$;

-- ¿La sesión actual es la credencial del controlador de este dispositivo?
create function public.es_credencial_dispositivo(p_dispositivo uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.dispositivos d
    where d.id = p_dispositivo and d.credencial_id = auth.uid()
  );
$$;

create function public.puede_ver_dispositivo(p_dispositivo uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.dispositivos d
    where d.id = p_dispositivo
      and (d.propietario_id = auth.uid()
           or d.credencial_id = auth.uid()
           or public.tiene_acceso_perfil(d.perfil_id))
  );
$$;

create function public.puede_controlar_dispositivo(p_dispositivo uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.dispositivos d
    where d.id = p_dispositivo
      and (d.propietario_id = auth.uid()
           or public.puede_controlar_perfil(d.perfil_id))
  );
$$;

-- Historial: se ve por el perfil al que quedó asociado (CA-05.2). Lo registrado
-- sin perfil solo lo ve el dueño del dispositivo. El controlador ve lo suyo.
create function public.puede_ver_historial(p_perfil uuid, p_dispositivo uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select public.tiene_acceso_perfil(p_perfil)
      or public.es_credencial_dispositivo(p_dispositivo)
      or (p_perfil is null and exists (
            select 1 from public.dispositivos d
            where d.id = p_dispositivo and d.propietario_id = auth.uid()));
$$;


-- -----------------------------------------------------------------------------
-- 2. Cuentas y perfiles (EP01)
-- -----------------------------------------------------------------------------

-- CA-01.1: cada cuenta nueva queda como administrador. Se mira app_metadata y no
-- user_metadata porque esta última la puede escribir el usuario al registrarse.
create function public.sincronizar_usuario()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if tg_op = 'UPDATE' then
    update public.usuarios set correo = new.email where id = new.id;
  elsif coalesce(new.raw_app_meta_data ->> 'rol', '') <> 'dispositivo' then
    insert into public.usuarios (id, correo) values (new.id, new.email);
  end if;
  return new;
end;
$$;

create trigger usuarios_desde_auth
  after insert or update of email on auth.users
  for each row execute function public.sincronizar_usuario();

create function public.dar_acceso_al_propietario()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.acceso_perfil (usuario_id, perfil_id, puede_controlar)
  values (new.propietario_id, new.id, true);
  return new;
end;
$$;

create trigger perfiles_bebe_acceso_propietario
  after insert on public.perfiles_bebe
  for each row execute function public.dar_acceso_al_propietario();

-- CA-03.2: los dispositivos quedan sin asignar y el historial se conserva.
create function public.eliminar_perfil(p_perfil uuid)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if not public.es_propietario_perfil(p_perfil) then
    raise exception 'No tienes permiso para eliminar este perfil' using errcode = '42501';
  end if;

  update public.perfiles_bebe set eliminado_en = now()
   where id = p_perfil and eliminado_en is null;
  update public.dispositivos set perfil_id = null where perfil_id = p_perfil;
  update public.recordatorios set activo = false where perfil_id = p_perfil;
end;
$$;

-- Da acceso a otra cuenta ya registrada (SRS 2.3, CA-17.1, CA-18.2).
create function public.compartir_perfil(p_perfil uuid, p_correo text, p_puede_controlar boolean default true)
returns void language plpgsql security definer set search_path = '' as $$
declare
  v_usuario uuid;
begin
  if not public.es_propietario_perfil(p_perfil) then
    raise exception 'No tienes permiso para compartir este perfil' using errcode = '42501';
  end if;

  select id into v_usuario from public.usuarios where correo = lower(btrim(p_correo));
  if v_usuario is null then
    raise exception 'No existe una cuenta con ese correo' using errcode = 'P0002';
  end if;

  insert into public.acceso_perfil (usuario_id, perfil_id, puede_controlar)
  values (v_usuario, p_perfil, p_puede_controlar)
  on conflict (usuario_id, perfil_id) do update set puede_controlar = excluded.puede_controlar;
end;
$$;


-- -----------------------------------------------------------------------------
-- 3. Dispositivos (EP02)
-- -----------------------------------------------------------------------------

create function public.crear_configuracion()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.tipo = 'biberon' then
    -- Rango seguro de la leche (CA-33.1).
    insert into public.configuracion (dispositivo_id, temp_min, temp_max)
    values (new.id, 35, 40);
  else
    insert into public.configuracion (dispositivo_id) values (new.id);
  end if;
  return new;
end;
$$;

create trigger dispositivos_crear_configuracion
  after insert on public.dispositivos
  for each row execute function public.crear_configuracion();

-- Solo con la clave service_role: da de alta un código y su controlador.
-- Marca la cuenta como controlador y la saca de usuarios.
create function public.provisionar_dispositivo(p_codigo text, p_tipo text, p_credencial uuid)
returns uuid language plpgsql security definer set search_path = '' as $$
declare
  v_id uuid;
begin
  if exists (select 1 from public.perfiles_bebe where propietario_id = p_credencial)
     or exists (select 1 from public.dispositivos where propietario_id = p_credencial) then
    raise exception 'La cuenta % ya administra perfiles o dispositivos', p_credencial;
  end if;

  update auth.users
     set raw_app_meta_data = coalesce(raw_app_meta_data, '{}') || '{"rol": "dispositivo"}'
   where id = p_credencial;
  delete from public.usuarios where id = p_credencial;

  insert into public.dispositivos (codigo, tipo, credencial_id)
  values (p_codigo, p_tipo, p_credencial)
  on conflict (codigo) do update set credencial_id = excluded.credencial_id
  returning id into v_id;

  return v_id;
end;
$$;

-- HU-04: el administrador reclama un código válido.
create function public.registrar_dispositivo(p_codigo text, p_nombre text default null)
returns public.dispositivos language plpgsql security definer set search_path = '' as $$
declare
  v_dispositivo public.dispositivos;
begin
  if not exists (select 1 from public.usuarios where id = auth.uid()) then
    raise exception 'Esta cuenta no puede registrar dispositivos' using errcode = '42501';
  end if;

  select * into v_dispositivo from public.dispositivos
   where codigo = btrim(p_codigo) for update;

  if not found then
    raise exception 'El código de dispositivo no es válido' using errcode = 'P0002';
  elsif v_dispositivo.propietario_id = auth.uid() then
    raise exception 'Este dispositivo ya está registrado en tu cuenta' using errcode = '23505';
  elsif v_dispositivo.propietario_id is not null then
    raise exception 'Este dispositivo ya está vinculado a otra cuenta' using errcode = '23505';
  end if;

  update public.dispositivos
     set propietario_id = auth.uid(),
         nombre = coalesce(nullif(btrim(p_nombre), ''), v_dispositivo.tipo),
         registrado_en = now()
   where id = v_dispositivo.id
  returning * into v_dispositivo;

  return v_dispositivo;
end;
$$;

-- Evento generado por el servidor, no por un sensor.
create function public.registrar_evento_sistema(
  p_dispositivo uuid, p_tipo text, p_descripcion text,
  p_valor numeric default null, p_unidad text default null
)
returns void language sql security definer set search_path = '' as $$
  insert into public.eventos (dispositivo_id, tipo, descripcion, valor, unidad, ocurrido_en)
  values (p_dispositivo, p_tipo, p_descripcion, p_valor, p_unidad, clock_timestamp())
  on conflict on constraint eventos_sin_duplicados do nothing;
$$;

-- Señal de vida cada 5 s (HU-06) con la última lectura para la vista en vivo.
-- El colchón manda aquí {"conectado_cuna": true|false} (CA-14.2).
create function public.registrar_senal(p_dispositivo uuid, p_lectura jsonb default null)
returns void language plpgsql security definer set search_path = '' as $$
declare
  v_estaba_en_linea boolean;
begin
  select en_linea into v_estaba_en_linea from public.dispositivos
   where id = p_dispositivo and credencial_id = auth.uid() for update;

  if not found then
    raise exception 'Credencial no autorizada para este dispositivo' using errcode = '42501';
  end if;

  update public.dispositivos
     set en_linea = true,
         ultima_senal_en = now(),
         ultima_lectura = coalesce(p_lectura, ultima_lectura)
   where id = p_dispositivo;

  if not v_estaba_en_linea then
    perform public.registrar_evento_sistema(p_dispositivo, 'conexion', 'En línea');
  end if;
end;
$$;

-- La usa el trigger de eventos para validar un horario (minutos desde el domingo
-- a las 00:00). Un horario que cruza el fin de la semana se parte en dos rangos.
create function public.horario_rangos(p_dias smallint[], p_inicio time, p_fin time)
returns setof int4range language sql immutable set search_path = '' as $$
  with base as (
    select d * 1440 + (extract(epoch from p_inicio) / 60)::integer as ini,
           (((extract(epoch from p_fin) - extract(epoch from p_inicio)) / 60)::integer + 1440) % 1440 as dur
    from unnest(p_dias) as d
  )
  select int4range(ini, least(ini + dur, 10080)) from base
  union all
  select int4range(0, ini + dur - 10080) from base where ini + dur > 10080;
$$;

-- CA-22.3: rechaza horarios traslapados del mismo dispositivo y tipo.
create function public.validar_horario()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  v_tipo_dispositivo text;
begin
  select tipo into v_tipo_dispositivo from public.dispositivos where id = new.dispositivo_id;

  if v_tipo_dispositivo <> (case new.tipo when 'movimiento' then 'cuna' else new.tipo end) then
    raise exception 'Un horario de % no aplica a un dispositivo de tipo %', new.tipo, v_tipo_dispositivo
      using errcode = '23514';
  end if;

  if new.activo and exists (
    select 1
    from public.horarios h
    cross join lateral public.horario_rangos(h.dias, h.hora_inicio, h.hora_fin) r1
    cross join lateral public.horario_rangos(new.dias, new.hora_inicio, new.hora_fin) r2
    where h.dispositivo_id = new.dispositivo_id
      and h.tipo = new.tipo
      and h.activo
      and h.id <> new.id
      and r1 && r2
  ) then
    raise exception 'El horario se traslapa con otro ya guardado' using errcode = '23P01';
  end if;

  return new;
end;
$$;

create trigger horarios_validar
  before insert or update on public.horarios
  for each row execute function public.validar_horario();

create function public.esta_en_horario(p_dispositivo uuid, p_tipo text, p_momento timestamptz)
returns boolean language sql stable security definer set search_path = '' as $$
  with ahora as (
    select p_momento at time zone 'America/Costa_Rica' as local
  )
  select exists (
    select 1
    from public.horarios h
    cross join ahora
    cross join lateral public.horario_rangos(h.dias, h.hora_inicio, h.hora_fin) r
    where h.dispositivo_id = p_dispositivo
      and h.tipo = p_tipo
      and h.activo
      and r @> (extract(dow from ahora.local)::integer * 1440
                + extract(hour from ahora.local)::integer * 60
                + extract(minute from ahora.local)::integer)
  );
$$;


-- -----------------------------------------------------------------------------
-- 4. Configuración
-- -----------------------------------------------------------------------------

create function public.configuracion_antes_actualizar()
returns trigger language plpgsql as $$
begin
  new.actualizado_en := now();
  return new;
end;
$$;

create trigger configuracion_fecha
  before update on public.configuracion
  for each row execute function public.configuracion_antes_actualizar();

-- Armar o desarmar queda en el historial, sea manual o por horario.
create function public.registrar_cambio_seguridad()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  perform public.registrar_evento_sistema(
    new.dispositivo_id,
    case when new.seguridad_armada then 'seguridad_armada' else 'seguridad_desarmada' end,
    case when new.seguridad_armada then 'Seguridad armada' else 'Seguridad desarmada' end
  );
  return new;
end;
$$;

create trigger configuracion_cambio_seguridad
  after update of seguridad_armada on public.configuracion
  for each row
  when (old.seguridad_armada is distinct from new.seguridad_armada)
  execute function public.registrar_cambio_seguridad();


-- -----------------------------------------------------------------------------
-- 5. Alertas
-- -----------------------------------------------------------------------------

-- CA-05.1: la alerta queda con el perfil actual del dispositivo.
create function public.alertas_antes_insertar()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.dispositivo_id is not null then
    select perfil_id into new.perfil_id from public.dispositivos where id = new.dispositivo_id;
  end if;
  return new;
end;
$$;

create trigger alertas_completar
  before insert on public.alertas
  for each row execute function public.alertas_antes_insertar();

-- Crea una alerta salvo que haya otra igual dentro del intervalo de repetición,
-- para que una condición que se mantiene no mande un mensaje por minuto.
create function public.crear_alerta(
  p_evento public.eventos, p_tipo text, p_severidad text, p_mensaje text,
  p_umbral numeric default null, p_repetir_cada interval default null
)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if p_repetir_cada is not null and exists (
    select 1 from public.alertas a
    where a.dispositivo_id = p_evento.dispositivo_id
      and a.tipo = p_tipo
      and a.creada_en > now() - p_repetir_cada
  ) then
    return;
  end if;

  insert into public.alertas (dispositivo_id, evento_id, tipo, severidad, mensaje, valor, umbral, foto_path)
  values (p_evento.dispositivo_id, p_evento.id, p_tipo, p_severidad, p_mensaje,
          p_evento.valor, p_umbral, p_evento.foto_path);
end;
$$;

create function public.nombre_perfil(p_perfil uuid)
returns text language sql stable security definer set search_path = '' as $$
  select coalesce((select nombre from public.perfiles_bebe where id = p_perfil), 'sin perfil asignado');
$$;

create function public.hora_local(p_momento timestamptz)
returns text language sql immutable set search_path = '' as $$
  select to_char(p_momento at time zone 'America/Costa_Rica', 'DD/MM/YYYY HH24:MI');
$$;


-- -----------------------------------------------------------------------------
-- 6. Eventos: el centro de la lógica (flujos 1, 2 y 4)
-- -----------------------------------------------------------------------------

create function public.eventos_antes_insertar()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  v_armada boolean;
begin
  select perfil_id into new.perfil_id from public.dispositivos where id = new.dispositivo_id;

  -- Un reloj sin sincronizar no puede dejar eventos en el futuro (CA-39.2).
  new.ocurrido_en := least(new.ocurrido_en, clock_timestamp());

  -- Cada dispositivo solo puede citar fotos de su propia carpeta (RNF-23).
  if new.foto_path is not null
     and split_part(new.foto_path, '/', 1) <> new.dispositivo_id::text then
    raise exception 'La foto debe estar en la carpeta del dispositivo' using errcode = '42501';
  end if;

  -- CA-10.2: movimiento fuera de la ventana. No se guarda ni alerta.
  if new.tipo = 'movimiento'
     and not public.esta_en_horario(new.dispositivo_id, 'movimiento', new.ocurrido_en) then
    return null;
  end if;

  -- CA-23.2, CA-24.2: con la seguridad desarmada los sensores no registran.
  if new.tipo in ('puerta', 'presencia') then
    select seguridad_armada into v_armada from public.configuracion
     where dispositivo_id = new.dispositivo_id;
    if not coalesce(v_armada, false) then
      return null;
    end if;
  end if;

  return new;
end;
$$;

create trigger eventos_validar
  before insert on public.eventos
  for each row execute function public.eventos_antes_insertar();

create function public.eventos_despues_insertar()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  c            public.configuracion;
  v_perfil     text := public.nombre_perfil(new.perfil_id);
  v_hora       text := public.hora_local(new.ocurrido_en);
  v_repeticion interval;
  v_base       numeric;
  v_perdido    numeric;
begin
  select * into c from public.configuracion where dispositivo_id = new.dispositivo_id;
  v_repeticion := make_interval(mins => c.alerta_repeticion_min);

  case new.tipo
    when 'temperatura' then       -- CA-09.1, CA-09.2
      if new.valor < c.temp_min then
        perform public.crear_alerta(new, 'temperatura_baja', 'advertencia',
          format('Temperatura baja en la cuna de %s: %s °C (mínimo %s °C). %s',
                 v_perfil, round(new.valor, 1), round(c.temp_min, 1), v_hora),
          c.temp_min, v_repeticion);
      elsif new.valor > c.temp_max then
        perform public.crear_alerta(new, 'temperatura_alta', 'advertencia',
          format('Temperatura alta en la cuna de %s: %s °C (máximo %s °C). %s',
                 v_perfil, round(new.valor, 1), round(c.temp_max, 1), v_hora),
          c.temp_max, v_repeticion);
      end if;

    when 'humedad' then
      if new.valor < c.hum_min then
        perform public.crear_alerta(new, 'humedad_baja', 'advertencia',
          format('Humedad baja en la cuna de %s: %s %% (mínimo %s %%). %s',
                 v_perfil, round(new.valor, 1), round(c.hum_min, 1), v_hora),
          c.hum_min, v_repeticion);
      elsif new.valor > c.hum_max then
        perform public.crear_alerta(new, 'humedad_alta', 'advertencia',
          format('Humedad alta en la cuna de %s: %s %% (máximo %s %%). %s',
                 v_perfil, round(new.valor, 1), round(c.hum_max, 1), v_hora),
          c.hum_max, v_repeticion);
      end if;

    when 'temperatura_biberon' then  -- CA-33.1, CA-33.2
      if new.valor > c.temp_max then
        perform public.crear_alerta(new, 'biberon_caliente', 'advertencia',
          format('Demasiado caliente: biberón de %s a %s °C (máximo %s °C). %s',
                 v_perfil, round(new.valor, 1), round(c.temp_max, 1), v_hora),
          c.temp_max, v_repeticion);
      elsif new.valor < c.temp_min then
        perform public.crear_alerta(new, 'biberon_fria', 'advertencia',
          format('Demasiado fría: biberón de %s a %s °C (mínimo %s °C). %s',
                 v_perfil, round(new.valor, 1), round(c.temp_min, 1), v_hora),
          c.temp_min, v_repeticion);
      end if;

    when 'movimiento' then        -- CA-10.3
      perform public.crear_alerta(new, 'movimiento', 'advertencia',
        format('Movimiento en la cuna de %s. %s', v_perfil, v_hora),
        null, interval '1 minute');

    when 'puerta', 'presencia' then  -- CA-24.1, CA-25.1, CA-27.1
      -- Si trae foto nueva sí se avisa: ya viene limitada por CA-26.3.
      perform public.crear_alerta(new, new.tipo, 'critica',
        format('%s en la habitación de %s. %s',
               case new.tipo when 'puerta' then 'Se abrió la puerta' else 'Presencia detectada' end,
               v_perfil, v_hora),
        null,
        case when new.foto_path is null
             then make_interval(secs => c.seguridad_intervalo_foto_s) end);

    when 'alarma_antirrobo' then  -- CA-16.1, CA-17.2. valor = peso actual en gramos.
      select s.peso_base_g into v_base from public.snapshots_peso s
       where s.dispositivo_id = new.dispositivo_id and s.desactivado_en is null;

      if v_base > 0 and new.valor is not null then
        v_perdido := round(greatest(v_base - new.valor, 0) * 100 / v_base, 1);
      end if;

      perform public.crear_alerta(new, 'antirrobo', 'critica',
        format('ALARMA ANTI-ROBO: %s. %sHora: %s', v_perfil,
               case when v_perdido is null then ''
                    else format('Peso perdido: %s %%. ', v_perdido) end,
               v_hora),
        c.alarma_caida_pct, interval '1 minute');

    else
      null;
  end case;

  -- CA-26.2: la foto queda vinculada al evento.
  if new.foto_path is not null then
    insert into public.capturas (evento_id, dispositivo_id, perfil_id, foto_path, tomada_en)
    values (new.id, new.dispositivo_id, new.perfil_id, new.foto_path, new.ocurrido_en);
  end if;

  return null;
end;
$$;

create trigger eventos_procesar
  after insert on public.eventos
  for each row execute function public.eventos_despues_insertar();


-- -----------------------------------------------------------------------------
-- 7. Modo siesta (HU-15 a HU-18)
--    App -> comando 'activar_siesta' -> el colchón promedia el peso e inserta en
--    snapshots_peso. Si este trigger lo rechaza, marca el comando como fallido
--    con el mensaje del error.
-- -----------------------------------------------------------------------------

create function public.snapshots_antes_insertar()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  d public.dispositivos;
  v_minimo numeric;
begin
  select * into d from public.dispositivos where id = new.dispositivo_id;
  select peso_minimo_g into v_minimo from public.configuracion where dispositivo_id = new.dispositivo_id;

  if d.tipo <> 'colchon' then
    raise exception 'Solo el colchón puede activar el modo siesta' using errcode = '23514';
  elsif d.perfil_id is null then
    raise exception 'El colchón no está asignado a un perfil' using errcode = '23514';
  elsif new.peso_base_g < v_minimo then
    raise exception 'No se detecta al bebé' using errcode = '23514';  -- CA-15.2
  end if;

  new.perfil_id := d.perfil_id;
  return new;
end;
$$;

create trigger snapshots_validar
  before insert on public.snapshots_peso
  for each row execute function public.snapshots_antes_insertar();

create function public.snapshots_despues_insertar()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  update public.configuracion set siesta_activa = true where dispositivo_id = new.dispositivo_id;
  perform public.registrar_evento_sistema(new.dispositivo_id, 'siesta_activada',
    'Modo siesta activado', new.peso_base_g, 'g');
  return null;
end;
$$;

create trigger snapshots_activar_siesta
  after insert on public.snapshots_peso
  for each row execute function public.snapshots_despues_insertar();

-- CA-18.1, CA-18.2: apaga el buzzer y registra quién y cuándo.
create function public.desactivar_siesta(p_dispositivo uuid)
returns void language plpgsql security definer set search_path = '' as $$
declare
  v_correo text;
begin
  if not public.puede_controlar_dispositivo(p_dispositivo) then
    raise exception 'No tienes permiso de control sobre este dispositivo' using errcode = '42501';
  end if;

  select correo into v_correo from public.usuarios where id = auth.uid();

  update public.alertas a
     set desactivada_por = auth.uid(), desactivada_en = now()
    from public.snapshots_peso s
   where s.dispositivo_id = p_dispositivo
     and s.desactivado_en is null
     and a.dispositivo_id = p_dispositivo
     and a.tipo = 'antirrobo'
     and a.desactivada_en is null
     and a.creada_en >= s.creado_en;

  update public.snapshots_peso
     set desactivado_en = now(), desactivado_por = auth.uid()
   where dispositivo_id = p_dispositivo and desactivado_en is null;

  update public.configuracion set siesta_activa = false where dispositivo_id = p_dispositivo;

  insert into public.comandos (dispositivo_id, tipo, creado_por)
  values (p_dispositivo, 'desactivar_siesta', auth.uid());

  perform public.registrar_evento_sistema(p_dispositivo, 'siesta_desactivada',
    format('Modo siesta desactivado por %s', v_correo));
end;
$$;


-- -----------------------------------------------------------------------------
-- 8. Tareas de pg_cron (se programan en la migración 5)
-- -----------------------------------------------------------------------------

-- HU-06: 60 s sin señal. CA-06.2: alerta si había siesta o seguridad armada.
create function public.marcar_fuera_de_linea()
returns integer language plpgsql security definer set search_path = '' as $$
declare
  d public.dispositivos;
  c public.configuracion;
  v_total integer := 0;
begin
  for d in
    update public.dispositivos
       set en_linea = false
     where en_linea and ultima_senal_en < now() - interval '60 seconds'
    returning *
  loop
    v_total := v_total + 1;
    perform public.registrar_evento_sistema(d.id, 'conexion', 'Fuera de línea');

    select * into c from public.configuracion where dispositivo_id = d.id;
    if (d.tipo = 'colchon' and c.siesta_activa) or (d.tipo = 'seguridad' and c.seguridad_armada) then
      insert into public.alertas (dispositivo_id, tipo, severidad, mensaje)
      values (d.id, 'fuera_de_linea', 'critica',
              format('%s de %s está fuera de línea. %s',
                     coalesce(d.nombre, d.tipo), public.nombre_perfil(d.perfil_id),
                     public.hora_local(now())));
    end if;
  end loop;

  return v_total;
end;
$$;

-- CA-22.1, CA-22.2, CA-23.1. Actúa solo en el minuto de inicio o de fin, no
-- durante todo el intervalo: así un desarme manual dura hasta el siguiente
-- intervalo (CA-23.2).
create function public.aplicar_horarios(p_momento timestamptz default now())
returns void language plpgsql security definer set search_path = '' as $$
declare
  v_local  timestamp := p_momento at time zone 'America/Costa_Rica';
  v_minuto time      := date_trunc('minute', v_local)::time;
  v_dia    smallint  := extract(dow from v_local)::smallint;
  v_ayer   smallint  := ((extract(dow from v_local)::integer + 6) % 7)::smallint;
  h        public.horarios;
  v_inicia boolean;
  v_termina boolean;
begin
  for h in
    select * from public.horarios
     where activo and tipo in ('movil', 'seguridad')
       and v_minuto in (hora_inicio, hora_fin)
  loop
    v_inicia  := h.hora_inicio = v_minuto and v_dia = any (h.dias);
    v_termina := h.hora_fin = v_minuto
      and (case when h.hora_fin < h.hora_inicio then v_ayer else v_dia end) = any (h.dias);

    if h.tipo = 'seguridad' and (v_inicia or v_termina) then
      update public.configuracion set seguridad_armada = v_inicia
       where dispositivo_id = h.dispositivo_id;
    elsif h.tipo = 'movil' and v_inicia then
      update public.configuracion set movil_encendido = true, movil_secuencia = h.secuencia
       where dispositivo_id = h.dispositivo_id;
    elsif h.tipo = 'movil' and v_termina then
      update public.configuracion set movil_encendido = false
       where dispositivo_id = h.dispositivo_id;
    end if;
  end loop;
end;
$$;

-- CA-36.1 y CA-36.2. Los recordatorios usan la misma tabla de alertas, así llegan
-- por el mismo trigger de Telegram.
create function public.revisar_recordatorios(p_momento timestamptz default now())
returns void language plpgsql security definer set search_path = '' as $$
declare
  v_local timestamp := p_momento at time zone 'America/Costa_Rica';
  r record;
  v_referencia timestamptz;
  v_toca boolean;
begin
  for r in
    select rec.*, p.nombre as bebe
    from public.recordatorios rec
    join public.perfiles_bebe p on p.id = rec.perfil_id
    where rec.activo and p.eliminado_en is null
  loop
    if r.tipo = 'intervalo' then
      select max(coalesce(t.fin, t.inicio)) into v_referencia
        from public.tomas t where t.perfil_id = r.perfil_id;
      v_referencia := coalesce(v_referencia, r.creado_en);
      -- Un solo aviso por cada toma: el siguiente espera a que se registre otra.
      v_toca := p_momento >= v_referencia + make_interval(mins => r.intervalo_min)
                and (r.ultimo_envio_en is null or r.ultimo_envio_en < v_referencia);
    else
      -- Margen de 5 minutos por si pg_cron se atrasa; una vez al día.
      v_toca := v_local::time >= r.hora
                and v_local::time < r.hora + interval '5 minutes'
                and (r.ultimo_envio_en is null
                     or (r.ultimo_envio_en at time zone 'America/Costa_Rica')::date < v_local::date);
    end if;

    if v_toca then
      insert into public.alertas (perfil_id, tipo, severidad, mensaje)
      values (r.perfil_id, 'recordatorio', 'informativa', format('Hora de alimentar a %s', r.bebe));
      update public.recordatorios set ultimo_envio_en = p_momento where id = r.id;
    end if;
  end loop;
end;
$$;

-- RNF-25. No toca lo que tiene foto: los archivos se borran con la API de Storage,
-- no con SQL, y sus filas son las que dicen cuáles hay que borrar.
create function public.purgar_historial(p_dias integer default 90)
returns void language sql security definer set search_path = '' as $$
  delete from public.alertas
   where creada_en < now() - make_interval(days => p_dias) and foto_path is null;
  delete from public.eventos e
   where e.ocurrido_en < now() - make_interval(days => p_dias)
     and not exists (select 1 from public.capturas c where c.evento_id = e.id);
$$;


-- -----------------------------------------------------------------------------
-- 9. Vistas para la app. security_invoker: se aplica el RLS de quien consulta.
-- -----------------------------------------------------------------------------

-- HU-39 y HU-40. Filtrar por perfil_id, dispositivo_id, tipo y ocurrido_en;
-- paginar de 50 en 50 con order=ocurrido_en.desc.
create view public.v_historial with (security_invoker = true) as
  select e.id,
         e.perfil_id,
         e.dispositivo_id,
         e.ocurrido_en,
         to_char(e.ocurrido_en at time zone 'America/Costa_Rica', 'YYYY-MM-DD HH24:MI:SS') as fecha_hora,
         p.nombre as perfil,
         coalesce(d.nombre, d.tipo) as dispositivo,
         e.tipo,
         e.valor,
         e.unidad,
         e.descripcion
  from public.eventos e
  join public.dispositivos d on d.id = e.dispositivo_id
  left join public.perfiles_bebe p on p.id = e.perfil_id;

-- HU-28: galería con la fecha y el tipo de evento.
create view public.v_galeria with (security_invoker = true) as
  select c.id,
         c.perfil_id,
         c.dispositivo_id,
         c.foto_path,
         c.tomada_en,
         to_char(c.tomada_en at time zone 'America/Costa_Rica', 'YYYY-MM-DD HH24:MI:SS') as fecha_hora,
         e.tipo as tipo_evento
  from public.capturas c
  join public.eventos e on e.id = c.evento_id;
