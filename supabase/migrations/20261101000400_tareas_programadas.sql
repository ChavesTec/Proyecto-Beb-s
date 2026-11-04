-- =============================================================================
-- Migración base 5 de 5: tareas de pg_cron.
-- Autor: Andrés Guzmán (AG)
--
-- cron.schedule con nombre reemplaza la tarea si ya existe, así que se puede
-- ejecutar más de una vez. El reintento de alertas fallidas (CA-38.3) no está
-- aquí: pertenece a la migración de Telegram.
-- =============================================================================
create extension if not exists pg_cron with schema pg_catalog;

select cron.schedule('dispositivos-fuera-de-linea', '* * * * *', 'select public.marcar_fuera_de_linea()');
select cron.schedule('aplicar-horarios',            '* * * * *', 'select public.aplicar_horarios()');
select cron.schedule('revisar-recordatorios',       '* * * * *', 'select public.revisar_recordatorios()');

-- 03:00 en Costa Rica = 09:00 UTC.
select cron.schedule('purgar-historial',            '0 9 * * *', 'select public.purgar_historial()');
