"""Display native thoughts as the same joined text emitted to the UI."""


def display_blocks(content):
    if not any(isinstance(block, dict) and block.get('type') == 'thinking' for block in content):
        return content
    text = ''.join(block.get('text', '') for block in content
        if isinstance(block, dict) and block.get('type') in {'thinking', 'reasoning'}
        and isinstance(block.get('text'), str))
    output = []
    emitted = False
    for block in content:
        if isinstance(block, dict) and block.get('type') in {'thinking', 'reasoning'}:
            if not emitted:
                output.append({'type': 'reasoning', 'text': text})
                emitted = True
        else:
            output.append(block)
    return output
