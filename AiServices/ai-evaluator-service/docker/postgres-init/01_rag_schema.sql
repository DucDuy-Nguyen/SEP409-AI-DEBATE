-- Schema kho fact cho RAG Evidence. Chi chay khi volume con trong (lan dau khoi tao DB).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_source (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    topic        text NOT NULL,      -- 'education' | 'environment' | 'technology'
    source_type  text NOT NULL,      -- 'dataset' | 'url' | 'document' | 'manual'
    title        text,
    url          text,
    dataset_ref  text,               -- vd 'vifactcheck:<article_id>'
    created_at   timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fact_card (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       uuid REFERENCES knowledge_source(id) ON DELETE CASCADE,
    topic           text NOT NULL,
    content         text NOT NULL,
    citation        text,
    published_date  date,
    status          text NOT NULL DEFAULT 'approved',   -- 'pending' | 'approved'
    embedding       vector(1024),                       -- bge-m3 dense = 1024 chieu
    -- Config 'simple' vi Postgres khong co stemmer tieng Viet
    content_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    created_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fact_card_embedding ON fact_card USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_fact_card_content_tsv ON fact_card USING gin (content_tsv);
CREATE INDEX IF NOT EXISTS idx_fact_card_topic_status ON fact_card (topic, status);
