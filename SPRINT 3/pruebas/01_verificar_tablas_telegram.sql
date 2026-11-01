-- =============================================================================
-- Pruebas de la migración de Telegram (ejecutar en el proyecto de pruebas).
-- Corre cada bloque por separado en el SQL Editor y compara con lo esperado.
-- =============================================================================

-- PRUEBA A: crear una alerta y un código para el usuario de prueba.
-- Esperado: "Success". La alerta queda con estado = 'pendiente'.
insert into public.alertas (tipo, mensaje)
values ('temperatura', 'Temperatura baja en la cuna: 19 °C');

insert into public.codigos_telegram (usuario_id, codigo)
select id, '123456' from public.usuarios where correo = 'prueba@ecosistema.test';

select id, tipo, estado, intentos from public.alertas;
select codigo, expira_en, usado_en from public.codigos_telegram;


-- PRUEBA B: código repetido mientras el primero sigue sin usar.
-- Esperado: ERROR "duplicate key value violates unique constraint
--           codigos_telegram_codigo_activo_uq".
insert into public.codigos_telegram (usuario_id, codigo)
select id, '123456' from public.usuarios where correo = 'prueba@ecosistema.test';


-- PRUEBA C: código con letras.
-- Esperado: ERROR "violates check constraint".
insert into public.codigos_telegram (usuario_id, codigo)
select id, 'ABC123' from public.usuarios where correo = 'prueba@ecosistema.test';


-- PRUEBA D: registrar el envío de la alerta a un usuario.
-- Esperado: "Success" y una fila con estado = 'pendiente', intentos = 0.
insert into public.alerta_envios (alerta_id, usuario_id, chat_id)
select a.id, u.id, 123456789
from public.alertas a, public.usuarios u
where u.correo = 'prueba@ecosistema.test'
order by a.id desc limit 1;

select alerta_id, chat_id, estado, intentos from public.alerta_envios;


-- PRUEBA E: registrar el MISMO envío otra vez (evita mensajes duplicados).
-- Esperado: ERROR "duplicate key value violates unique constraint
--           alerta_envios_unico".
insert into public.alerta_envios (alerta_id, usuario_id, chat_id)
select a.id, u.id, 123456789
from public.alertas a, public.usuarios u
where u.correo = 'prueba@ecosistema.test'
order by a.id desc limit 1;


-- PRUEBA F: estado inválido.
-- Esperado: ERROR "violates check constraint alertas_estado_valido".
update public.alertas set estado = 'perdida';


-- LIMPIEZA (opcional): borra los datos de prueba, deja las tablas.
-- delete from public.alerta_envios;
-- delete from public.codigos_telegram;
-- delete from public.alertas;
