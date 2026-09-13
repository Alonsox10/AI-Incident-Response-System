CREATE TABLE IF NOT EXISTS faqs (
    id         SERIAL PRIMARY KEY,
    question   TEXT         NOT NULL,   -- la pregunta tal como la formula el usuario
    answer     TEXT         NOT NULL,   -- respuesta completa (causa probable + pasos)
    category   VARCHAR(100),
    embedding  vector(1536),            -- dimensión de text-embedding-3-small
    metadata   JSONB        DEFAULT '{}', -- severidad, origen, etc.
    created_at TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS faqs_embedding_idx
    ON faqs USING hnsw (embedding vector_cosine_ops);
