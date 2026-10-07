"""One-off DDL for the POC (no Alembic). Safe to re-run."""

from sqlalchemy import text

from app.db import engine

DDL = [
    "ALTER TABLE ov_exceptions ALTER COLUMN commodity_code TYPE VARCHAR(80)",
    "ALTER TABLE ov_exceptions ADD COLUMN IF NOT EXISTS source_osd_number BIGINT",
    "ALTER TABLE ov_exceptions DROP CONSTRAINT IF EXISTS uq_ov_exceptions_source_osd_number",
    "ALTER TABLE ov_exceptions ADD CONSTRAINT uq_ov_exceptions_source_osd_number UNIQUE (source_osd_number)",
    "ALTER TABLE ov_exceptions ADD COLUMN IF NOT EXISTS commodity_description VARCHAR(80) NOT NULL DEFAULT ''",
    # Multi-factor root cause: {factor: bool} alongside the existing category/confidence/reasoning.
    "ALTER TABLE root_cause_classifications ADD COLUMN IF NOT EXISTS contributing_factors JSON",
    "ALTER TABLE classification_cache ADD COLUMN IF NOT EXISTS contributing_factors JSON",
    # Effectiveness + escalation on recommendations (additive; existing rows default to active/0).
    "ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS status VARCHAR(12) NOT NULL DEFAULT 'active'",
    "ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS escalation_level INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS superseded_by_id UUID REFERENCES recommendations(id)",
    # expected_shipments and prevention_checks are new tables - Base.metadata.create_all() makes
    # them on startup, nothing to alter here.
]

if __name__ == "__main__":
    with engine.begin() as conn:
        for statement in DDL:
            conn.execute(text(statement))
            print("OK:", statement)
