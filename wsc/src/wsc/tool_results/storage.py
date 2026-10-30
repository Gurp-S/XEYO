"""Session-scoped immutable UTF-8 files with bounded, verified range reads."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import codecs
import json
import os
import sqlite3
import stat
from uuid import uuid4

from ..contracts import encode, require
from ..evidence import link_like

CHARS = 16384


class ResultStore:
    def __init__(self, root, *, session, access=None, max_object_bytes=128*1024*1024,
                 max_storage_bytes=512*1024*1024):
        candidate=Path(root).absolute()
        for p in (candidate,*candidate.parents):
            require(not link_like(p),'tool_result_path_link')
        candidate.mkdir(parents=True,exist_ok=True)
        self.root=candidate.resolve();self.objects=self.root/'objects'
        require(not link_like(self.objects),'tool_result_path_link');self.objects.mkdir(exist_ok=True)
        self.db=self.root/'results.sqlite3'
        require(not link_like(self.db),'tool_result_path_link')
        require(type(session) is str and 0<len(session)<=256,'tool_result_session_invalid')
        require(type(max_object_bytes) is int and max_object_bytes>0 and
                type(max_storage_bytes) is int and max_storage_bytes>=max_object_bytes,'tool_result_storage_limits_invalid')
        self.session=session;self.access=access or (lambda *_:True)
        self.max_object_bytes=max_object_bytes;self.max_storage_bytes=max_storage_bytes
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS binding(singleton INTEGER PRIMARY KEY CHECK(singleton=1),session TEXT NOT NULL);'
                'CREATE TABLE IF NOT EXISTS objects(hash TEXT PRIMARY KEY,size INTEGER,chunks TEXT,index_sha TEXT);'
                'CREATE TABLE IF NOT EXISTS results(id INTEGER PRIMARY KEY,call_id TEXT UNIQUE,hash TEXT,meta TEXT);')
            row=db.execute('SELECT session FROM binding WHERE singleton=1').fetchone()
            require(row is None or row[0]==session,'tool_result_session_mismatch')
            if row is None:db.execute('INSERT OR IGNORE INTO binding VALUES (1,?)',(session,))
            require(db.execute('SELECT session FROM binding WHERE singleton=1').fetchone()[0]==session,'tool_result_session_mismatch')

    @contextmanager
    def connect(self):
        require(not link_like(self.db) and not link_like(self.objects),'tool_result_path_link')
        db=sqlite3.connect(self.db,timeout=10)
        try:
            with db:yield db
        finally:db.close()

    def _authorize(self, result_id):
        require(self.access(self.session,result_id,'read') is True,'Permission denied: tool result')

    def _file(self, digest, size):
        require(type(digest) is str and len(digest)==64 and all(c in '0123456789abcdef' for c in digest),'tool_result_object_invalid')
        path=self.objects/(digest+'.txt')
        require(not link_like(path),'tool_result_path_link')
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0))
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size!=size:
            os.close(fd);require(False,'tool_result_integrity_mismatch')
        return os.fdopen(fd,'rb')

    def capture(self, call_id, text, meta):
        require(type(call_id) is str and 0<len(call_id)<=256,'tool_result_call_invalid')
        require(type(text) is str,'tool_result_text_required')
        encoded=encode(meta);require(len(encoded.encode())<=16384,'tool_result_metadata_limit')
        temp=self.objects/('.'+uuid4().hex+'.tmp');chunks=[];size=0;digest=sha256();lines=0
        try:
            with temp.open('xb') as f:
                for start in range(0,len(text),CHARS):
                    raw=text[start:start+CHARS].encode('utf-8');size_next=size+len(raw)
                    require(size_next<=self.max_object_bytes,'tool_result_object_limit')
                    chunks.append([size,len(raw),sha256(raw).hexdigest(),lines])
                    f.write(raw);digest.update(raw);size=size_next;lines+=raw.count(b'\n')
                f.flush();os.fsync(f.fileno())
            key=digest.hexdigest();target=self.objects/(key+'.txt')
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                old=db.execute('SELECT id,hash,meta FROM results WHERE call_id=?',(call_id,)).fetchone()
                if old:
                    require(old[1:]==(key,encoded),'tool_result_call_identity_conflict')
                    existing=db.execute('SELECT size,chunks,index_sha FROM objects WHERE hash=?',(key,)).fetchone()
                    require(existing is not None,'tool_result_integrity_mismatch')
                    require(sha256(existing[1].encode()).hexdigest()==existing[2],'tool_result_index_invalid')
                    with self._file(key,existing[0]) as f:
                        for offset,length,h,_ in json.loads(existing[1]):
                            f.seek(offset);require(sha256(f.read(length)).hexdigest()==h,'tool_result_integrity_mismatch')
                    # Preserve the predecessor available when this call first
                    # committed. Later identical calls cannot change replay.
                    prior=db.execute('SELECT id,meta FROM results WHERE hash=? AND id<? ORDER BY id DESC LIMIT 1',
                                     (key,old[0])).fetchone()
                    previous=dict(id='r'+str(prior[0]),meta=json.loads(prior[1])) if prior else None
                    return 'r'+str(old[0]),previous,False
                previous=db.execute('SELECT id,meta FROM results WHERE hash=? ORDER BY id DESC LIMIT 1',(key,)).fetchone()
                obj=db.execute('SELECT size,chunks,index_sha FROM objects WHERE hash=?',(key,)).fetchone()
                if obj:
                    require(obj[0]==size,'tool_result_integrity_mismatch')
                    require(sha256(obj[1].encode()).hexdigest()==obj[2],'tool_result_index_invalid')
                    with self._file(key,size) as f:
                        for offset,length,h,_ in json.loads(obj[1]):
                            f.seek(offset);require(sha256(f.read(length)).hexdigest()==h,'tool_result_integrity_mismatch')
                else:
                    used=db.execute('SELECT COALESCE(SUM(size),0) FROM objects').fetchone()[0]
                    require(used+size<=self.max_storage_bytes,'tool_result_storage_limit')
                    # No overwrite of either a prior object or a link leaf.
                    try:os.link(temp,target)
                    except FileExistsError:
                        # An object may survive a process crash before its DB
                        # transaction commits. Reconcile only exact bytes.
                        pass
                    # A successful write/link alone is not a verified recovery
                    # target. Check the installed file before publishing its ID.
                    with self._file(key,size) as f:
                        for offset,length,h,_ in chunks:
                            f.seek(offset);require(sha256(f.read(length)).hexdigest()==h,'tool_result_integrity_mismatch')
                    if os.name!='nt':
                        fd=os.open(self.objects,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
                        try:os.fsync(fd)
                        finally:os.close(fd)
                    index=encode(chunks)
                    db.execute('INSERT INTO objects VALUES (?,?,?,?)',(key,size,index,sha256(index.encode()).hexdigest()))
                cursor=db.execute('INSERT INTO results(call_id,hash,meta) VALUES (?,?,?)',(call_id,key,encoded))
                prior=dict(id='r'+str(previous[0]),meta=json.loads(previous[1])) if previous else None
                return 'r'+str(cursor.lastrowid),prior,obj is None
        finally:
            if temp.exists():temp.unlink()

    def record(self, result_id):
        require(type(result_id) is str and len(result_id)<=20 and result_id.startswith('r') and result_id[1:].isascii() and result_id[1:].isdigit(),'tool_result_id_invalid')
        require(0<int(result_id[1:])<=9223372036854775807 and not result_id[1:].startswith('0'),'tool_result_id_invalid')
        self._authorize(result_id)
        with self.connect() as db:
            row=db.execute('SELECT r.hash,r.meta,o.size,o.chunks,o.index_sha,r.call_id FROM results r JOIN objects o ON r.hash=o.hash WHERE r.id=?',
                           (int(result_id[1:]),)).fetchone()
        require(row is not None,'tool_result_unavailable')
        require(sha256(row[3].encode()).hexdigest()==row[4],'tool_result_index_invalid')
        chunks=json.loads(row[3]);end=0;lines=0
        require(type(row[2]) is int and 0<=row[2]<=self.max_object_bytes and type(chunks) is list,'tool_result_index_invalid')
        for item in chunks:
            require(type(item) is list and len(item)==4,'tool_result_index_invalid')
            offset,length,h,before=item
            require(type(offset) is int and offset==end and type(length) is int and 0<length<=CHARS*4
                    and type(before) is int and before>=lines and type(h) is str and len(h)==64,'tool_result_index_invalid')
            end+=length;lines=before
        require(end==row[2],'tool_result_index_invalid')
        return dict(id=result_id,hash=row[0],meta=json.loads(row[1]),size=row[2],chunks=chunks,call_id=row[5])

    def prior(self, call_id, digest_hex, meta):
        """Read-only preview of capture(): same predecessor, no blob and no row."""
        require(type(call_id) is str and 0 < len(call_id) <= 256, 'tool_result_call_invalid')
        encoded = encode(meta); require(len(encoded.encode()) <= 16384, 'tool_result_metadata_limit')
        with self.connect() as db:
            old = db.execute('SELECT id,hash,meta FROM results WHERE call_id=?', (call_id,)).fetchone()
            if old:
                require(old[1:] == (digest_hex, encoded), 'tool_result_call_identity_conflict')
                row = db.execute('SELECT id,meta FROM results WHERE hash=? AND id<? ORDER BY id DESC LIMIT 1',
                                 (digest_hex, old[0])).fetchone()
                return 'r' + str(old[0]), (dict(id='r' + str(row[0]), meta=json.loads(row[1])) if row else None)
            row = db.execute('SELECT id,meta FROM results WHERE hash=? ORDER BY id DESC LIMIT 1',
                             (digest_hex,)).fetchone()
            nxt = db.execute('SELECT COALESCE(MAX(id),0)+1 FROM results').fetchone()[0]
            return 'r' + str(nxt), (dict(id='r' + str(row[0]), meta=json.loads(row[1])) if row else None)

    def find(self, call_id):
        """Derived-index lookup by call identity; None when the row is absent."""
        with self.connect() as db:
            row = db.execute('SELECT id FROM results WHERE call_id=?', (call_id,)).fetchone()
        return None if row is None else 'r' + str(row[0])

    def text(self, record):
        return b''.join(block for _, block in self.blocks(record)).decode('utf-8')

    def blocks(self, record, *, start=0, end=None):
        self._authorize(record['id']);end=record['size'] if end is None else end
        with self._file(record['hash'],record['size']) as f:
            for offset,length,h,_ in record['chunks']:
                if offset+length<=start:continue
                if offset>=end:break
                f.seek(offset);raw=f.read(length)
                require(sha256(raw).hexdigest()==h,'tool_result_integrity_mismatch')
                self._authorize(record['id'])
                low=max(start,offset);high=min(end,offset+length)
                yield low,raw[low-offset:high-offset]

    def read(self, result_id, *, offset=0, limit=8192):
        record=self.record(result_id)
        require(type(offset) is int and 0<=offset<=record['size'] and type(limit) is int and 4<=limit<=32768,'tool_result_range_invalid')
        raw=b''.join(b for _,b in self.blocks(record,start=offset,end=min(record['size'],offset+limit)))
        try:text=codecs.getincrementaldecoder('utf-8')().decode(raw,final=offset+len(raw)==record['size'])
        except UnicodeDecodeError:raise ValueError('tool_result_offset_not_utf8_boundary') from None
        end=offset+len(text.encode('utf-8'));self._authorize(result_id)
        return dict(result_id=result_id,text=text,offset=offset,end=end,total_bytes=record['size'],
                    next_offset=end if end<record['size'] else None,complete=offset==0 and end==record['size'],
                    representation='original_utf8',recovery=True)
