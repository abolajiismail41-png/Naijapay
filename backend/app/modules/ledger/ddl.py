"""Database-level ledger guarantees, shared by the migration and the test schema."""
LEDGER_DDL = [
    """CREATE OR REPLACE FUNCTION ledger_immutable() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION 'ledger is append-only'; END; $$ LANGUAGE plpgsql""",
    """CREATE OR REPLACE FUNCTION ledger_journal_balanced() RETURNS trigger AS $$
       DECLARE diff bigint;
       BEGIN
         SELECT COALESCE(SUM(CASE direction WHEN 'D' THEN amount_kobo ELSE -amount_kobo END), 0)
           INTO diff FROM ledger_entries WHERE journal_id = NEW.journal_id;
         IF diff <> 0 THEN
           RAISE EXCEPTION 'ledger journal % is unbalanced by % kobo', NEW.journal_id, diff;
         END IF;
         RETURN NULL;
       END; $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER trg_ledger_entries_immutable BEFORE UPDATE OR DELETE ON ledger_entries
       FOR EACH ROW EXECUTE FUNCTION ledger_immutable()""",
    """CREATE TRIGGER trg_ledger_journals_immutable BEFORE UPDATE OR DELETE ON ledger_journals
       FOR EACH ROW EXECUTE FUNCTION ledger_immutable()""",
    """CREATE TRIGGER trg_ledger_entries_no_truncate BEFORE TRUNCATE ON ledger_entries
       FOR EACH STATEMENT EXECUTE FUNCTION ledger_immutable()""",
    """CREATE TRIGGER trg_ledger_journals_no_truncate BEFORE TRUNCATE ON ledger_journals
       FOR EACH STATEMENT EXECUTE FUNCTION ledger_immutable()""",
    # Deferred: checked at COMMIT, so a journal's lines may be inserted in any order.
    """CREATE CONSTRAINT TRIGGER trg_ledger_entries_balanced AFTER INSERT ON ledger_entries
       DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ledger_journal_balanced()""",
]
