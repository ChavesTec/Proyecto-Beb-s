select fecha_hora, perfil, dispositivo, tipo, valor, unidad
from public.v_historial order by ocurrido_en desc limit 50;