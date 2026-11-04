-- =============================================================================
-- Datos semilla (Fase 0 del plan de trabajo): los seis dispositivos, un perfil y
-- las asignaciones, para que ningún carril dependa de HU-04 y HU-05.
-- Autor: Andrés Guzmán (AG)
--
-- Antes de ejecutarlo, crear en Dashboard -> Authentication -> Users estas cuatro
-- cuentas, con Auto Confirm y una contraseña propia. Las contraseñas no van en
-- este archivo (RNF-15):
--   admin@ecosistema.test          administrador de prueba
--   controlador-a@ecosistema.test  Raspberry Pi: cuna y seguridad
--   controlador-b@ecosistema.test  ESP32: colchón
--   controlador-c@ecosistema.test  ESP32: móvil, juguete y biberón
--
-- Se puede ejecutar varias veces. Si faltan las cuentas, avisa y no hace nada.
-- =============================================================================
do $$
declare
  v_admin  uuid := (select id from auth.users where email = 'admin@ecosistema.test');
  v_ctrl_a uuid := (select id from auth.users where email = 'controlador-a@ecosistema.test');
  v_ctrl_b uuid := (select id from auth.users where email = 'controlador-b@ecosistema.test');
  v_ctrl_c uuid := (select id from auth.users where email = 'controlador-c@ecosistema.test');
  v_perfil uuid;
begin
  if v_admin is null or v_ctrl_a is null or v_ctrl_b is null or v_ctrl_c is null then
    raise notice 'Semilla omitida: primero cree las cuentas indicadas en supabase/seed.sql';
    return;
  end if;

  perform public.provisionar_dispositivo('CUNA-001',      'cuna',      v_ctrl_a);
  perform public.provisionar_dispositivo('SEGURIDAD-001', 'seguridad', v_ctrl_a);
  perform public.provisionar_dispositivo('COLCHON-001',   'colchon',   v_ctrl_b);
  perform public.provisionar_dispositivo('MOVIL-001',     'movil',     v_ctrl_c);
  perform public.provisionar_dispositivo('JUGUETE-001',   'juguete',   v_ctrl_c);
  perform public.provisionar_dispositivo('BIBERON-001',   'biberon',   v_ctrl_c);

  select id into v_perfil from public.perfiles_bebe
   where propietario_id = v_admin and nombre = 'Bebé de prueba' and eliminado_en is null;

  if v_perfil is null then
    insert into public.perfiles_bebe (propietario_id, nombre, fecha_nacimiento)
    values (v_admin, 'Bebé de prueba', date '2026-01-15')
    returning id into v_perfil;
  end if;

  update public.dispositivos
     set propietario_id = v_admin,
         perfil_id      = v_perfil,
         nombre         = coalesce(nombre, initcap(tipo)),
         registrado_en  = coalesce(registrado_en, now())
   where codigo in ('CUNA-001', 'SEGURIDAD-001', 'COLCHON-001',
                    'MOVIL-001', 'JUGUETE-001', 'BIBERON-001');
end;
$$;
