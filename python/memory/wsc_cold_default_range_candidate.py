"""Optional start-of-source range for the isolated sealed recall interface.

Omitting both offset and query selects offset zero. Explicit selectors, source
identity, payload selection, limits and seals retain the native contracts.
"""
from copy import deepcopy

from memory.wsc_cold_locator_candidate import AddressedSources


class DefaultRangeSources(AddressedSources):
    def source(self, arguments):
        args = deepcopy(arguments)
        if isinstance(args, dict) and 'offset' not in args and 'query' not in args:
            args['offset'] = 0
        return super().source(args)

    @staticmethod
    def schemas():
        schemas = AddressedSources.schemas()
        schema = schemas[1]['input_schema']
        # Keep the exactly-one source locator constraint. Range selectors are
        # mutually exclusive, but neither is required for a prefix read.
        schema['allOf'][1] = {'not': {'required': ['offset', 'query']}}
        schema['properties']['offset'].update(default=0,
            description='Character offset. With neither offset nor query, the range starts at zero.')
        return schemas
