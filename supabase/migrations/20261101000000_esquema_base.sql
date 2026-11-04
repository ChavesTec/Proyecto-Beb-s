-- =============================================================================
-- Migración base 1 de 5: tablas e índices (SRS 3.4, Tabla 2).
-- Autor: Andrés Guzmán (AG)
--
-- Convenciones:
--   * Fechas en UTC con timestamptz; se muestran en UTC-6 (RNF-26).
--   * Valores permitidos con text + check, igual que la migración de Telegram.
--   * alertas.id es bigint y usuarios.id es uuid: lo pide el contrato de
--     README_TELEGRAM.md.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Usuarios y perfiles (EP01)
-- -----------------------------------------------------------------------------

-- Las contraseñas viven en Supabase Auth (RNF-12); aquí nunca se guardan.
-- Las cuentas de los controladores existen en auth.users pero no aquí.
create table public.usuarios (
  id                    uuid primary key references auth.users (id) on delete cascade,
  correo                text        not null unique,
  nombre                text,
  rol                   text        not null default 'administrador'
                          check (rol in ('administrador', 'usuario')),
  telegram_chat_id      bigint unique,   -- NULL = no ha vinculado (CA-37.2)
  telegram_vinculado_en timestamptz,
  creado_en             timestamptz not null default now()
);

-- eliminado_en: borrado lógico. El historial sigue asociado al perfil (CA-03.2).
create table public.perfiles_bebe (
  id               uuid primary key default gen_random_uuid(),
  propietario_id   uuid        not null references public.usuarios (id) on delete cascade,
  nombre           text        not null check (btrim(nombre) <> ''),
  fecha_nacimiento date        not null,
  creado_en        timestamptz not null default now(),
  eliminado_en     timestamptz
);

create index perfiles_bebe_propietario_idx on public.perfiles_bebe (propietario_id);

-- Quién puede ver un perfil y quién puede además controlarlo (CA-18.2).
-- El propietario también tiene su fila: se crea sola con un trigger.
create table public.acceso_perfil (
  usuario_id      uuid        not null references public.usuarios (id) on delete cascade,
  perfil_id       uuid        not null references public.perfiles_bebe (id) on delete cascade,
  puede_controlar boolean     not null default true,
  creado_en       timestamptz not null default now(),
  primary key (usuario_id, perfil_id)
);

create index acceso_perfil_perfil_idx on public.acceso_perfil (perfil_id);


-- -----------------------------------------------------------------------------
-- Dispositivos (EP02)
-- -----------------------------------------------------------------------------

-- Un dispositivo nace sin dueño (provisionar_dispositivo) y el administrador lo
-- reclama con su código (HU-04). perfil_id es una sola columna, así que un
-- dispositivo no puede estar en dos perfiles a la vez (CA-05.3).
-- credencial_id es la cuenta de Auth del controlador: un mismo controlador
-- maneja varios dispositivos (por ejemplo, móvil, juguete y biberón).
create table public.dispositivos (
  id              uuid primary key default gen_random_uuid(),
  codigo          text        not null unique check (btrim(codigo) <> ''),
  tipo            text        not null
                    check (tipo in ('cuna', 'colchon', 'movil', 'seguridad', 'juguete', 'biberon')),
  nombre          text,
  propietario_id  uuid references public.usuarios (id) on delete set null,
  perfil_id       uuid references public.perfiles_bebe (id) on delete set null,
  credencial_id   uuid references auth.users (id) on delete set null,
  en_linea        boolean     not null default false,
  ultima_senal_en timestamptz,
  ultima_lectura  jsonb,               -- vista en vivo, se actualiza cada 5 s
  registrado_en   timestamptz,         -- cuándo lo reclamó el administrador
  creado_en       timestamptz not null default now(),

  constraint dispositivos_perfil_requiere_dueno
    check (perfil_id is null or propietario_id is not null)
);

create index dispositivos_propietario_idx on public.dispositivos (propietario_id);
create index dispositivos_perfil_idx      on public.dispositivos (perfil_id);
create index dispositivos_credencial_idx  on public.dispositivos (credencial_id);

-- Una fila por dispositivo, creada con un trigger. El dispositivo la recibe por
-- Realtime y conserva su último estado al reiniciar (CA-11.3).
-- Los valores por defecto son los umbrales estándar de CA-09.4. El biberón
-- recibe su propio rango de temperatura en crear_configuracion().
create table public.configuracion (
  dispositivo_id           uuid primary key references public.dispositivos (id) on delete cascade,

  -- Cuna (HU-09, HU-11) y biberón (HU-33)
  temp_min                 numeric(5,2) not null default 18,
  temp_max                 numeric(5,2) not null default 26,
  hum_min                  numeric(5,2) not null default 40,
  hum_max                  numeric(5,2) not null default 60,
  alerta_repeticion_min    integer      not null default 10,   -- CA-09.2
  luz_intensidad           smallint     not null default 0,

  -- Colchón (HU-15, HU-16). siesta_activa solo cambia con funciones del servidor.
  siesta_activa            boolean      not null default false,
  peso_minimo_g            numeric(8,2) not null default 500,  -- CA-15.2
  alarma_caida_pct         numeric(5,2) not null default 30,   -- CA-16.1

  -- Móvil (HU-20 a HU-22)
  movil_encendido          boolean      not null default false,
  movil_secuencia          smallint     not null default 1,
  movil_velocidad          smallint     not null default 2,

  -- Seguridad (HU-23, HU-26)
  seguridad_armada         boolean      not null default false,
  seguridad_intervalo_foto_s integer    not null default 30,   -- CA-26.3

  -- Juguete (HU-30, HU-31)
  juguete_tiempo_ronda_s   integer      not null default 10,
  juguete_volumen          smallint     not null default 50,

  actualizado_en           timestamptz  not null default now(),

  constraint configuracion_rango_temperatura check (temp_min < temp_max),   -- CA-09.3
  constraint configuracion_rango_humedad     check (hum_min < hum_max and hum_min >= 0 and hum_max <= 100),
  constraint configuracion_repeticion        check (alerta_repeticion_min > 0),
  constraint configuracion_luz               check (luz_intensidad between 0 and 100),
  constraint configuracion_peso_minimo       check (peso_minimo_g >= 0),
  constraint configuracion_caida             check (alarma_caida_pct > 0 and alarma_caida_pct <= 100),
  constraint configuracion_secuencia         check (movil_secuencia > 0),
  constraint configuracion_velocidad         check (movil_velocidad between 1 and 3),  -- CA-21
  constraint configuracion_intervalo_foto    check (seguridad_intervalo_foto_s > 0),
  constraint configuracion_tiempo_ronda      check (juguete_tiempo_ronda_s > 0),
  constraint configuracion_volumen           check (juguete_volumen between 0 and 100)
);

-- Horarios del móvil (HU-22), de la seguridad (HU-23) y ventanas de movimiento
-- de la cuna (HU-10). dias: 0 = domingo ... 6 = sábado, en hora de Costa Rica.
-- Si hora_fin < hora_inicio, el horario cruza la medianoche.
create table public.horarios (
  id             uuid primary key default gen_random_uuid(),
  dispositivo_id uuid        not null references public.dispositivos (id) on delete cascade,
  tipo           text        not null check (tipo in ('movil', 'seguridad', 'movimiento')),
  dias           smallint[]  not null,
  hora_inicio    time        not null,
  hora_fin       time        not null,
  secuencia      smallint,            -- solo para el móvil
  activo         boolean     not null default true,
  creado_en      timestamptz not null default now(),

  constraint horarios_dias_validos
    check (cardinality(dias) > 0 and dias <@ array[0, 1, 2, 3, 4, 5, 6]::smallint[]),
  constraint horarios_horas_distintas check (hora_inicio <> hora_fin),
  constraint horarios_horas_en_minutos
    check (extract(second from hora_inicio) = 0 and extract(second from hora_fin) = 0),
  constraint horarios_secuencia_movil
    check ((tipo = 'movil') = (secuencia is not null))
);

create index horarios_dispositivo_idx on public.horarios (dispositivo_id, tipo);

-- La app inserta, el dispositivo lo recibe por Realtime y lo marca (flujo 3).
create table public.comandos (
  id             bigint generated always as identity primary key,
  dispositivo_id uuid        not null references public.dispositivos (id) on delete cascade,
  tipo           text        not null
                   check (tipo in ('activar_siesta', 'desactivar_siesta',
                                   'audio_reproducir', 'audio_detener',
                                   'probar_luz', 'probar_buzzer', 'tomar_foto')),
  parametros     jsonb       not null default '{}',
  estado         text        not null default 'pendiente'
                   check (estado in ('pendiente', 'ejecutado', 'fallido')),
  resultado      text,                -- p. ej. "No se detecta al bebé" (CA-15.2)
  creado_por     uuid default auth.uid() references public.usuarios (id) on delete set null,
  creado_en      timestamptz not null default now(),
  ejecutado_en   timestamptz
);

create index comandos_pendientes_idx
  on public.comandos (dispositivo_id, creado_en)
  where estado = 'pendiente';


-- -----------------------------------------------------------------------------
-- Historial (EP10): lecturas y eventos en una sola tabla, porque el historial y
-- el CSV usan las mismas columnas (CA-40.1).
-- -----------------------------------------------------------------------------

-- perfil_id se copia del dispositivo al insertar: así una reasignación no cambia
-- el historial anterior (CA-05.1, CA-05.2).
-- foto_path: el dispositivo sube la foto primero y la indica aquí; el trigger
-- crea la captura y la alerta con foto en la misma transacción (flujo 4).
create table public.eventos (
  id             bigint generated always as identity primary key,
  dispositivo_id uuid        not null references public.dispositivos (id) on delete cascade,
  perfil_id      uuid references public.perfiles_bebe (id) on delete cascade,
  tipo           text        not null
                   check (tipo in ('temperatura', 'humedad', 'temperatura_biberon', 'peso',
                                   'movimiento', 'puerta', 'presencia',
                                   'alarma_antirrobo', 'siesta_activada', 'siesta_desactivada',
                                   'seguridad_armada', 'seguridad_desarmada',
                                   'conexion', 'juguete_acierto', 'sistema')),
  valor          numeric,
  unidad         text,
  descripcion    text,
  foto_path      text,
  ocurrido_en    timestamptz not null default now(),  -- hora en el dispositivo
  recibido_en    timestamptz not null default now(),  -- difiere si venía del buffer

  -- Si el buffer reenvía un evento ya guardado (RNF-17), no se duplica.
  -- También sirve como índice por (dispositivo, fecha).
  constraint eventos_sin_duplicados unique (dispositivo_id, ocurrido_en, tipo)
);

create index eventos_perfil_fecha_idx on public.eventos (perfil_id, ocurrido_en desc);
create index eventos_tipo_fecha_idx   on public.eventos (tipo, ocurrido_en desc);

-- estado, intentos y enviada_en son los que acordó la migración de Telegram.
create table public.alertas (
  id             bigint generated always as identity primary key,
  perfil_id      uuid references public.perfiles_bebe (id) on delete cascade,
  dispositivo_id uuid references public.dispositivos (id) on delete cascade,
  evento_id      bigint references public.eventos (id) on delete set null,
  tipo           text        not null
                   check (tipo in ('temperatura_baja', 'temperatura_alta',
                                   'humedad_baja', 'humedad_alta', 'movimiento',
                                   'antirrobo', 'puerta', 'presencia', 'fuera_de_linea',
                                   'biberon_caliente', 'biberon_fria', 'recordatorio')),
  severidad      text        not null default 'advertencia'
                   check (severidad in ('critica', 'advertencia', 'informativa')),
  mensaje        text        not null,
  valor          numeric,
  umbral         numeric,
  foto_path      text,
  estado         text        not null default 'pendiente',
  intentos       integer     not null default 0,
  enviada_en     timestamptz,
  desactivada_por uuid references public.usuarios (id) on delete set null,  -- CA-18.2
  desactivada_en timestamptz,
  creada_en      timestamptz not null default now(),

  constraint alertas_estado_valido
    check (estado in ('pendiente', 'enviada', 'fallida', 'sin_destinatarios'))
);

create index alertas_dispositivo_fecha_idx on public.alertas (dispositivo_id, creada_en desc);
create index alertas_perfil_fecha_idx      on public.alertas (perfil_id, creada_en desc);
create index alertas_evento_idx            on public.alertas (evento_id);


-- -----------------------------------------------------------------------------
-- Colchón (EP04)
-- -----------------------------------------------------------------------------
create table public.snapshots_peso (
  id              bigint generated always as identity primary key,
  dispositivo_id  uuid          not null references public.dispositivos (id) on delete cascade,
  perfil_id       uuid          not null references public.perfiles_bebe (id) on delete cascade,
  peso_base_g     numeric(8,2)  not null check (peso_base_g >= 0),
  creado_en       timestamptz   not null default now(),
  desactivado_en  timestamptz,         -- NULL = siesta en curso
  desactivado_por uuid references public.usuarios (id) on delete set null
);

create unique index snapshots_peso_una_siesta_activa
  on public.snapshots_peso (dispositivo_id)
  where desactivado_en is null;
create index snapshots_peso_perfil_idx on public.snapshots_peso (perfil_id, creado_en desc);


-- -----------------------------------------------------------------------------
-- Seguridad (EP06)
-- -----------------------------------------------------------------------------
create table public.capturas (
  id             bigint generated always as identity primary key,
  evento_id      bigint      not null references public.eventos (id) on delete cascade,
  dispositivo_id uuid        not null references public.dispositivos (id) on delete cascade,
  perfil_id      uuid references public.perfiles_bebe (id) on delete cascade,
  foto_path      text        not null unique,
  tomada_en      timestamptz not null
);

create index capturas_evento_idx on public.capturas (evento_id);
create index capturas_perfil_fecha_idx on public.capturas (perfil_id, tomada_en desc);
create index capturas_dispositivo_fecha_idx on public.capturas (dispositivo_id, tomada_en desc);


-- -----------------------------------------------------------------------------
-- Alimentación (EP08)
-- -----------------------------------------------------------------------------
create table public.tomas (
  id             bigint generated always as identity primary key,
  perfil_id      uuid         not null references public.perfiles_bebe (id) on delete cascade,
  dispositivo_id uuid references public.dispositivos (id) on delete set null,
  inicio         timestamptz  not null default now(),
  fin            timestamptz,
  duracion_s     integer generated always as (extract(epoch from (fin - inicio))::integer) stored,
  cantidad_ml    numeric(6,1),
  creado_por     uuid default auth.uid() references public.usuarios (id) on delete set null,

  constraint tomas_fin_despues_de_inicio check (fin is null or fin >= inicio),
  constraint tomas_cantidad_valida       check (cantidad_ml is null or cantidad_ml >= 0),  -- CA-35.2
  constraint tomas_cantidad_al_finalizar check (cantidad_ml is null or fin is not null)    -- CA-35.1
);

create index tomas_perfil_fecha_idx on public.tomas (perfil_id, inicio desc);
create unique index tomas_una_en_curso on public.tomas (perfil_id) where fin is null;

-- 'intervalo': intervalo_min después de la última toma (CA-36.1).
-- 'hora_fija': todos los días a esa hora de Costa Rica (CA-36.2).
create table public.recordatorios (
  id              uuid primary key default gen_random_uuid(),
  perfil_id       uuid        not null references public.perfiles_bebe (id) on delete cascade,
  tipo            text        not null check (tipo in ('intervalo', 'hora_fija')),
  intervalo_min   integer check (intervalo_min > 0),
  hora            time,
  activo          boolean     not null default true,
  ultimo_envio_en timestamptz,
  creado_en       timestamptz not null default now(),

  constraint recordatorios_datos_por_tipo check (
    (tipo = 'intervalo' and intervalo_min is not null and hora is null) or
    (tipo = 'hora_fija' and hora is not null and intervalo_min is null)
  )
);

create index recordatorios_perfil_idx on public.recordatorios (perfil_id);


-- -----------------------------------------------------------------------------
-- Audios de la cuna (HU-13). Ruta en Storage: <propietario_id>/<archivo>.mp3
-- -----------------------------------------------------------------------------
create table public.audios (
  id             uuid primary key default gen_random_uuid(),
  propietario_id uuid        not null default auth.uid() references public.usuarios (id) on delete cascade,
  nombre         text        not null check (btrim(nombre) <> ''),
  archivo_path   text        not null unique,
  tamano_bytes   integer     not null,
  creado_en      timestamptz not null default now(),

  -- CA-13.3. El bucket audios aplica los mismos límites al subir el archivo.
  constraint audios_solo_mp3     check (lower(archivo_path) like '%.mp3'),
  constraint audios_tamano_valido check (tamano_bytes > 0 and tamano_bytes <= 5242880)
);

create index audios_propietario_idx on public.audios (propietario_id);
