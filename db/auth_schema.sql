-- Autenticación por API key por tenant (Fase 2).
--
-- Cada migración debe poder aplicarse sola: `scripts/migrate.py` las corre en orden
-- alfabético y esta queda primera, así que no da por hecho nada de las demás.
--
-- No se guarda la clave, solo su SHA-256. Una filtración de la base no entrega
-- credenciales usables, y como contrapartida una clave perdida no se puede recuperar:
-- se rota con `scripts/gestionar_tenants.py rotar`.

CREATE TABLE IF NOT EXISTS tenants (
    id            SERIAL PRIMARY KEY,
    nombre        VARCHAR(120) NOT NULL UNIQUE,
    api_key_hash  CHAR(64)     NOT NULL UNIQUE,  -- SHA-256 en hexadecimal
    rol           VARCHAR(20)  NOT NULL DEFAULT 'user',  -- 'user' | 'admin'
    activo        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP    DEFAULT NOW(),
    CONSTRAINT tenants_rol_valido CHECK (rol IN ('user', 'admin'))
);

-- La autenticación busca por `api_key_hash` en cada petición. No se añade un índice
-- aparte: el `UNIQUE` de la columna ya crea uno, y la búsqueda por igualdad lo usa.
