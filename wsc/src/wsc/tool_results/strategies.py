"""Bounded display projections. No source mutation or semantic relevance ranking."""
import json
import re
from itertools import islice
from ..contracts import encode
from ..denoise.collapse_stack import collapse
from ..denoise.diff_digest import digest as diff_digest

RULES=('strip_noise_lines','collapse_stack','diff_digest','dedupe_identical','dedupe_reads','outline_json','truncate_head_tail')
KINDS={'unknown','terminal_log','stack','diff','json','table','source','document','test','build'}
SGR=re.compile(r'\x1b\[[0-9;]*m')


MAX_JSON_DEPTH=100


def nested_depth(value):
    """Deepest container nesting, measured without recursion."""
    deepest=0
    stack=[(value,1)]
    while stack:
        node,level=stack.pop()
        if not isinstance(node,(dict,list)):continue
        deepest=max(deepest,level)
        if deepest>MAX_JSON_DEPTH:return deepest
        children=node.values() if isinstance(node,dict) else node
        stack.extend((child,level+1) for child in children)
    return deepest


def strict_json(text):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('duplicate_json_key')
            result[key]=value
        return result
    def constant(value):raise ValueError('nonfinite_json_value')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)


def outline(value,depth=0):
    if isinstance(value,dict):
        keys=list(islice(value,24))
        return dict(type='object',fields=len(value),entries=[dict(key=k,value=outline(value[k],depth+1)) for k in keys] if depth<3 else [],omitted=len(value)-(len(keys) if depth<3 else 0))
    if isinstance(value,list):
        return dict(type='array',length=len(value),sample=[outline(x,depth+1) for x in value[:2]] if depth<3 else [],sample_complete=len(value)<=2 and depth<3)
    if isinstance(value,str):return dict(type='string',length=len(value),preview=value[:64],complete=len(value)<=64)
    return dict(type=type(value).__name__,value=value)


def clip(text,budget):
    if len(text)<=budget and len(text.encode('utf-8'))<=budget:return text,False
    # Byte ceilings, not character approximations; never split a UTF-8 codepoint.
    head=text[:budget].encode('utf-8')[:budget*2//3].decode('utf-8',errors='ignore')
    tail=text[-budget:].encode('utf-8')[-budget//3:].decode('utf-8',errors='ignore')
    return head+'\n[omitted middle]\n'+tail,True


def project(text,kind,rules,budget,max_json_bytes,prior=None,source=None,*,original_bytes=None,max_transform_bytes=8*1024*1024):
    applied=[];notes=[];current=text
    if prior:
        old=prior['meta'];same_read=(kind in {'source','document'} and source and
            all(source.get(k) is not None for k in ('path','version','range')) and source==old.get('source'))
        rule='dedupe_reads' if same_read and 'dedupe_reads' in rules else 'dedupe_identical'
        if rule in rules:
            return encode(dict(same_body_as=prior['id'])),[rule],notes
    size=original_bytes if original_bytes is not None else sum(len(text[i:i+16384].encode()) for i in range(0,len(text),16384))
    if size>max_transform_bytes:
        notes.append('display_scan_byte_limit')
        if 'truncate_head_tail' in rules:
            value,changed=clip(text,max(64,budget-32))
            return value,['truncate_head_tail'] if changed else [],notes
        return text,[],notes
    if kind in {'terminal_log','stack','test','build'} and 'strip_noise_lines' in rules:
        # CRLF is a line ending. Standalone CR is retained rather than guessed
        # to be a disposable progress frame. No INFO/error/pytest lines removed.
        current=SGR.sub('',current.replace('\r\n','\n'))
        if current!=text:applied.append('strip_noise_lines')
    if kind=='stack' and 'collapse_stack' in rules:
        value=collapse(current)
        if value!=current:applied.append('collapse_stack');current=value
    if kind=='diff' and 'diff_digest' in rules:
        value=diff_digest(current)
        if value!=current:applied.append('diff_digest');current=value
    if kind in {'json','table'} and 'outline_json' in rules:
        if size>max_json_bytes:notes.append('structured_parse_byte_limit')
        else:
            try:
                parsed=strict_json(text)
                # Refuse deep nesting on a stated bound rather than on the
                # interpreter's recursion limit, which varies by build and lets
                # a deeply nested payload slip through as an outline.
                if nested_depth(parsed)>MAX_JSON_DEPTH:raise ValueError('json_depth_limit')
                current=encode(outline(parsed));applied.append('outline_json')
            except (ValueError,RecursionError):notes.append('structured_format_unavailable')
    if 'truncate_head_tail' in rules:
        current,changed=clip(current,max(64,budget-32))
        if changed:applied.append('truncate_head_tail')
    return current,applied,notes
