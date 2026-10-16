"""Source IDs and sealed archive record positions are explicit namespaces."""
from copy import deepcopy

from memory.wsc_cold_discovery_candidate import DiscoverableSources


class AddressedSources(DiscoverableSources):
    def resolve_locator(self,arguments):
        if not isinstance(arguments,dict):raise ValueError('handoff_source_invalid_arguments')
        args=deepcopy(arguments)
        if 'source_index' in args:
            if 'message_id' in args:raise ValueError('cold_source_locator_ambiguous')
            index=args.pop('source_index')
            if type(index) is not int or not 0<=index<len(self._sources):raise ValueError('cold_source_index_invalid')
            row=self._sources[index];uid=row.get('message_id') or row.get('id')
            if not uid:raise ValueError('cold_source_identity_missing')
            args['message_id']=str(uid)
        else:index=None
        return args,index

    def source(self,arguments):
        args,index=self.resolve_locator(arguments)
        result=super().source(args)
        if index is None:index=next(i for i,row in enumerate(self._sources) if str(row.get('message_id') or row.get('id'))==args['message_id'])
        return {**result,'source_index':index}

    @staticmethod
    def schemas():
        schemas=DiscoverableSources.schemas();schema=schemas[1]['input_schema']
        schema['properties']['source_index']={'type':'integer','minimum':0,'description':'Zero-based record position in the sealed archive. Request-message positions use a different namespace.'}
        schema['required']=['limit']
        range_choice=schema.pop('oneOf')
        schema['allOf']=[{'oneOf':[{'required':['message_id']},{'required':['source_index']}]},{'oneOf':range_choice}]
        schemas[1]['description']+=' Sources are addressed by message_id or sealed-archive source_index.'
        return schemas
