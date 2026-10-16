"""Pure historical answer parsing, without API credentials or budget side effects."""
import json


def parse(content):
    try:
        return json.loads(content), True
    except ValueError:
        pass
    for index, char in enumerate(content):
        if char == '{':
            try:
                value, _ = json.JSONDecoder().raw_decode(content[index:])
                if isinstance(value, dict):
                    return value, False
            except ValueError:
                pass
    return {}, False
