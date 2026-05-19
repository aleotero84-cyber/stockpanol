-- =====================================================
-- PAÑOL — Script de creación de tablas en Supabase
-- Ejecutar en: Supabase Dashboard → SQL Editor
-- =====================================================

-- Tabla de ítems
CREATE TABLE IF NOT EXISTS paniol_items (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(200) NOT NULL,
    categoria   VARCHAR(100) DEFAULT 'otro',
    ubicacion   VARCHAR(200) DEFAULT '',
    cantidad    INTEGER NOT NULL DEFAULT 0,
    minimo      INTEGER NOT NULL DEFAULT 0,
    descripcion TEXT    DEFAULT '',
    creado      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tabla de movimientos
CREATE TABLE IF NOT EXISTS paniol_movimientos (
    id               SERIAL PRIMARY KEY,
    id_item          INTEGER NOT NULL,
    nombre_item      VARCHAR(200),
    tipo             VARCHAR(10) CHECK (tipo IN ('entrada', 'salida')),
    cantidad         INTEGER NOT NULL,
    responsable      VARCHAR(200) DEFAULT '',
    stock_resultante INTEGER NOT NULL,
    fecha            TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Acceso público de lectura (para que cualquiera pueda ver el stock)
ALTER TABLE paniol_items       ENABLE ROW LEVEL SECURITY;
ALTER TABLE paniol_movimientos ENABLE ROW LEVEL SECURITY;

CREATE POLICY "lectura_publica_items" ON paniol_items
    FOR SELECT USING (true);

CREATE POLICY "lectura_publica_movimientos" ON paniol_movimientos
    FOR SELECT USING (true);

-- Escritura solo desde el servidor (anon key desde Streamlit)
CREATE POLICY "escritura_items" ON paniol_items
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "escritura_movimientos" ON paniol_movimientos
    FOR ALL USING (true) WITH CHECK (true);

-- =====================================================
-- Datos de ejemplo (opcional, podés borrar esto)
-- =====================================================
INSERT INTO paniol_items (nombre, categoria, ubicacion, cantidad, minimo, descripcion) VALUES
    ('Martillo 500g',         'herramienta', 'Estante A1', 5, 2, 'Martillo de carpintero'),
    ('Destornillador Phillips','herramienta', 'Estante A1', 8, 3, 'Talle 2'),
    ('Cinta métrica 5m',      'herramienta', 'Estante A2', 4, 2, ''),
    ('Cable UTP Cat6 (m)',     'material',    'Depósito B', 120, 20, 'Por metro'),
    ('Conector RJ45',          'material',    'Cajón C3',   50, 10, ''),
    ('Taladro Percutor',       'equipo',      'Estante D1', 2,  1, 'Black & Decker'),
    ('Guantes de seguridad',   'consumible',  'Cajón E1',   15,  5, 'Talle L');
