-- =============================================================================
-- Pruebas de la base de datos, por criterio de aceptación.
-- ⚠️ SOLO en una base local de Docker, con un superusuario. Nunca en el proyecto
-- oficial. Todo corre en una transacción que termina en ROLLBACK.
--
-- Como now() no avanza dentro de una transacción, los eventos usan fechas
-- explícitas y la repetición de alertas se prueba moviendo creada_en.
-- =============================================================================
\set ON_ERROR_STOP on
\set QUIET on
\pset format unaligned
\pset tuples_only on
\o /dev/null
begin;

create schema pruebas;
grant usage on schema pruebas to public;
create table pruebas.resultados (n serial, nombre text, ok boolean, detalle text);
grant all on pruebas.resultados to public;
grant all on sequence pruebas.resultados_n_seq to public;

create function pruebas.ok(p_nombre text, p_ok boolean, p_detalle text default null) returns void
language sql as $$ insert into pruebas.resultados (nombre, ok, detalle) values (p_nombre, coalesce(p_ok, false), p_detalle) $$;

-- La sentencia debe fallar con un error que contenga p_patron.
create function pruebas.falla(p_nombre text, p_sql text, p_patron text) returns void
language plpgsql as $$
begin
  execute p_sql;
  perform pruebas.ok(p_nombre, false, 'no falló');
exception when others then
  perform pruebas.ok(p_nombre, sqlerrm ilike '%' || p_patron || '%', sqlerrm);
end $$;

-- Cuántas filas afecta la sentencia.
create function pruebas.filas(p_sql text) returns integer
language plpgsql as $$
declare v integer;
begin
  execute p_sql;
  get diagnostics v = row_count;
  return v;
end $$;

create function pruebas.como(p_uid uuid) returns void language plpgsql as $$
begin
  perform set_config('request.jwt.claims', json_build_object('sub', p_uid, 'role', 'authenticated')::text, true);
  perform set_config('request.jwt.claim.sub', p_uid::text, true);
  perform set_config('role', 'authenticated', true);
end $$;

create function pruebas.como_servidor() returns void language plpgsql as $$
begin
  perform set_config('role', 'none', true);
end $$;
grant execute on all functions in schema pruebas to public;

create function pruebas.cuenta(p_correo text, p_app_meta jsonb default '{}') returns uuid language sql as $$
  insert into auth.users (id, email, raw_app_meta_data)
  values (gen_random_uuid(), p_correo, p_app_meta) returning id
$$;

create table pruebas.ctx (clave text primary key, valor uuid);
grant select on pruebas.ctx to public;
create function pruebas.id(p_clave text) returns uuid language sql stable as $$
  select valor from pruebas.ctx where clave = p_clave $$;
grant execute on function pruebas.id(text) to public;


-- ---------------------------------------------------------------- Preparación
-- Las pruebas cuentan filas, así que parten de tablas vacías aunque la base ya
-- tenga datos, por ejemplo de 03_probar_servicios.py. El ROLLBACK final los devuelve.
truncate public.usuarios, public.dispositivos cascade;

do $$
declare
  v_ctrl_a uuid; v_ctrl_b uuid; v_ctrl_c uuid;
begin
  insert into pruebas.ctx values
    ('ana',   pruebas.cuenta('ana@test.cr')),
    ('beto',  pruebas.cuenta('beto@test.cr')),
    ('carla', pruebas.cuenta('carla@test.cr')),
    ('dani',  pruebas.cuenta('dani@test.cr'));

  v_ctrl_a := pruebas.cuenta('ctrl-a@test.cr');
  v_ctrl_b := pruebas.cuenta('ctrl-b@test.cr');
  v_ctrl_c := pruebas.cuenta('ctrl-c@test.cr');
  insert into pruebas.ctx values ('ctrl_a', v_ctrl_a), ('ctrl_b', v_ctrl_b), ('ctrl_c', v_ctrl_c),
    ('cuna',      public.provisionar_dispositivo('T-CUNA', 'cuna', v_ctrl_a)),
    ('seguridad', public.provisionar_dispositivo('T-SEG',  'seguridad', v_ctrl_a)),
    ('colchon',   public.provisionar_dispositivo('T-COL',  'colchon', v_ctrl_b)),
    ('movil',     public.provisionar_dispositivo('T-MOV',  'movil', v_ctrl_c)),
    ('biberon',   public.provisionar_dispositivo('T-BIB',  'biberon', v_ctrl_c));
end $$;


-- ----------------------------------------------------------------------- EP01
select pruebas.ok('CA-01.1 cuenta nueva queda como administrador',
  (select rol from public.usuarios where id = pruebas.id('ana')) = 'administrador');
select pruebas.ok('Un controlador no queda en usuarios',
  not exists (select 1 from public.usuarios where id = pruebas.id('ctrl_a')));
insert into pruebas.ctx values ('x', pruebas.cuenta('x@test.cr', '{"rol":"dispositivo"}'));
select pruebas.ok('Cuenta con app_metadata dispositivo no entra a usuarios',
  not exists (select 1 from public.usuarios where id = pruebas.id('x')));

select pruebas.como(pruebas.id('ana'));
insert into public.perfiles_bebe (propietario_id, nombre, fecha_nacimiento)
  values (auth.uid(), 'Sofía', '2026-01-01');
insert into public.perfiles_bebe (propietario_id, nombre, fecha_nacimiento)
  values (auth.uid(), 'Mateo', '2026-01-01');
select pruebas.ok('CA-03.1 perfil visible para su dueña',
  (select count(*) from public.perfiles_bebe) = 2);
select pruebas.ok('Propietario recibe acceso automático',
  (select count(*) from public.acceso_perfil where usuario_id = auth.uid() and puede_controlar) = 2);
select pruebas.falla('Nadie cambia su propio rol',
  $$ update public.usuarios set rol = 'usuario' $$, 'permission denied');
select pruebas.falla('Nadie escribe su chat de Telegram',
  $$ update public.usuarios set telegram_chat_id = 1 $$, 'permission denied');
select pruebas.falla('No se borra un perfil directamente (CA-03.2)',
  $$ delete from public.perfiles_bebe $$, 'permission denied');

select pruebas.como_servidor();
insert into pruebas.ctx select 'sofia', id from public.perfiles_bebe where nombre = 'Sofía';
insert into pruebas.ctx select 'mateo', id from public.perfiles_bebe where nombre = 'Mateo';

select pruebas.como(pruebas.id('beto'));
select pruebas.ok('RNF-14 otro usuario no ve el perfil', (select count(*) from public.perfiles_bebe) = 0);
select pruebas.falla('RNF-14 no se crea un perfil para otro',
  format($$ insert into public.perfiles_bebe (propietario_id, nombre, fecha_nacimiento) values (%L, 'X', '2026-01-01') $$, pruebas.id('ana')),
  'row-level security');
select pruebas.falla('RNF-14 solo el dueño comparte',
  format($$ select public.compartir_perfil(%L, 'beto@test.cr') $$, pruebas.id('sofia')), 'permiso');


-- ----------------------------------------------------------------------- EP02
select pruebas.como(pruebas.id('ana'));
select pruebas.ok('CA-04.1 dispositivo sin reclamar no es visible', (select count(*) from public.dispositivos) = 0);
select public.registrar_dispositivo('T-CUNA', 'Cuna');
select public.registrar_dispositivo('T-SEG', 'Seguridad');
select public.registrar_dispositivo('T-COL', 'Colchón');
select public.registrar_dispositivo('T-MOV', 'Móvil');
select public.registrar_dispositivo('T-BIB', 'Biberón');
select pruebas.ok('CA-04.1 reclamado queda con tipo y nombre',
  (select tipo || '/' || nombre from public.dispositivos where codigo = 'T-CUNA') = 'cuna/Cuna');
select pruebas.falla('Código inexistente', $$ select public.registrar_dispositivo('NOPE') $$, 'no es válido');

select pruebas.como(pruebas.id('beto'));
select pruebas.falla('CA-04.2 código de otra cuenta',
  $$ select public.registrar_dispositivo('T-CUNA') $$, 'otra cuenta');
select pruebas.ok('RNF-14 otro usuario no ve dispositivos', (select count(*) from public.dispositivos) = 0);

select pruebas.como(pruebas.id('ctrl_a'));
select pruebas.falla('Un controlador no reclama dispositivos',
  $$ select public.registrar_dispositivo('T-JUG') $$, 'no puede registrar');

select pruebas.como(pruebas.id('ana'));
update public.dispositivos set perfil_id = pruebas.id('sofia');
select pruebas.falla('El dueño no cambia la credencial',
  $$ update public.dispositivos set credencial_id = null $$, 'permission denied');
select pruebas.falla('El dueño no finge estar en línea',
  $$ update public.dispositivos set en_linea = true $$, 'permission denied');

-- Señal de vida (HU-06)
select pruebas.como(pruebas.id('ctrl_a'));
select public.registrar_senal(pruebas.id('cuna'), '{"temperatura": 22.5, "humedad": 50}');
select pruebas.ok('Controlador ve solo sus dos dispositivos', (select count(*) from public.dispositivos) = 2);
select pruebas.falla('RNF-14 credencial ajena no manda señal',
  format($$ select public.registrar_senal(%L) $$, pruebas.id('colchon')), 'no autorizada');
select pruebas.ok('El controlador no cambia su perfil',
  pruebas.filas(format($$ update public.dispositivos set perfil_id = null where id = %L $$, pruebas.id('cuna'))) = 0);

select pruebas.como_servidor();
select pruebas.ok('HU-06 señal deja el dispositivo en línea con su lectura',
  (select en_linea and (ultima_lectura ->> 'temperatura') = '22.5' from public.dispositivos where id = pruebas.id('cuna')));

-- CA-06.1 y CA-06.2
update public.dispositivos set en_linea = true, ultima_senal_en = now() - interval '61 seconds'
 where id in (pruebas.id('colchon'), pruebas.id('movil'));
update public.dispositivos set en_linea = true, ultima_senal_en = now() - interval '30 seconds'
 where id = pruebas.id('cuna');
update public.configuracion set siesta_activa = true where dispositivo_id = pruebas.id('colchon');
select pruebas.ok('CA-06.1 pasan a fuera de línea solo los de más de 60 s',
  public.marcar_fuera_de_linea() = 2);
select pruebas.ok('CA-06.2 alerta si el colchón estaba en siesta',
  (select count(*) from public.alertas where tipo = 'fuera_de_linea' and dispositivo_id = pruebas.id('colchon')) = 1);
select pruebas.ok('CA-06.2 sin alerta para el móvil',
  (select count(*) from public.alertas where tipo = 'fuera_de_linea' and dispositivo_id = pruebas.id('movil')) = 0);
update public.configuracion set siesta_activa = false where dispositivo_id = pruebas.id('colchon');
delete from public.alertas;


-- ----------------------------------------------------------------------- EP03
select pruebas.como(pruebas.id('ana'));
select pruebas.ok('CA-09.4 umbrales estándar',
  (select temp_min = 18 and temp_max = 26 from public.configuracion where dispositivo_id = pruebas.id('cuna')));
select pruebas.falla('CA-09.3 mínimo mayor que máximo',
  format($$ update public.configuracion set temp_min = 30 where dispositivo_id = %L $$, pruebas.id('cuna')),
  'configuracion_rango_temperatura');
select pruebas.falla('CA-11 luz fuera de rango',
  format($$ update public.configuracion set luz_intensidad = 101 where dispositivo_id = %L $$, pruebas.id('cuna')),
  'configuracion_luz');
select pruebas.falla('La app no fuerza la siesta',
  format($$ update public.configuracion set siesta_activa = true where dispositivo_id = %L $$, pruebas.id('colchon')),
  'permission denied');
update public.configuracion set luz_intensidad = 40 where dispositivo_id = pruebas.id('cuna');
select pruebas.ok('CA-11.3 la intensidad queda guardada',
  (select luz_intensidad from public.configuracion where dispositivo_id = pruebas.id('cuna')) = 40);

select pruebas.como(pruebas.id('ctrl_a'));
select pruebas.ok('El controlador no cambia umbrales',
  pruebas.filas(format($$ update public.configuracion set temp_min = 10 where dispositivo_id = %L $$, pruebas.id('cuna'))) = 0);
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('cuna'), 'temperatura', 22, '°C', '2026-11-01 12:00+00');
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('cuna'), 'temperatura', 15.5, '°C', '2026-11-01 12:01+00');
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('cuna'), 'temperatura', 15.2, '°C', '2026-11-01 12:02+00');
-- Reenvío del buffer: no se duplica (RNF-17).
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('cuna'), 'temperatura', 15.2, '°C', '2026-11-01 12:02+00')
  on conflict on constraint eventos_sin_duplicados do nothing;
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('cuna'), 'humedad', 80, '%', '2026-11-01 12:02+00');
select pruebas.falla('RNF-14 credencial ajena no escribe eventos',
  format($$ insert into public.eventos (dispositivo_id, tipo) values (%L, 'peso') $$, pruebas.id('colchon')),
  'row-level security');
select pruebas.falla('El dispositivo no elige el perfil del evento',
  format($$ insert into public.eventos (dispositivo_id, tipo, perfil_id) values (%L, 'peso', %L) $$, pruebas.id('cuna'), pruebas.id('mateo')),
  'permission denied');
select pruebas.falla('El dispositivo no cambia el estado de una alerta',
  $$ update public.alertas set estado = 'enviada' $$, 'permission denied');

select pruebas.como_servidor();
select pruebas.ok('RNF-17 el buffer reenviado no duplica',
  (select count(*) from public.eventos where tipo = 'temperatura' and dispositivo_id = pruebas.id('cuna')) = 3);
select pruebas.ok('CA-09.1 alerta con valor y umbral',
  (select count(*) = 1 and bool_and(valor = 15.5 and umbral = 18 and perfil_id = pruebas.id('sofia'))
     from public.alertas where tipo = 'temperatura_baja'));
select pruebas.ok('CA-09.1 mensaje con perfil, valor, umbral y hora local (UTC-6)',
  (select mensaje from public.alertas where tipo = 'temperatura_baja')
    = 'Temperatura baja en la cuna de Sofía: 15.5 °C (mínimo 18.0 °C). 01/11/2026 06:01');
select pruebas.ok('Alerta nueva queda pendiente para Telegram',
  (select bool_and(estado = 'pendiente' and intentos = 0) from public.alertas));
select pruebas.ok('Humedad alta genera su alerta',
  (select count(*) from public.alertas where tipo = 'humedad_alta') = 1);

-- CA-09.2: pasado el intervalo, la alerta se repite.
update public.alertas set creada_en = now() - interval '11 minutes' where tipo = 'temperatura_baja';
select pruebas.como(pruebas.id('ctrl_a'));
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('cuna'), 'temperatura', 15, '°C', '2026-11-01 12:13+00');
select pruebas.como_servidor();
select pruebas.ok('CA-09.2 se repite tras el intervalo',
  (select count(*) from public.alertas where tipo = 'temperatura_baja') = 2);

-- CA-10: ventana de 22:00 a 06:00 de domingo. 2026-11-02 es lunes.
select pruebas.como(pruebas.id('ana'));
insert into public.horarios (dispositivo_id, tipo, dias, hora_inicio, hora_fin)
  values (pruebas.id('cuna'), 'movimiento', '{0}', '22:00', '06:00');
select pruebas.como(pruebas.id('ctrl_a'));
insert into public.eventos (dispositivo_id, tipo, ocurrido_en)  -- lunes 12:00 local: fuera
  values (pruebas.id('cuna'), 'movimiento', '2026-10-26 18:00+00');
insert into public.eventos (dispositivo_id, tipo, ocurrido_en)  -- lunes 01:00 local: dentro, cruza medianoche
  values (pruebas.id('cuna'), 'movimiento', '2026-10-26 07:00+00');
select pruebas.como_servidor();
select pruebas.ok('CA-10.1 y CA-10.2 solo se guarda lo que está dentro de la ventana',
  (select count(*) from public.eventos where tipo = 'movimiento') = 1);
select pruebas.ok('CA-10.3 movimiento dentro de la ventana alerta',
  (select count(*) from public.alertas where tipo = 'movimiento') = 1);

-- CA-13
select pruebas.como(pruebas.id('ana'));
insert into public.audios (nombre, archivo_path, tamano_bytes)
  values ('Nana', auth.uid() || '/nana.mp3', 1000);
select pruebas.falla('CA-13.3 otro formato', format($$ insert into public.audios (nombre, archivo_path, tamano_bytes) values ('W', %L, 1) $$, auth.uid() || '/a.wav'), 'audios_solo_mp3');
select pruebas.falla('CA-13.3 mayor a 5 MB', format($$ insert into public.audios (nombre, archivo_path, tamano_bytes) values ('G', %L, 6000000) $$, auth.uid() || '/g.mp3'), 'audios_tamano_valido');
select pruebas.como(pruebas.id('ctrl_a'));
select pruebas.ok('La cuna del mismo dueño lee los audios', (select count(*) from public.audios) = 1);
select pruebas.como(pruebas.id('beto'));
select pruebas.ok('RNF-14 otro usuario no ve audios', (select count(*) from public.audios) = 0);


-- ----------------------------------------------------------------------- EP04
select pruebas.como(pruebas.id('ctrl_b'));
select pruebas.falla('CA-15.2 sin bebé no activa la siesta',
  format($$ insert into public.snapshots_peso (dispositivo_id, peso_base_g) values (%L, 100) $$, pruebas.id('colchon')),
  'No se detecta al bebé');
insert into public.snapshots_peso (dispositivo_id, peso_base_g) values (pruebas.id('colchon'), 4000);
select pruebas.falla('Una sola siesta activa',
  format($$ insert into public.snapshots_peso (dispositivo_id, peso_base_g) values (%L, 4000) $$, pruebas.id('colchon')),
  'snapshots_peso_una_siesta_activa');
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('colchon'), 'alarma_antirrobo', 1000, 'g', '2026-11-01 15:00+00');

select pruebas.como_servidor();
select pruebas.ok('CA-15.1 snapshot activa la siesta y queda con perfil',
  (select c.siesta_activa and s.perfil_id = pruebas.id('sofia')
     from public.configuracion c join public.snapshots_peso s using (dispositivo_id)
    where c.dispositivo_id = pruebas.id('colchon')));
select pruebas.ok('CA-16.1 alerta crítica',
  (select severidad from public.alertas where tipo = 'antirrobo') = 'critica');
select pruebas.ok('CA-17.2 mensaje con perfil, porcentaje y hora',
  (select mensaje from public.alertas where tipo = 'antirrobo')
    = 'ALARMA ANTI-ROBO: Sofía. Peso perdido: 75.0 %. Hora: 01/11/2026 09:00');

select pruebas.como(pruebas.id('beto'));
select pruebas.falla('CA-18.2 sin permiso no desactiva',
  format($$ select public.desactivar_siesta(%L) $$, pruebas.id('colchon')), 'permiso de control');

-- Carla ve pero no controla; Dani controla (CA-18.2).
select pruebas.como(pruebas.id('ana'));
select public.compartir_perfil(pruebas.id('sofia'), 'carla@test.cr', false);
select public.compartir_perfil(pruebas.id('sofia'), 'dani@test.cr', true);
select pruebas.falla('Compartir con correo inexistente',
  format($$ select public.compartir_perfil(%L, 'nadie@test.cr') $$, pruebas.id('sofia')), 'No existe');
select pruebas.ok('El propietario no se quita a sí mismo el control',
  pruebas.filas($$ update public.acceso_perfil set puede_controlar = false where usuario_id = auth.uid() $$) = 0);

select pruebas.como(pruebas.id('carla'));
select pruebas.ok('Usuario con acceso ve el perfil compartido', (select count(*) from public.perfiles_bebe) = 1);
select pruebas.ok('Usuario con acceso ve las alertas', (select count(*) from public.alertas where tipo = 'antirrobo') = 1);
select pruebas.falla('Acceso sin control no desactiva la siesta',
  format($$ select public.desactivar_siesta(%L) $$, pruebas.id('colchon')), 'permiso de control');
select pruebas.falla('Acceso sin control no manda comandos',
  format($$ insert into public.comandos (dispositivo_id, tipo) values (%L, 'probar_luz') $$, pruebas.id('cuna')),
  'row-level security');
select pruebas.falla('Nadie manda desactivar_siesta sin dejar registro',
  format($$ insert into public.comandos (dispositivo_id, tipo) values (%L, 'desactivar_siesta') $$, pruebas.id('colchon')),
  'row-level security');

select pruebas.como(pruebas.id('dani'));
select public.desactivar_siesta(pruebas.id('colchon'));

select pruebas.como_servidor();
select pruebas.ok('CA-18.2 registra quién y cuándo en la alerta',
  (select desactivada_por = pruebas.id('dani') and desactivada_en is not null from public.alertas where tipo = 'antirrobo'));
select pruebas.ok('CA-18.2 cierra el snapshot y la siesta',
  (select s.desactivado_por = pruebas.id('dani') and not c.siesta_activa
     from public.snapshots_peso s join public.configuracion c using (dispositivo_id)
    where s.dispositivo_id = pruebas.id('colchon')));
select pruebas.ok('CA-18.2 manda el comando para apagar el buzzer',
  (select estado from public.comandos where tipo = 'desactivar_siesta') = 'pendiente');
select pruebas.ok('CA-18.2 queda en el historial con el correo',
  (select descripcion from public.eventos where tipo = 'siesta_desactivada') = 'Modo siesta desactivado por dani@test.cr');

-- Flujo 3: comando
select pruebas.como(pruebas.id('ana'));
insert into public.comandos (dispositivo_id, tipo, parametros)
  values (pruebas.id('cuna'), 'audio_reproducir', '{"audio": "nana"}');
select pruebas.ok('El comando registra quién lo creó',
  (select creado_por from public.comandos where tipo = 'audio_reproducir') = auth.uid());
select pruebas.ok('La app no marca comandos: el UPDATE no afecta filas',
  pruebas.filas($$ update public.comandos set estado = 'ejecutado' where tipo = 'audio_reproducir' $$) = 0);
select pruebas.como(pruebas.id('ctrl_a'));
update public.comandos set estado = 'ejecutado', ejecutado_en = now() where tipo = 'audio_reproducir';
select pruebas.ok('Flujo 3 el controlador lo marca ejecutado',
  (select estado from public.comandos where tipo = 'audio_reproducir') = 'ejecutado');
select pruebas.ok('Un controlador no ve comandos ajenos',
  (select count(*) from public.comandos where tipo = 'desactivar_siesta') = 0);


-- ----------------------------------------------------------------------- EP05
select pruebas.como(pruebas.id('ana'));
insert into public.horarios (dispositivo_id, tipo, dias, hora_inicio, hora_fin, secuencia)
  values (pruebas.id('movil'), 'movil', '{1,2}', '08:00', '09:00', 2);
select pruebas.falla('CA-22.3 traslape el mismo día',
  format($$ insert into public.horarios (dispositivo_id, tipo, dias, hora_inicio, hora_fin, secuencia) values (%L, 'movil', '{2}', '08:30', '10:00', 1) $$, pruebas.id('movil')),
  'traslapa');
insert into public.horarios (dispositivo_id, tipo, dias, hora_inicio, hora_fin, secuencia)
  values (pruebas.id('movil'), 'movil', '{1}', '09:00', '10:00', 1);  -- Justo al terminar: permitido
insert into public.horarios (dispositivo_id, tipo, dias, hora_inicio, hora_fin, secuencia)
  values (pruebas.id('movil'), 'movil', '{6}', '23:00', '01:00', 1);  -- Sábado, cruza al domingo
select pruebas.falla('CA-22.3 traslape que cruza el fin de semana',
  format($$ insert into public.horarios (dispositivo_id, tipo, dias, hora_inicio, hora_fin, secuencia) values (%L, 'movil', '{0}', '00:30', '02:00', 1) $$, pruebas.id('movil')),
  'traslapa');
select pruebas.falla('El móvil necesita secuencia',
  format($$ insert into public.horarios (dispositivo_id, tipo, dias, hora_inicio, hora_fin) values (%L, 'movil', '{3}', '08:00', '09:00') $$, pruebas.id('movil')),
  'horarios_secuencia_movil');
select pruebas.falla('Horario de seguridad en otro dispositivo',
  format($$ insert into public.horarios (dispositivo_id, tipo, dias, hora_inicio, hora_fin) values (%L, 'seguridad', '{3}', '08:00', '09:00') $$, pruebas.id('movil')),
  'no aplica');
select pruebas.falla('CA-21 solo 3 velocidades',
  format($$ update public.configuracion set movil_velocidad = 4 where dispositivo_id = %L $$, pruebas.id('movil')),
  'configuracion_velocidad');

select pruebas.como_servidor();
select public.aplicar_horarios('2026-11-02 14:00+00');  -- Lunes 08:00 local
select pruebas.ok('CA-22.1 el móvil enciende con su secuencia',
  (select movil_encendido and movil_secuencia = 2 from public.configuracion where dispositivo_id = pruebas.id('movil')));
select public.aplicar_horarios('2026-11-03 16:00+00');  -- Martes 10:00 local: sin horario
select pruebas.ok('Sin horario a esa hora, no cambia',
  (select movil_encendido from public.configuracion where dispositivo_id = pruebas.id('movil')));
select public.aplicar_horarios('2026-11-03 15:00+00');  -- Martes 09:00 local
select pruebas.ok('CA-22.2 el móvil se apaga al terminar',
  (select not movil_encendido from public.configuracion where dispositivo_id = pruebas.id('movil')));
select public.aplicar_horarios('2026-11-08 07:00+00');  -- Domingo 01:00 local, viene del sábado
select pruebas.ok('Horario que cruza medianoche se apaga al día siguiente',
  (select not movil_encendido from public.configuracion where dispositivo_id = pruebas.id('movil')));


-- ----------------------------------------------------------------------- EP06
select pruebas.como(pruebas.id('ctrl_a'));
insert into public.eventos (dispositivo_id, tipo, ocurrido_en)
  values (pruebas.id('seguridad'), 'puerta', '2026-11-01 10:00+00');
select pruebas.como_servidor();
select pruebas.ok('CA-24.2 con seguridad desarmada no se registra la puerta',
  (select count(*) from public.eventos where tipo = 'puerta') = 0);

-- CA-23.1: horario de armado, lunes a las 20:00 local.
select pruebas.como(pruebas.id('ana'));
insert into public.horarios (dispositivo_id, tipo, dias, hora_inicio, hora_fin)
  values (pruebas.id('seguridad'), 'seguridad', '{1}', '20:00', '06:00');
select pruebas.como_servidor();
select public.aplicar_horarios('2026-11-03 02:00+00');
select pruebas.ok('CA-23.1 llega el horario y queda armada',
  (select seguridad_armada from public.configuracion where dispositivo_id = pruebas.id('seguridad')));
select pruebas.ok('Armar queda en el historial',
  (select count(*) from public.eventos where tipo = 'seguridad_armada') = 1);

select pruebas.como(pruebas.id('ctrl_a'));
insert into public.eventos (dispositivo_id, tipo, ocurrido_en)
  values (pruebas.id('seguridad'), 'puerta', '2026-11-01 10:00+00');
insert into public.eventos (dispositivo_id, tipo, foto_path, ocurrido_en)
  values (pruebas.id('seguridad'), 'presencia', pruebas.id('seguridad') || '/foto1.jpg', '2026-11-01 10:01+00');
select pruebas.falla('RNF-23 no se cita una foto de otra carpeta',
  format($$ insert into public.eventos (dispositivo_id, tipo, foto_path) values (%L, 'presencia', %L) $$, pruebas.id('seguridad'), pruebas.id('cuna') || '/x.jpg'),
  'carpeta del dispositivo');

select pruebas.como_servidor();
select pruebas.ok('CA-24.1 evento y alerta de puerta',
  (select count(*) from public.alertas where tipo = 'puerta') = 1);
select pruebas.ok('CA-26.2 la foto queda vinculada al evento',
  (select c.foto_path = pruebas.id('seguridad') || '/foto1.jpg' and e.tipo = 'presencia'
     from public.capturas c join public.eventos e on e.id = c.evento_id));
select pruebas.ok('CA-27.1 la alerta lleva la foto',
  (select foto_path from public.alertas where tipo = 'presencia') = pruebas.id('seguridad') || '/foto1.jpg');

-- CA-23.2: el desarme manual dura hasta el siguiente intervalo.
select pruebas.como(pruebas.id('ana'));
update public.configuracion set seguridad_armada = false where dispositivo_id = pruebas.id('seguridad');
select pruebas.como_servidor();
select public.aplicar_horarios('2026-11-03 03:00+00');  -- Lunes 21:00 local, dentro del intervalo
select pruebas.ok('CA-23.2 sigue desarmada dentro del intervalo',
  (select not seguridad_armada from public.configuracion where dispositivo_id = pruebas.id('seguridad')));

-- HU-28 y RNF-23
select pruebas.como(pruebas.id('carla'));
select pruebas.ok('CA-28.1 galería con tipo de evento',
  (select tipo_evento from public.v_galeria) = 'presencia');
select pruebas.como(pruebas.id('beto'));
select pruebas.ok('RNF-23 sin acceso no ve capturas', (select count(*) from public.v_galeria) = 0);


-- ----------------------------------------------------------------------- CA-05
select pruebas.como(pruebas.id('ana'));
update public.dispositivos set perfil_id = pruebas.id('mateo') where id = pruebas.id('cuna');
select pruebas.como(pruebas.id('ctrl_a'));
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('cuna'), 'temperatura', 30, '°C', '2026-11-01 13:00+00');
select pruebas.como_servidor();
select pruebas.ok('CA-05.1 lecturas nuevas con el perfil B',
  (select perfil_id from public.eventos where ocurrido_en = '2026-11-01 13:00+00') = pruebas.id('mateo'));
select pruebas.ok('CA-05.1 alertas nuevas con el perfil B',
  (select perfil_id from public.alertas where tipo = 'temperatura_alta') = pruebas.id('mateo'));
select pruebas.ok('CA-05.2 lo anterior sigue en el perfil A',
  (select perfil_id from public.eventos where ocurrido_en = '2026-11-01 12:00+00') = pruebas.id('sofia'));
select pruebas.como(pruebas.id('carla'));
select pruebas.ok('Acceso a A no da acceso a lo nuevo de B',
  (select count(*) from public.eventos where perfil_id = pruebas.id('mateo')) = 0);
select pruebas.ok('Acceso a A conserva lo viejo de A',
  (select count(*) from public.eventos where ocurrido_en = '2026-11-01 12:00+00') = 1);

select pruebas.como(pruebas.id('beto'));
select pruebas.falla('Asignar un dispositivo ajeno no afecta filas',
  format($$ do $d$ begin
    update public.dispositivos set perfil_id = null where id = %L;
    if not found then raise exception 'sin filas'; end if;
  end $d$ $$, pruebas.id('cuna')), 'sin filas');


-- ----------------------------------------------------------------------- EP08
select pruebas.como(pruebas.id('ana'));
select pruebas.ok('CA-33 biberón con su propio rango',
  (select temp_min = 35 and temp_max = 40 from public.configuracion where dispositivo_id = pruebas.id('biberon')));
select pruebas.como(pruebas.id('ctrl_c'));
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('biberon'), 'temperatura_biberon', 45, '°C', '2026-11-01 14:00+00');
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('biberon'), 'temperatura_biberon', 20, '°C', '2026-11-01 14:01+00');
select pruebas.como_servidor();
select pruebas.ok('CA-33.1 Demasiado caliente',
  (select mensaje like 'Demasiado caliente%' from public.alertas where tipo = 'biberon_caliente'));
select pruebas.ok('CA-33.2 Demasiado fría',
  (select mensaje like 'Demasiado fría%' from public.alertas where tipo = 'biberon_fria'));
delete from public.alertas where tipo like 'biberon%';
select pruebas.como(pruebas.id('ana'));
update public.configuracion set temp_max = 50 where dispositivo_id = pruebas.id('biberon');
select pruebas.como(pruebas.id('ctrl_c'));
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('biberon'), 'temperatura_biberon', 45, '°C', '2026-11-01 14:02+00');
select pruebas.como_servidor();
select pruebas.ok('CA-33.3 usa el rango nuevo',
  (select count(*) from public.alertas where tipo = 'biberon_caliente') = 0);

select pruebas.como(pruebas.id('ana'));
insert into public.tomas (perfil_id, inicio) values (pruebas.id('sofia'), '2026-11-01 08:00+00');
select pruebas.falla('Una sola toma en curso por perfil',
  format($$ insert into public.tomas (perfil_id) values (%L) $$, pruebas.id('sofia')), 'tomas_una_en_curso');
select pruebas.falla('CA-35.1 no hay cantidad sin finalizar',
  $$ update public.tomas set cantidad_ml = 90 $$, 'tomas_cantidad_al_finalizar');
update public.tomas set fin = '2026-11-01 08:15+00';
select pruebas.ok('CA-34.2 inicio, fin y duración',
  (select duracion_s from public.tomas) = 900);
select pruebas.falla('CA-35.2 cantidad negativa', $$ update public.tomas set cantidad_ml = -1 $$, 'tomas_cantidad_valida');
update public.tomas set cantidad_ml = 90;
select pruebas.ok('CA-35.1 cantidad guardada', (select cantidad_ml from public.tomas) = 90);

insert into public.recordatorios (perfil_id, tipo, intervalo_min) values (pruebas.id('sofia'), 'intervalo', 180);
insert into public.recordatorios (perfil_id, tipo, hora) values (pruebas.id('mateo'), 'hora_fija', '12:00');
select pruebas.falla('Recordatorio sin sus datos',
  format($$ insert into public.recordatorios (perfil_id, tipo) values (%L, 'hora_fija') $$, pruebas.id('sofia')),
  'recordatorios_datos_por_tipo');
select pruebas.como_servidor();
select public.revisar_recordatorios('2026-11-01 10:00+00');  -- 1 h 45 min después
select pruebas.ok('CA-36.1 antes del intervalo no avisa',
  (select count(*) from public.alertas where tipo = 'recordatorio') = 0);
select public.revisar_recordatorios('2026-11-01 11:16+00');
select pruebas.ok('CA-36.1 pasado el intervalo avisa',
  (select mensaje from public.alertas where tipo = 'recordatorio') = 'Hora de alimentar a Sofía');
select public.revisar_recordatorios('2026-11-01 11:17+00');
select pruebas.ok('CA-36.1 no repite hasta otra toma',
  (select count(*) from public.alertas where tipo = 'recordatorio') = 1);
select public.revisar_recordatorios('2026-11-01 18:01+00');  -- 12:01 local
select public.revisar_recordatorios('2026-11-01 18:02+00');
select pruebas.ok('CA-36.2 hora fija avisa una vez',
  (select count(*) from public.alertas where tipo = 'recordatorio' and mensaje = 'Hora de alimentar a Mateo') = 1);


-- ----------------------------------------------------------------------- EP10
select pruebas.como(pruebas.id('ana'));
select pruebas.ok('CA-40.1 columnas del CSV en UTC-6',
  (select fecha_hora || '|' || perfil || '|' || dispositivo || '|' || tipo || '|' || valor || '|' || unidad
     from public.v_historial where ocurrido_en = '2026-11-01 12:00+00')
    = '2026-11-01 06:00:00|Sofía|Cuna|temperatura|22|°C');
select pruebas.ok('CA-39.2 fecha futura sin registros',
  (select count(*) from public.v_historial where ocurrido_en > now() + interval '1 day') = 0);
select pruebas.como(pruebas.id('ctrl_a'));
insert into public.eventos (dispositivo_id, tipo, valor, ocurrido_en)
  values (pruebas.id('cuna'), 'temperatura', 22, now() + interval '1 year');
select pruebas.como(pruebas.id('ana'));
select pruebas.ok('Un reloj adelantado no crea eventos futuros',
  (select count(*) from public.v_historial where ocurrido_en > clock_timestamp()) = 0);
select pruebas.como(pruebas.id('beto'));
select pruebas.ok('RNF-14 otro usuario no ve historial', (select count(*) from public.v_historial) = 0);
select pruebas.ok('RNF-14 otro usuario no ve alertas', (select count(*) from public.alertas) = 0);


-- -------------------------------------------------------------------- Storage
select pruebas.como(pruebas.id('ctrl_a'));
insert into storage.objects (bucket_id, name)
  values ('capturas', pruebas.id('seguridad') || '/foto1.jpg');
select pruebas.falla('RNF-23 un controlador no sube a la carpeta de otro',
  format($$ insert into storage.objects (bucket_id, name) values ('capturas', %L) $$, pruebas.id('colchon') || '/x.jpg'),
  'row-level security');
select pruebas.como(pruebas.id('beto'));
select pruebas.falla('Un usuario no sube capturas',
  format($$ insert into storage.objects (bucket_id, name) values ('capturas', %L) $$, pruebas.id('seguridad') || '/y.jpg'),
  'row-level security');
select pruebas.ok('RNF-23 sin acceso al perfil no ve la foto',
  (select count(*) from storage.objects where bucket_id = 'capturas') = 0);
select pruebas.como(pruebas.id('carla'));
select pruebas.ok('RNF-23 con acceso al perfil ve la foto',
  (select count(*) from storage.objects where bucket_id = 'capturas') = 1);
select pruebas.como(pruebas.id('ana'));
insert into storage.objects (bucket_id, name) values ('audios', auth.uid() || '/nana.mp3');
select pruebas.falla('Un usuario no sube audios a la carpeta de otro',
  format($$ insert into storage.objects (bucket_id, name) values ('audios', %L) $$, pruebas.id('beto') || '/n.mp3'),
  'row-level security');
select pruebas.como(pruebas.id('ctrl_a'));
select pruebas.ok('La cuna del mismo dueño puede descargar el audio',
  (select count(*) from storage.objects where bucket_id = 'audios') = 1);
select pruebas.como(pruebas.id('beto'));
select pruebas.ok('Otro usuario no ve el audio',
  (select count(*) from storage.objects where bucket_id = 'audios') = 0);


-- ------------------------------------------------------------------ Retención
select pruebas.como_servidor();
insert into public.eventos (dispositivo_id, tipo, valor, ocurrido_en)
  values (pruebas.id('cuna'), 'temperatura', 22, now() - interval '91 days');
select public.purgar_historial();
select pruebas.ok('RNF-25 se purga lo de más de 90 días',
  (select count(*) from public.eventos where ocurrido_en < now() - interval '90 days') = 0);
insert into public.eventos (dispositivo_id, tipo, foto_path, ocurrido_en)
  select pruebas.id('seguridad'), 'sistema', pruebas.id('seguridad') || '/vieja.jpg', now() - interval '91 days';
select public.purgar_historial();
select pruebas.ok('RNF-25 lo que tiene foto se conserva',
  (select count(*) from public.capturas where foto_path like '%vieja.jpg') = 1);


-- ------------------------------------------------- Permisos de funciones y anon
select pruebas.ok('anon no entra a ninguna tabla',
  not exists (
    select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r', 'v')
      and has_table_privilege('anon', c.oid, 'select,insert,update,delete')));
select pruebas.ok('anon no entra a las tablas de Telegram si esa migración ya corrió',
  to_regclass('public.alerta_envios') is null
  or not has_table_privilege('anon', 'public.alerta_envios', 'select'));
select pruebas.ok('RLS activo en todas las tablas',
  not exists (
    select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity));
select pruebas.ok('La app no llama tareas internas',
  not has_function_privilege('authenticated', 'public.marcar_fuera_de_linea()', 'execute')
  and not has_function_privilege('authenticated', 'public.aplicar_horarios(timestamptz)', 'execute')
  and not has_function_privilege('authenticated', 'public.provisionar_dispositivo(text,text,uuid)', 'execute')
  and not has_function_privilege('authenticated', 'public.crear_alerta(public.eventos,text,text,text,numeric,interval)', 'execute'));
select pruebas.ok('anon no llama funciones',
  not has_function_privilege('anon', 'public.registrar_senal(uuid,jsonb)', 'execute'));
select pruebas.ok('Cuatro tareas programadas',
  (select count(*) from cron.job where jobname in
    ('dispositivos-fuera-de-linea', 'aplicar-horarios', 'revisar-recordatorios', 'purgar-historial')) = 4);
select pruebas.ok('Buckets privados',
  (select count(*) from storage.buckets where id in ('capturas', 'audios') and not public) = 2);
select pruebas.ok('Tablas publicadas en Realtime',
  (select count(*) from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public') = 4);


-- ------------------------------------------------------------- CA-03.2 al final
select pruebas.como(pruebas.id('dani'));
select pruebas.falla('Solo el dueño elimina un perfil',
  format($$ select public.eliminar_perfil(%L) $$, pruebas.id('sofia')), 'permiso');
select pruebas.como(pruebas.id('ana'));
select public.eliminar_perfil(pruebas.id('sofia'));
select pruebas.como_servidor();
select pruebas.ok('CA-03.2 dispositivos sin asignar',
  (select count(*) from public.dispositivos where perfil_id = pruebas.id('sofia')) = 0);
select pruebas.ok('CA-03.2 historial conservado',
  (select count(*) from public.eventos where perfil_id = pruebas.id('sofia')) > 0);
select pruebas.como(pruebas.id('ana'));
select pruebas.ok('CA-03.2 la dueña sigue viendo ese historial',
  (select count(*) from public.v_historial where perfil = 'Sofía') > 0);
select pruebas.falla('No se asigna a un perfil eliminado',
  format($$ update public.dispositivos set perfil_id = %L where id = %L $$, pruebas.id('sofia'), pruebas.id('cuna')),
  'row-level security');
select pruebas.como(pruebas.id('ctrl_a'));
insert into public.eventos (dispositivo_id, tipo, valor, unidad, ocurrido_en)
  values (pruebas.id('seguridad'), 'sistema', 1, 'x', '2026-11-01 16:00+00');
select pruebas.como(pruebas.id('ana'));
select pruebas.ok('Lo registrado sin perfil lo ve el dueño del dispositivo',
  (select count(*) from public.v_historial where ocurrido_en = '2026-11-01 16:00+00' and perfil_id is null) = 1);


-- ----------------------------------------------------------------- Resultado
select pruebas.como_servidor();
\o
select case when ok then 'ok    ' else 'FALLA ' end || nombre || coalesce(' -> ' || case when ok then null else detalle end, '')
  from pruebas.resultados order by ok desc, n;
select format('%s pruebas, %s fallas', count(*), count(*) filter (where not ok)) from pruebas.resultados;
\o /dev/null
rollback;
