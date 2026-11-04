-- =============================================================================
-- Migración base 3 de 5: permisos y RLS (RNF-14, RNF-23).
-- Autor: Andrés Guzmán (AG)
--
-- Dos capas:
--   * GRANT dice qué columnas se pueden tocar (p. ej. nadie cambia su rol ni su
--     chat de Telegram, y un dispositivo no elige el perfil de sus eventos).
--   * RLS dice qué filas.
-- anon no entra a nada: toda la app y los dispositivos usan una sesión con JWT.
-- service_role (solo en Edge Functions) ignora el RLS.
-- =============================================================================

revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all functions in schema public from public, anon, authenticated;

grant all on all tables    in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant all on all functions in schema public to service_role;

-- Supabase da permisos a anon en todo lo nuevo. Esto también cubre las tablas y
-- funciones de migraciones posteriores, como la de Telegram.
alter default privileges in schema public revoke all on tables    from anon;
alter default privileges in schema public revoke all on sequences from anon;
alter default privileges in schema public revoke all on functions from anon;


-- -----------------------------------------------------------------------------
-- Funciones que se pueden llamar desde la app o desde un dispositivo
-- -----------------------------------------------------------------------------

-- Las usan las políticas: se evalúan con el rol de quien consulta.
grant execute on function public.tiene_acceso_perfil(uuid)          to authenticated;
grant execute on function public.puede_controlar_perfil(uuid)       to authenticated;
grant execute on function public.es_propietario_perfil(uuid)        to authenticated;
grant execute on function public.es_credencial_dispositivo(uuid)    to authenticated;
grant execute on function public.puede_ver_dispositivo(uuid)        to authenticated;
grant execute on function public.puede_controlar_dispositivo(uuid)  to authenticated;
grant execute on function public.puede_ver_historial(uuid, uuid)    to authenticated;

-- RPC de la app
grant execute on function public.eliminar_perfil(uuid)                  to authenticated;
grant execute on function public.compartir_perfil(uuid, text, boolean)  to authenticated;
grant execute on function public.registrar_dispositivo(text, text)      to authenticated;
grant execute on function public.desactivar_siesta(uuid)                to authenticated;

-- RPC de los dispositivos
grant execute on function public.registrar_senal(uuid, jsonb)           to authenticated;


-- -----------------------------------------------------------------------------
-- Activar RLS en todas las tablas
-- -----------------------------------------------------------------------------
alter table public.usuarios       enable row level security;
alter table public.perfiles_bebe  enable row level security;
alter table public.acceso_perfil  enable row level security;
alter table public.dispositivos   enable row level security;
alter table public.configuracion  enable row level security;
alter table public.horarios       enable row level security;
alter table public.comandos       enable row level security;
alter table public.eventos        enable row level security;
alter table public.alertas        enable row level security;
alter table public.snapshots_peso enable row level security;
alter table public.capturas       enable row level security;
alter table public.tomas          enable row level security;
alter table public.recordatorios  enable row level security;
alter table public.audios         enable row level security;


-- -----------------------------------------------------------------------------
-- usuarios
-- -----------------------------------------------------------------------------
grant select on public.usuarios to authenticated;
grant update (nombre) on public.usuarios to authenticated;

create policy usuarios_ver_propio on public.usuarios
  for select to authenticated using (id = auth.uid());
create policy usuarios_editar_propio on public.usuarios
  for update to authenticated using (id = auth.uid()) with check (id = auth.uid());


-- -----------------------------------------------------------------------------
-- perfiles_bebe. Sin DELETE directo: se elimina con eliminar_perfil() (CA-03.2).
-- -----------------------------------------------------------------------------
grant select on public.perfiles_bebe to authenticated;
grant insert (propietario_id, nombre, fecha_nacimiento) on public.perfiles_bebe to authenticated;
grant update (nombre, fecha_nacimiento) on public.perfiles_bebe to authenticated;

create policy perfiles_ver on public.perfiles_bebe
  for select to authenticated using (public.tiene_acceso_perfil(id) or propietario_id = auth.uid());
create policy perfiles_crear on public.perfiles_bebe
  for insert to authenticated with check (propietario_id = auth.uid());
create policy perfiles_editar on public.perfiles_bebe
  for update to authenticated using (propietario_id = auth.uid()) with check (propietario_id = auth.uid());


-- -----------------------------------------------------------------------------
-- acceso_perfil. Se agrega con compartir_perfil(). El propietario no se quita.
-- -----------------------------------------------------------------------------
grant select, delete on public.acceso_perfil to authenticated;
grant update (puede_controlar) on public.acceso_perfil to authenticated;

create policy acceso_ver on public.acceso_perfil
  for select to authenticated
  using (usuario_id = auth.uid() or public.es_propietario_perfil(perfil_id));
create policy acceso_editar on public.acceso_perfil
  for update to authenticated
  using (usuario_id <> auth.uid() and public.es_propietario_perfil(perfil_id))
  with check (usuario_id <> auth.uid() and public.es_propietario_perfil(perfil_id));
create policy acceso_quitar on public.acceso_perfil
  for delete to authenticated
  using (usuario_id <> auth.uid() and public.es_propietario_perfil(perfil_id));


-- -----------------------------------------------------------------------------
-- dispositivos. Se reclaman con registrar_dispositivo(); la señal entra por
-- registrar_senal(). Directo, el dueño solo cambia nombre y perfil (CA-05.1).
-- -----------------------------------------------------------------------------
grant select on public.dispositivos to authenticated;
grant update (nombre, perfil_id) on public.dispositivos to authenticated;

create policy dispositivos_ver on public.dispositivos
  for select to authenticated
  using (propietario_id = auth.uid()
         or credencial_id = auth.uid()
         or public.tiene_acceso_perfil(perfil_id));
create policy dispositivos_editar on public.dispositivos
  for update to authenticated
  using (propietario_id = auth.uid())
  with check (
    propietario_id = auth.uid()
    and (perfil_id is null or exists (
          select 1 from public.perfiles_bebe p
          where p.id = perfil_id and p.propietario_id = auth.uid() and p.eliminado_en is null))
  );


-- -----------------------------------------------------------------------------
-- configuracion. siesta_activa no se puede cambiar directo.
-- -----------------------------------------------------------------------------
grant select on public.configuracion to authenticated;
grant update (temp_min, temp_max, hum_min, hum_max, alerta_repeticion_min, luz_intensidad,
              peso_minimo_g, alarma_caida_pct,
              movil_encendido, movil_secuencia, movil_velocidad,
              seguridad_armada, seguridad_intervalo_foto_s,
              juguete_tiempo_ronda_s, juguete_volumen)
  on public.configuracion to authenticated;

create policy configuracion_ver on public.configuracion
  for select to authenticated using (public.puede_ver_dispositivo(dispositivo_id));
create policy configuracion_editar on public.configuracion
  for update to authenticated
  using (public.puede_controlar_dispositivo(dispositivo_id))
  with check (public.puede_controlar_dispositivo(dispositivo_id));


-- -----------------------------------------------------------------------------
-- horarios
-- -----------------------------------------------------------------------------
grant select, delete on public.horarios to authenticated;
grant insert (dispositivo_id, tipo, dias, hora_inicio, hora_fin, secuencia, activo) on public.horarios to authenticated;
grant update (dias, hora_inicio, hora_fin, secuencia, activo) on public.horarios to authenticated;

create policy horarios_ver on public.horarios
  for select to authenticated using (public.puede_ver_dispositivo(dispositivo_id));
create policy horarios_crear on public.horarios
  for insert to authenticated with check (public.puede_controlar_dispositivo(dispositivo_id));
create policy horarios_editar on public.horarios
  for update to authenticated
  using (public.puede_controlar_dispositivo(dispositivo_id))
  with check (public.puede_controlar_dispositivo(dispositivo_id));
create policy horarios_borrar on public.horarios
  for delete to authenticated using (public.puede_controlar_dispositivo(dispositivo_id));


-- -----------------------------------------------------------------------------
-- comandos. La app crea; solo el controlador marca el resultado.
-- desactivar_siesta va por su función, que registra quién fue (CA-18.2).
-- -----------------------------------------------------------------------------
grant select on public.comandos to authenticated;
grant insert (dispositivo_id, tipo, parametros) on public.comandos to authenticated;
grant update (estado, resultado, ejecutado_en) on public.comandos to authenticated;

create policy comandos_ver on public.comandos
  for select to authenticated using (public.puede_ver_dispositivo(dispositivo_id));
create policy comandos_crear on public.comandos
  for insert to authenticated
  with check (public.puede_controlar_dispositivo(dispositivo_id) and tipo <> 'desactivar_siesta');
create policy comandos_marcar on public.comandos
  for update to authenticated
  using (public.es_credencial_dispositivo(dispositivo_id))
  with check (public.es_credencial_dispositivo(dispositivo_id));


-- -----------------------------------------------------------------------------
-- eventos
-- -----------------------------------------------------------------------------
grant select on public.eventos to authenticated;
grant insert (dispositivo_id, tipo, valor, unidad, descripcion, foto_path, ocurrido_en)
  on public.eventos to authenticated;

create policy eventos_ver on public.eventos
  for select to authenticated using (public.puede_ver_historial(perfil_id, dispositivo_id));
create policy eventos_crear on public.eventos
  for insert to authenticated with check (public.es_credencial_dispositivo(dispositivo_id));


-- -----------------------------------------------------------------------------
-- alertas. Solo la Edge Function (service_role) cambia estado e intentos.
-- -----------------------------------------------------------------------------
grant select on public.alertas to authenticated;
grant insert (dispositivo_id, tipo, severidad, mensaje, valor, umbral, foto_path, evento_id)
  on public.alertas to authenticated;

create policy alertas_ver on public.alertas
  for select to authenticated using (public.puede_ver_historial(perfil_id, dispositivo_id));
create policy alertas_crear on public.alertas
  for insert to authenticated with check (public.es_credencial_dispositivo(dispositivo_id));


-- -----------------------------------------------------------------------------
-- snapshots_peso
-- -----------------------------------------------------------------------------
grant select on public.snapshots_peso to authenticated;
grant insert (dispositivo_id, peso_base_g) on public.snapshots_peso to authenticated;

create policy snapshots_ver on public.snapshots_peso
  for select to authenticated using (public.puede_ver_historial(perfil_id, dispositivo_id));
create policy snapshots_crear on public.snapshots_peso
  for insert to authenticated with check (public.es_credencial_dispositivo(dispositivo_id));


-- -----------------------------------------------------------------------------
-- capturas. Las crea el trigger de eventos; aquí solo se leen (RNF-23).
-- -----------------------------------------------------------------------------
grant select on public.capturas to authenticated;

create policy capturas_ver on public.capturas
  for select to authenticated using (public.puede_ver_historial(perfil_id, dispositivo_id));


-- -----------------------------------------------------------------------------
-- tomas y recordatorios
-- -----------------------------------------------------------------------------
grant select on public.tomas to authenticated;
grant insert (perfil_id, dispositivo_id, inicio, fin, cantidad_ml) on public.tomas to authenticated;
grant update (fin, cantidad_ml) on public.tomas to authenticated;

create policy tomas_ver on public.tomas
  for select to authenticated using (public.tiene_acceso_perfil(perfil_id));
create policy tomas_crear on public.tomas
  for insert to authenticated with check (public.puede_controlar_perfil(perfil_id));
create policy tomas_editar on public.tomas
  for update to authenticated
  using (public.puede_controlar_perfil(perfil_id))
  with check (public.puede_controlar_perfil(perfil_id));

grant select, delete on public.recordatorios to authenticated;
grant insert (perfil_id, tipo, intervalo_min, hora, activo) on public.recordatorios to authenticated;
grant update (intervalo_min, hora, activo) on public.recordatorios to authenticated;

create policy recordatorios_ver on public.recordatorios
  for select to authenticated using (public.tiene_acceso_perfil(perfil_id));
create policy recordatorios_crear on public.recordatorios
  for insert to authenticated with check (public.puede_controlar_perfil(perfil_id));
create policy recordatorios_editar on public.recordatorios
  for update to authenticated
  using (public.puede_controlar_perfil(perfil_id))
  with check (public.puede_controlar_perfil(perfil_id));
create policy recordatorios_borrar on public.recordatorios
  for delete to authenticated using (public.puede_controlar_perfil(perfil_id));


-- -----------------------------------------------------------------------------
-- audios. La cuna del mismo dueño los puede leer para reproducirlos.
-- -----------------------------------------------------------------------------
grant select, delete on public.audios to authenticated;
grant insert (nombre, archivo_path, tamano_bytes) on public.audios to authenticated;
grant update (nombre) on public.audios to authenticated;

create policy audios_ver on public.audios
  for select to authenticated
  using (propietario_id = auth.uid() or exists (
    select 1 from public.dispositivos d
    where d.credencial_id = auth.uid() and d.propietario_id = audios.propietario_id));
create policy audios_crear on public.audios
  for insert to authenticated with check (propietario_id = auth.uid());
create policy audios_editar on public.audios
  for update to authenticated using (propietario_id = auth.uid()) with check (propietario_id = auth.uid());
create policy audios_borrar on public.audios
  for delete to authenticated using (propietario_id = auth.uid());


-- -----------------------------------------------------------------------------
-- Vistas
-- -----------------------------------------------------------------------------
grant select on public.v_historial, public.v_galeria to authenticated;
