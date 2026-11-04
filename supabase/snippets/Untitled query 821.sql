select count(*) from public.alertas a
join public.dispositivos d on d.id = a.dispositivo_id
where d.codigo = 'CUNA-001';