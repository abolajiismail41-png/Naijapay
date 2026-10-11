PRICING_DDL = [
    """CREATE OR REPLACE FUNCTION pricing_snapshot_immutable() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION 'pricing_snapshots is append-only'; END; $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER trg_pricing_snapshots_immutable BEFORE UPDATE OR DELETE ON pricing_snapshots
       FOR EACH ROW EXECUTE FUNCTION pricing_snapshot_immutable()""",
    """CREATE TRIGGER trg_pricing_snapshots_no_truncate BEFORE TRUNCATE ON pricing_snapshots
       FOR EACH STATEMENT EXECUTE FUNCTION pricing_snapshot_immutable()""",
]
