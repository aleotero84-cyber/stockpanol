-- =====================================================
-- PAÑOL — Script de creación de tablas en Supabase
-- Versión MULTI-ALMACÉN (soporta varios stocks independientes:
-- pañol, droguería, depósito, etc.)
-- Ejecutar en: Supabase Dashboard → SQL Editor
-- =====================================================

-- -----------------------------------------------------
-- Tabla de almacenes (cada uno es un "stock" independiente)
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS paniol_almacenes (
    id           SERIAL PRIMARY KEY,
    nombre       VARCHAR(150) NOT NULL,
    slug         VARCHAR(150) UNIQUE NOT NULL,
    icono        VARCHAR(10)  DEFAULT '📦',
    clave_hash   VARCHAR(256) NOT NULL,   -- hash SHA-256 de la contraseña de admin
    creado       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- -----------------------------------------------------
-- Tabla de ítems (ahora ligada a un almacén)
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS paniol_items (
    id           SERIAL PRIMARY KEY,
    almacen_id   INTEGER NOT NULL REFERENCES paniol_almacenes(id) ON DELETE CASCADE,
    nombre       VARCHAR(200) NOT NULL,
    categoria    VARCHAR(100) DEFAULT 'otro',
    ubicacion    VARCHAR(200) DEFAULT '',
    cantidad     INTEGER NOT NULL DEFAULT 0,
    minimo       INTEGER NOT NULL DEFAULT 0,
    descripcion  TEXT    DEFAULT '',
    creado       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_items_almacen ON paniol_items(almacen_id);

-- -----------------------------------------------------
-- Tabla de movimientos (también ligada a un almacén)
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS paniol_movimientos (
    id               SERIAL PRIMARY KEY,
    almacen_id       INTEGER NOT NULL REFERENCES paniol_almacenes(id) ON DELETE CASCADE,
    id_item          INTEGER NOT NULL,
    nombre_item      VARCHAR(200),
    tipo             VARCHAR(10) CHECK (tipo IN ('entrada', 'salida')),
    cantidad         INTEGER NOT NULL,
    responsable      VARCHAR(200) DEFAULT '',
    stock_resultante INTEGER NOT NULL,
    fecha            TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_movimientos_almacen ON paniol_movimientos(almacen_id);

-- -----------------------------------------------------
-- Seguridad a nivel de fila (RLS)
-- Lectura pública (cualquiera ve el stock sin login).
-- Escritura abierta porque el control de "quién puede escribir"
-- se hace en la app (pidiendo la contraseña del almacén).
-- -----------------------------------------------------
ALTER TABLE paniol_almacenes    ENABLE ROW LEVEL SECURITY;
ALTER TABLE paniol_items        ENABLE ROW LEVEL SECURITY;
ALTER TABLE paniol_movimientos  ENABLE ROW LEVEL SECURITY;

CREATE POLICY "lectura_publica_almacenes" ON paniol_almacenes
    FOR SELECT USING (true);
CREATE POLICY "lectura_publica_items" ON paniol_items
    FOR SELECT USING (true);
CREATE POLICY "lectura_publica_movimientos" ON paniol_movimientos
    FOR SELECT USING (true);

CREATE POLICY "escritura_almacenes" ON paniol_almacenes
    FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "escritura_items" ON paniol_items
    FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "escritura_movimientos" ON paniol_movimientos
    FOR ALL USING (true) WITH CHECK (true);

-- =====================================================
-- Almacén de ejemplo: "Pañol IACI" + sus ítems
-- Contraseña de este almacén de ejemplo: panol.unqui.iaci
-- (el hash de abajo corresponde a esa contraseña, SHA-256)
-- =====================================================
INSERT INTO paniol_almacenes (nombre, slug, icono, clave_hash) VALUES
    ('Pañol IACI', 'panol-iaci', '🔧',
     'aa86381c093b9d38c916f995a3cb15103408f33805fe7e796728f0ac3062112f')
ON CONFLICT (slug) DO NOTHING;

-- Insertamos los ítems de ejemplo asociados a ese almacén
INSERT INTO paniol_items (almacen_id, nombre, categoria, ubicacion, cantidad, minimo, descripcion)
SELECT a.id, v.nombre, v.categoria, v.ubicacion, v.cantidad, v.minimo, v.descripcion
FROM paniol_almacenes a
CROSS JOIN (VALUES
    ('Martillo 500g',          'herramienta', 'Estante A1', 5,   2,  'Martillo de carpintero'),
    ('Destornillador Phillips','herramienta', 'Estante A1', 8,   3,  'Talle 2'),
    ('Cinta métrica 5m',       'herramienta', 'Estante A2', 4,   2,  ''),
    ('Cable UTP Cat6 (m)',     'material',    'Depósito B', 120, 20, 'Por metro'),
    ('Conector RJ45',          'material',    'Cajón C3',   50,  10, ''),
    ('Taladro Percutor',       'equipo',      'Estante D1', 2,   1,  'Black & Decker'),
    ('Guantes de seguridad',   'consumible',  'Cajón E1',   15,  5,  'Talle L')
) AS v(nombre, categoria, ubicacion, cantidad, minimo, descripcion)
WHERE a.slug = 'panol-iaci'
  AND NOT EXISTS (SELECT 1 FROM paniol_items WHERE almacen_id = a.id);

-- NOTA: La contraseña de ejemplo es "panol.unqui.iaci".
-- Para crear un nuevo almacén (ej. una droguería) NO hace falta tocar
-- este script: se crea directamente desde la app con el botón
-- "+ Nuevo almacén" en el selector inicial.
