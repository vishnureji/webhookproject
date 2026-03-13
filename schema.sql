-- Run this in Railway's Postgres Query tab to set up your table

CREATE TABLE IF NOT EXISTS articles_master (
    article_id      TEXT PRIMARY KEY,
    headline        TEXT,
    slug            TEXT,
    author_id       TEXT,
    author_name     TEXT,
    pub_date        DATE,
    post_url        TEXT,
    body            TEXT,
    last_modified   TIMESTAMP
);

-- Optional: index for faster lookups by date or author
CREATE INDEX IF NOT EXISTS idx_articles_pub_date ON articles_master (pub_date);
CREATE INDEX IF NOT EXISTS idx_articles_author_id ON articles_master (author_id);
