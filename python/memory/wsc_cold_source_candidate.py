"""Sealed exact-source recall candidate using existing catalog/read primitives.

No semantic selection, goal inference, or hot historical-card generation.
Callers own when to recall; the snapshot owns source identities and bytes.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from memory.wsc_handoff_catalog import Catalog
from memory.wsc_handoff_recall import read


class ColdSources:
    def __init__(self,path,sha256):
        self.path=Path(path)
        raw=self.path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha256:
            raise ValueError('cold_source_seal_mismatch')
        self.sha256=sha256
        self._sources=[json.loads(line) for line in raw.decode('utf-8').split('\n') if line.strip()]
        self._catalog=Catalog(self._sources)

    def locator(self):
        return {'archive':str(self.path),'sha256':self.sha256,'source_count':len(self._sources)}

    def catalog(self,arguments):
        return deepcopy(self._catalog.read(arguments))

    def source(self,arguments):
        if not isinstance(arguments,dict):raise ValueError('handoff_source_invalid_arguments')
        args=dict(arguments);call_id=args.pop('call_id',None)
        if 'call_id' in arguments and (not isinstance(call_id,str) or not call_id):
            raise ValueError('cold_result_identity_invalid')
        # Native reader performs argument and source-identity validation before
        # result selection. Original row/hash stay the provenance authority.
        result=read(args,self._sources)
        row=next(row for row in self._sources if str(row.get('message_id') or row.get('id'))==args['message_id'])
        from synaptic.textutil import tool_result_blocks
        from synaptic.task_fact_sources import source_text
        blocks=list(tool_result_blocks(row))
        selected=[block for block in blocks if block.get('tool_use_id')==call_id] if call_id is not None else blocks
        if call_id is not None and len(selected)!=1:raise ValueError('cold_result_source_not_unique')
        if call_id is not None or source_text(row) is None and len(selected)==1:
            payload=selected[0].get('content')
            if not isinstance(payload,str):raise ValueError('cold_result_payload_not_text')
            # Adapter reuses exact range/search machinery over decoded result
            # text; it does not invent a new event or change archived content.
            # source_text excludes tool-role strings; a textual view is
            # explicit and engine-local rather than encoding the payload again.
            result=read(args,[{'id':args['message_id'],'role':'assistant','content':payload}])
            result.update(role=row.get('role'),tool_call_id=selected[0].get('tool_use_id'),
                representation='tool_result_text',payload_sha256=hashlib.sha256(payload.encode('utf-8')).hexdigest())
        encoded=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
        return {**result,'source_sha256':hashlib.sha256(encoded).hexdigest(),'archive_sha256':self.sha256}

    def reopen(self):
        """A restart checks the stored seal rather than trusting a reused handle."""
        return type(self)(self.path,self.sha256)

    @staticmethod
    def schemas():
        from memory.wsc_handoff_catalog import schema as catalog_schema
        from memory.wsc_handoff_recall import schema as source_schema
        catalog=catalog_schema();source=source_schema()
        catalog.update(name='SourceCatalog',description='Returns source identities, roles, sizes and invocation identities from a sealed archive. Literal query and role filters are supported.')
        source.update(name='SourceRead',description='Returns exact character ranges or literal-match passages from one source ID in a sealed archive, with offsets and source hashes.')
        source['description']+=' Single-result sources expose decoded result text; call_id selects a result in mixed sources.'
        source['input_schema']['properties']['call_id']={'type':'string','minLength':1}
        return [catalog,source]

    def call(self,name,arguments):
        if name=='SourceCatalog':return self.catalog(arguments)
        if name=='SourceRead':return self.source(arguments)
        raise ValueError('cold_source_tool_unavailable')
