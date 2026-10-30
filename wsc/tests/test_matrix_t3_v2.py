from pathlib import Path
from types import SimpleNamespace
import sqlite3
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from acceptance_matrix_v1.acceptors import load_candidate,accept_t3
from acceptance_matrix_v1.acceptor_t3_v2 import accept_t3_v2


class T3NeutralChecks(unittest.TestCase):
    def setUp(self):
        self.path=ROOT/'benchmarks/acceptance_matrix_v1/calibration/migration_reference.py'
        self.reference=load_candidate(self.path)
    def variant(self,name):
        scope={};exec(compile(self.path.read_text().replace('projects_migrating',name),str(self.path),'exec'),scope)
        return SimpleNamespace(migrate=scope['migrate'])
    def staging(self,result):
        return next(r for r in result['checks'] if r['check_id']=='staging-and-unrelated-preservation')
    def test_reference_and_alternative_quoted_stage_both_pass(self):
        for module in (self.reference,self.variant('other_stage'),self.variant('"stage""quoted"')):
            result=accept_t3_v2(module)
            self.assertTrue(result['success'],result)
            self.assertEqual(10,len(result['checks']))
    def test_original_private_name_false_negative_is_retained_but_not_repeated(self):
        module=self.variant('other_stage')
        self.assertFalse(accept_t3(module)['success'])
        result=accept_t3_v2(module)
        self.assertTrue(result['success']);self.assertFalse(result['legacy_result']['success'])
    def test_different_exception_class_is_valid_when_rejection_is_atomic(self):
        def migrate(db):
            try:self.reference.migrate(db)
            except Exception as error:raise RuntimeError('rejected') from error
        self.assertTrue(accept_t3_v2(SimpleNamespace(migrate=migrate))['success'])
    def test_deleting_existing_stage_cannot_pass(self):
        def migrate(db):
            db.execute('DROP TABLE IF EXISTS projects_migrating');self.reference.migrate(db)
        self.assertFalse(self.staging(accept_t3_v2(SimpleNamespace(migrate=migrate)))['passed'])
    def test_deleting_unrelated_table_cannot_pass(self):
        def migrate(db):
            db.execute('DROP TABLE IF EXISTS unrelated_customer_table');self.reference.migrate(db)
        self.assertFalse(self.staging(accept_t3_v2(SimpleNamespace(migrate=migrate)))['passed'])
    def test_mutation_before_rejection_cannot_pass(self):
        def migrate(db):
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='projects_migrating'").fetchone():
                db.execute('DELETE FROM projects_migrating');raise RuntimeError('rejected')
            self.reference.migrate(db)
        self.assertFalse(self.staging(accept_t3_v2(SimpleNamespace(migrate=migrate)))['passed'])
    def test_always_reject_is_not_a_success(self):
        def migrate(db):raise RuntimeError('no migration')
        self.assertFalse(accept_t3_v2(SimpleNamespace(migrate=migrate))['success'])
    def test_correct_in_place_migration_does_not_need_a_staging_table(self):
        def migrate(db):
            versions=db.execute('SELECT version FROM schema_version').fetchall()
            if len(versions)!=1 or versions[0][0] not in (1,2,3):raise RuntimeError('version')
            version=versions[0][0]
            if version==3:
                if {r[1] for r in db.execute('PRAGMA table_info(projects)')}!={'id','workspace_id','title','archived','row_version'}:raise RuntimeError('shape')
                return
            db.execute('SAVEPOINT in_place')
            try:
                if version==1:
                    db.execute('ALTER TABLE projects RENAME COLUMN tenant TO workspace_id')
                    db.execute('ALTER TABLE projects RENAME COLUMN deleted TO archived')
                db.execute('ALTER TABLE projects ADD COLUMN row_version INTEGER NOT NULL DEFAULT 1')
                active=set()
                for identity,workspace,title,archived in db.execute('SELECT id,workspace_id,title,archived FROM projects ORDER BY id').fetchall():
                    if not archived:
                        if (workspace,title) in active:db.execute('UPDATE projects SET archived=1 WHERE id=?',(identity,))
                        else:active.add((workspace,title))
                db.execute('CREATE UNIQUE INDEX active_title ON projects(workspace_id,title) WHERE archived=0')
                db.execute('UPDATE schema_version SET version=3');db.execute('RELEASE in_place')
            except Exception:
                db.execute('ROLLBACK TO in_place');db.execute('RELEASE in_place');raise
        result=accept_t3_v2(SimpleNamespace(migrate=migrate))
        self.assertTrue(result['success'],result)
        self.assertEqual([],result['staging_coverage']['observed_stage_names'])
    def test_committing_caller_and_resetting_rows_still_fail(self):
        for action in (lambda db:db.commit(),lambda db:db.execute('UPDATE projects SET row_version=1')):
            def migrate(db):self.reference.migrate(db);action(db)
            self.assertFalse(accept_t3_v2(SimpleNamespace(migrate=migrate))['success'])
    def test_unknown_attached_staging_is_unassessable_not_pass_or_failure(self):
        def migrate(db):
            if 'extra' not in {r[1] for r in db.execute('PRAGMA database_list')}:
                db.execute("ATTACH ':memory:' AS extra");db.execute('CREATE TABLE extra.stage(x)')
            self.reference.migrate(db)
        result=accept_t3_v2(SimpleNamespace(migrate=migrate))
        self.assertIsNone(self.staging(result)['passed'])
        self.assertIsNone(result['success']);self.assertEqual(1,result['unassessable_checks'])


if __name__=='__main__':unittest.main()
