-- Habilitar la extensión pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Base de conocimiento: almacena fragmentos de documentos informativos con sus embeddings
-- Se usa para recuperación RAG cuando el agente necesita contexto de documentación técnica
CREATE TABLE IF NOT EXISTS knowledge_base (
    id           SERIAL PRIMARY KEY,
    content      TEXT         NOT NULL,
    source       VARCHAR(500),          -- nombre del documento o ruta del archivo
    chunk_index  INTEGER      DEFAULT 0, -- posición dentro del documento original
    embedding    vector(1536),           -- dimensión de text-embedding-3-small
    metadata     JSONB        DEFAULT '{}',
    created_at   TIMESTAMP    DEFAULT NOW()
);

-- Índice HNSW para búsqueda aproximada de vecinos más cercanos (funciona en tablas vacías)
CREATE INDEX IF NOT EXISTS knowledge_base_embedding_idx
    ON knowledge_base USING hnsw (embedding vector_cosine_ops);

-- Embeddings de incidentes: almacena incidentes históricos con sus resoluciones
-- Se usa para recuperación RAG y encontrar cómo se resolvieron incidentes similares en el pasado
CREATE TABLE IF NOT EXISTS incident_embeddings (
    id          SERIAL PRIMARY KEY,
    description TEXT         NOT NULL,
    category    VARCHAR(100),
    priority    VARCHAR(50),
    resolution  TEXT,
    embedding   vector(1536),
    created_at  TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS incident_embeddings_idx
    ON incident_embeddings USING hnsw (embedding vector_cosine_ops);
