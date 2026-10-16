"""Exact bounded previews in requested cold-directory pages only.

No relevance score, semantic ranking, lifecycle inference, or hot index.
Native directory order/filters and identity validation remain authoritative.
"""
from copy import deepcopy
import json

from memory.wsc_cold_source_candidate import ColdSources


class DiscoverableSources(ColdSources):
    PREVIEW_CHARACTERS=240
    PAGE_BYTES=24000

    def catalog(self,arguments):
        page=super().catalog(arguments)
        records=[]
        for record in page['records']:
            view=deepcopy(record)
            if record.get('identity_unique') is True:
                args={'message_id':str(record['message_id']),'limit':self.PREVIEW_CHARACTERS}
                if arguments.get('query'):args['query']=arguments['query']
                else:args['offset']=0
                try:
                    preview=self.source(args)
                    # Hashes/identity are already bound by the directory and
                    # source. Only exact text coordinates are duplicated here.
                    view['text_preview']={k:preview[k] for k in ('offset','content','total_characters','text_complete',
                        'next_offset','passages','matches_total','unreturned_match_count','representation','tool_call_id') if k in preview}
                except ValueError as exc:
                    view['preview_error']=str(exc)
            candidate={**page,'records':records+[view]}
            if len(json.dumps(candidate,ensure_ascii=False,separators=(',',':')).encode())>self.PAGE_BYTES:
                # The next page resumes at the first unreturned record, not at
                # the native page end. Byte pressure never loses a record.
                page['next_source']=record['source']
                break
            records.append(view)
        page['records']=records
        if not records and page['next_source'] is not None:raise ValueError('cold_catalog_record_exceeds_budget')
        return page

    @staticmethod
    def schemas():
        schemas=ColdSources.schemas()
        schemas[0]['description']='Returns source identities, roles, sizes and exact bounded text previews from a sealed archive. Query previews contain literal-match offsets; directory order is preserved and bounded pages include next_source.'
        schemas[1]['input_schema']['properties']['message_id']['description']='Source message identity; archive filenames and SHA-256 seals are separate namespaces.'
        return schemas
