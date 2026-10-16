"""Identity-addressed reads; legacy names retain the existing scan fallback."""
import hashlib


def identity_lock(domain, note_id):
    from engine.write_transaction import path_lock
    from memory.memdir import memdir_root
    digest = hashlib.sha256(note_id.encode("utf-8")).hexdigest()
    return path_lock(str(memdir_root(domain) / "topics" / (".identity-" + digest)))


def find_in_domain(domain, note_id):
    from memory.memdir import memdir_root, split_frontmatter, load_notes
    from memory.governance import ALLOWED_TYPES, MemorySchemaError, parse_and_validate

    digest = hashlib.sha256(note_id.encode("utf-8")).hexdigest()
    topics = memdir_root(domain) / "topics"
    found = None
    # Same ordering and canonical preference as load_notes, including type changes.
    for kind in sorted(ALLOWED_TYPES | {"untyped"}):
        try:
            fm, body = split_frontmatter((topics / f"{kind}-{digest}.md").read_text(encoding="utf-8"))
            note = parse_and_validate(fm, body)
        except (OSError, UnicodeError, MemorySchemaError):
            continue
        if note.id == note_id and note.type == kind:
            if found is None or note.updated_at > found.updated_at:
                found = note
    if found is not None:
        return found
    return next((n for n in load_notes(domain) if n.id == note_id), None)
