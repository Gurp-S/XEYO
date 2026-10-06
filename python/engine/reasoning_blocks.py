"""Native replay facts remain separate from display deltas."""


def validate_reasoning_block(block):
    from engine.model_events import ModelProtocolError

    if not isinstance(block, dict):
        raise ModelProtocolError('reasoning_block must be an object')
    kind = block.get('type')
    keys = ('text', 'signature') if kind == 'thinking' else ('data',)
    if kind not in {'thinking', 'redacted_thinking'}:
        raise ModelProtocolError('unsupported reasoning block type')
    if any(not isinstance(block.get(key), str) for key in keys):
        raise ModelProtocolError('reasoning block fields must be strings')
    if not block.get('signature' if kind == 'thinking' else 'data'):
        raise ModelProtocolError('reasoning block is missing replay identity')
