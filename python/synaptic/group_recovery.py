"""Bounded complete-member copies in the existing immutable cold view."""
import hashlib
import json
from dataclasses import dataclass, field
from synaptic.handles import HandleRenderer, _READ_RE
from synaptic.read_plan import MAX_READ_CHARS, line_prefix, first_page_end
from synaptic.prune import group_cards, cards_handle
from synaptic.textutil import node_token_len

PREFIX='head://packet-'

def packet_text(cold, members):
    return '\n'.join(f'#node {i}\n'+cold.texts[i].replace('\r\n','\n').replace('\r','\n') for i in members)


def packet_handle(members, text):
    # Membership participates in identity: node bodies may themselves contain
    # #node labels, so visible packet text alone cannot identify its partition.
    encoded=json.dumps([list(members),text],ensure_ascii=False,separators=(',',':')).encode()
    return PREFIX+hashlib.sha256(encoded).hexdigest()


def put_packet(cold, members, max_bytes=8*1024*1024):
    members=tuple(dict.fromkeys(members))
    if not members or any(i not in cold.texts for i in members):
        return None
    text=packet_text(cold,members)
    if len(text)>MAX_READ_CHARS:
        return None
    handle=packet_handle(members,text)
    if handle in cold.snapshots:
        if cold.snapshots[handle]!=text or cold.handles.get(handle)!=members:
            raise ValueError('packet identity mismatch')
        return handle
    if handle in cold.handles and cold.handles[handle]!=members:
        raise ValueError('packet binding mismatch')
    used=sum(len(body.encode()) for key,body in cold.snapshots.items() if key.startswith(PREFIX))
    if used+len(text.encode())>max_bytes:
        return None
    cold.put_snapshot(handle,text)
    cold.bind(handle,members)
    return handle


def verified_layout(cold):
    text,ranges=cold.render_text_view()
    copies=[]
    packets=set()
    for handle,body in cold.snapshots.items():
        if not handle.startswith(PREFIX):
            continue
        members=cold.handles.get(handle)
        if not members or any(i not in cold.texts for i in members):
            raise ValueError('packet source unavailable')
        if body!=packet_text(cold,members) or handle!=packet_handle(members,body):
            raise ValueError('packet identity mismatch')
        first,last=ranges[handle]
        cursor=first
        for idx in members:
            norm=cold.texts[idx].replace('\r\n','\n').replace('\r','\n')
            start=cursor+1
            end=start+norm.count('\n')
            copies.append((idx,start,end))
            cursor=end+1
        assert cursor==last+1
        packets.add(handle)
    return text,ranges,tuple(copies),frozenset(packets)

def required_origins(renderer):
    required = {}
    for handle, nodes in renderer.handle_nodes.items():
        required.setdefault(renderer.expression(handle), set()).update(nodes)
    return required


def complete_members(group_members, expression, required):
    ordered = tuple(dict.fromkeys(group_members))
    return ordered + tuple(i for i in sorted(required.get(expression, ())) if i not in ordered)

@dataclass(frozen=True)
class RecoveryRenderer(HandleRenderer):
    copy_ranges: tuple=()
    packet_handles: frozenset=field(default_factory=frozenset)
    aliases: dict=field(default_factory=dict)
    original: object=None

    def span(self, handle):
        if handle in self.aliases:
            return self.node_ranges.get(self.aliases[handle])
        if handle in self.packet_handles:
            return self.node_ranges.get(handle)
        return super().span(handle)

    def recoverable_nodes(self,text):
        out=set(super().recoverable_nodes(text))
        for full,_first_read in self._declared_extents(text):
            start,end=full[1],full[1]+full[2]-1
            out.update(idx for idx,lo,hi in self.copy_ranges if start<=lo and hi<=end)
        return frozenset(out)

    def _reverse_index(self):
        if self._reverse_cache is not None:
            return self._reverse_cache
        out=dict(self.original._reverse_index()) if self.original else {}
        out.update(super()._reverse_index())
        object.__setattr__(self,'_reverse_cache',out)
        return out


    def extract_nodes(self, text):
        out=set(super().extract_nodes(text))
        known=self._reverse_index()
        for match in _READ_RE.finditer(text):
            key=(match.group('path'),int(match.group('offset')),int(match.group('limit')))
            if key not in known:
                continue
            start,end=key[1],key[1]+key[2]-1
            out.update(idx for idx,lo,hi in self.copy_ranges if start<=lo and hi<=end)
        return frozenset(out)

def prepare_groups(cold,cards,ref):
    raw,ranges=cold.render_text_view()
    lines=raw.split('\n')
    original=HandleRenderer(style='read',path=ref,node_ranges=ranges,
                            handle_nodes=dict(cold.handles),line_lengths=line_prefix(raw))
    required=required_origins(original)
    mapping={}
    created=[]
    visible_groups = group_cards(tuple(card for card in cards if not card.error_sig)) + [[card] for card in cards if card.error_sig]
    group_handles=[cards_handle(group) for group in visible_groups]
    group_handles += [h for h,nodes in cold.handles.items() if len(nodes)>1 and h.startswith(('reqs://','node://'))]
    for handle in dict.fromkeys(group_handles):
        expression=original.expression(handle)
        members=complete_members(cold.handles.get(handle,()),expression,required)
        extent=original.span(handle)
        if not extent or not members or not all(i in cold.texts for i in members):
            continue
        first,last=extent
        stop=first_page_end(first,last,original.line_lengths)
        old='\n'.join(lines[first-1:stop])
        text=packet_text(cold,members)
        if node_token_len(text)>=node_token_len(old):
            continue
        key=packet_handle(members,text)
        exists=key in cold.snapshots
        if not exists and len(created)>=24:
            continue
        key=put_packet(cold,members)
        if key is None:
            continue
        mapping[handle]=key
        mapping.update({h:key for h in original.handle_nodes if original.expression(h)==expression})
        if not exists:
            created.append(dict(handle=handle,packet=key,nodes=members,old_origin=expression,
                                old_first_tokens=node_token_len(old),packet_tokens=node_token_len(text)))
    return mapping



def recovery_renderer(cold,path,ranges,lengths,aliases=None):
    original=HandleRenderer(style='read',path=path,node_ranges=ranges,
                            handle_nodes=dict(cold.handles),line_lengths=lengths)
    if not aliases and not any(h.startswith(PREFIX) for h in cold.snapshots):
        return original
    _text,_ranges,copies,packets=verified_layout(cold)
    assert _ranges==ranges
    return RecoveryRenderer(style='read',path=path,node_ranges=ranges,handle_nodes=dict(cold.handles),
                            line_lengths=lengths,copy_ranges=copies,packet_handles=packets,
                            aliases=aliases or {},original=original)
