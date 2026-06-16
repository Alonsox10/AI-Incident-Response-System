-- Tabla de incidentes usada por las herramientas del agente de recomendacion
CREATE TABLE IF NOT EXISTS incidents (
    id        SERIAL PRIMARY KEY,
    title     TEXT        NOT NULL,
    category  TEXT        NOT NULL,
    priority  TEXT        NOT NULL,
    created_at TIMESTAMP  DEFAULT NOW()
);
