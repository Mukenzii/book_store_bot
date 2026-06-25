-- Schema for the Book Store finder bot.
-- Plain PostgreSQL: distances are computed with the haversine formula in SQL,
-- so no PostGIS extension is required.

CREATE TABLE IF NOT EXISTS stores (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    address       VARCHAR(500) NOT NULL,
    phone         VARCHAR(50),
    working_hours VARCHAR(255),
    description   TEXT,
    latitude      DOUBLE PRECISION NOT NULL,
    longitude     DOUBLE PRECISION NOT NULL
);

-- Helps when the store catalogue grows large; ordering still does a scan +
-- sort on the computed distance, but lookups by coordinates stay cheap.
CREATE INDEX IF NOT EXISTS idx_stores_coords ON stores (latitude, longitude);
