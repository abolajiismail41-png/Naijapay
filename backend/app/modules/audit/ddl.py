"""Append-only enforcement, shared by the migration and the test schema."""
IMMUTABLE_DDL = [
    """CREATE OR REPLACE FUNCTION audit_logs_immutable() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION 'audit_logs is append-only'; END; $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER trg_audit_logs_immutable BEFORE UPDATE OR DELETE ON audit_logs
       FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable()""",
    """CREATE TRIGGER trg_audit_logs_no_truncate BEFORE TRUNCATE ON audit_logs
       FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_immutable()""",
]
