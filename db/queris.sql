CREATE TABLE incidents (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255),
    title TEXT,
    description TEXT,
    category VARCHAR(100),
    priority VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE conversations (
    id UUID PRIMARY KEY,
    created_at TIMESTAMP DEFAULT NOW()
);
