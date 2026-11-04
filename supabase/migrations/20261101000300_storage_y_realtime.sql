-- =============================================================================
-- Migración base 4 de 5: buckets privados y tablas publicadas por Realtime.
-- Autor: Andrés Guzmán (AG)
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Buckets privados: se leen con URLs firmadas de corta duración.
--   capturas/<dispositivo_id>/<archivo>.jpg   máx. 150 KB (RNF-05)
--   audios/<propietario_id>/<archivo>.mp3     máx. 5 MB   (CA-13.2, CA-13.3)
-- -----------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('capturas', 'capturas', false, 153600,  array['image/jpeg']),
  ('audios',   'audios',   false, 5242880, array['audio/mpeg'])
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

-- Cada controlador sube solo a la carpeta de sus dispositivos.
create policy capturas_subir on storage.objects
  for insert to authenticated
  with check (
    bucket_id = 'capturas'
    and public.es_credencial_dispositivo(((storage.foldername(name))[1])::uuid)
  );

-- RNF-23: la foto se ve solo con acceso al perfil del evento que la registró.
create policy capturas_ver on storage.objects
  for select to authenticated
  using (
    bucket_id = 'capturas'
    and exists (
      select 1 from public.capturas c
      where c.foto_path = name
        and public.puede_ver_historial(c.perfil_id, c.dispositivo_id))
  );

create policy audios_subir on storage.objects
  for insert to authenticated
  with check (bucket_id = 'audios' and (storage.foldername(name))[1] = auth.uid()::text);

create policy audios_ver on storage.objects
  for select to authenticated
  using (
    bucket_id = 'audios'
    and (
      (storage.foldername(name))[1] = auth.uid()::text
      or exists (
        select 1 from public.dispositivos d
        where d.credencial_id = auth.uid()
          and d.propietario_id::text = (storage.foldername(name))[1])
    )
  );

create policy audios_borrar on storage.objects
  for delete to authenticated
  using (bucket_id = 'audios' and (storage.foldername(name))[1] = auth.uid()::text);


-- -----------------------------------------------------------------------------
-- Realtime: comandos y configuración hacia el dispositivo; última lectura y
-- alertas hacia la app. Realtime respeta el RLS de cada suscriptor.
-- -----------------------------------------------------------------------------
alter publication supabase_realtime
  add table public.dispositivos, public.configuracion, public.comandos, public.alertas;
