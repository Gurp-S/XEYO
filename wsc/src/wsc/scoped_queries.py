"""Opt-in prefix checks and a trigger-maintained presentation projection.

Original receipts remain authoritative. The projection is backfilled once and
maintained for insert/update/delete in the same SQLite transaction.
"""
from .contracts import require
from .store import getmeta


def existing_sources(db,ids):
    values=list(set(ids));known=set()
    for start in range(0,len(values),256):
        part=values[start:start+256]
        known.update(r[0] for r in db.execute('SELECT id FROM events WHERE id IN ('+','.join('?' for _ in part)+')',part))
    return known


def presentation_index(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wsc_presentation_sources_v1'").fetchone():return
    db.execute('CREATE TABLE wsc_presentation_sources_v1 (receipt_id TEXT NOT NULL,source_id TEXT NOT NULL,PRIMARY KEY(receipt_id,source_id))')
    db.execute('CREATE INDEX wsc_presented_source_v1 ON wsc_presentation_sources_v1(source_id)')
    db.execute("INSERT OR IGNORE INTO wsc_presentation_sources_v1 SELECT p.id,j.value FROM presentations p,json_each(p.data,'$.source_ids') j")
    for name,when,body in (
        ('insert','INSERT',"INSERT OR IGNORE INTO wsc_presentation_sources_v1 SELECT NEW.id,value FROM json_each(NEW.data,'$.source_ids');"),
        ('delete','DELETE','DELETE FROM wsc_presentation_sources_v1 WHERE receipt_id=OLD.id;'),
        ('update','UPDATE',"DELETE FROM wsc_presentation_sources_v1 WHERE receipt_id=OLD.id; INSERT OR IGNORE INTO wsc_presentation_sources_v1 SELECT NEW.id,value FROM json_each(NEW.data,'$.source_ids');")):
        db.execute(f'CREATE TRIGGER wsc_presented_{name}_v1 AFTER {when} ON presentations BEGIN {body} END')


def safe_boundary(db,cut,*,read_prefix):
    require(type(cut) is int and cut>0 and cut>=getmeta(db,'cursor'),'invalid_fold_boundary')
    prefix=read_prefix(db,cut)
    require(len(prefix)==cut,'source_boundary_missing')
    needed={r['id'] for r in prefix if r['kind']=='result'}
    delivered=set()
    if needed:
        presentation_index(db)
        values=list(needed)
        for start in range(0,len(values),256):
            part=values[start:start+256]
            delivered.update(r[0] for r in db.execute('SELECT DISTINCT source_id FROM wsc_presentation_sources_v1 WHERE source_id IN ('+','.join('?' for _ in part)+')',part))
    pending=set()
    for row in prefix:
        if row['kind']=='call':pending.add(row['call_id'])
        elif row['kind']=='result':
            pending.remove(row['call_id']);require(row['id'] in delivered,'result_presentation_unknown')
    require(not pending,'pending_tool_results')
    return prefix
