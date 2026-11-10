-- =============================================================================
-- Fotos de evidencia en PNG (EP06, HU-26).
--
-- La Raspberry Pi Pico W con la OV7670 no puede comprimir en JPEG: guarda un
-- PNG RGB de 154x120 sin comprimir (~56 KB), que cabe en el límite de 150 KB
-- (RNF-05) y que la galería (Pillow) y Telegram (sendPhoto) aceptan.
--   capturas/<dispositivo_id>/<archivo>.jpg | .png   máx. 150 KB
-- =============================================================================

update storage.buckets
   set allowed_mime_types = array['image/jpeg', 'image/png']
 where id = 'capturas';
