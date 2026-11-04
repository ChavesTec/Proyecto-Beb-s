insert into public.eventos (dispositivo_id, tipo, valor, unidad)
select id, 'temperatura', 15, '°C' from public.dispositivos where codigo = 'CUNA-001';

select tipo, severidad, mensaje, estado from public.alertas order by id desc limit 1;