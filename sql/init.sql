-- Reference schema for the Book Store bot (manual use only).
--
-- The application creates these tables itself from the SQLAlchemy models
-- (bot/models.py via init_db / create_all), which is the single source of
-- truth. This file is NOT mounted into Postgres by docker-compose — it exists
-- only as documentation or for setting up a database by hand.
--
-- Plain PostgreSQL: distances are computed with the haversine formula in SQL,
-- so no PostGIS extension is required.

CREATE TABLE IF NOT EXISTS stores (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    address       VARCHAR(500),               -- nullable: many rows are map-pin only
    phone         VARCHAR(120),
    working_hours VARCHAR(255),
    description   TEXT,
    latitude      DOUBLE PRECISION NOT NULL,
    longitude     DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stores_coords ON stores (latitude, longitude);

CREATE TABLE IF NOT EXISTS users (
    id            BIGINT PRIMARY KEY,
    username      VARCHAR(255),
    first_name    VARCHAR(255),
    language_code VARCHAR(16),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
