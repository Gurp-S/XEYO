"""Read every receipt identity without collapsing duplicate blocks."""


def result_ids(message):
    content = message.content
    if isinstance(content, list):
        blocks = [block for block in content if isinstance(block, dict) and block.get('type') == 'tool_result']
        if blocks:
            identities = [str(block.get('tool_use_id') or (message.tool_call_id if len(blocks) == 1 else '') or '') for block in blocks]
            # An envelope ID denotes one receipt; it cannot override conflicting
            # block identities or supply the missing identity of another block.
            if message.tool_call_id and (len(blocks) != 1 or identities[0] != str(message.tool_call_id)):
                identities.append('')
            return identities
    if message.role == 'tool' or message.tool_call_id:
        return [str(message.tool_call_id or '')]
    return []
