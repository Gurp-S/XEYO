"""Local checkpoint CLI. Export is never reported as a native installation."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from . import Limits, Store, WSC, WSCError
from .redaction import redact
from .adapters.codex import CodexCheckpointAdapter
from .contracts import encode
from .generation import selection_from_json
from .generation_api import build_generator


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def parser():
    p = argparse.ArgumentParser(prog="wsc", description="Independent WSC checkpoint sidecar")
    p.add_argument('--resource-io',action='store_true',help='Bounded descriptor I/O and Windows installation resource leases')
    p.add_argument('--prefix-index',action='store_true',help='Prefix-scoped validation and indexed presentation membership')
    p.add_argument('--bounded-catalog',action='store_true',help='Release exported catalog copies before final binding validation')
    p.add_argument("--db", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--workspace", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-native")
    imp.add_argument("--input", required=True)
    imp.add_argument("--thread")
    imp.add_argument("--start-ordinal", type=int, default=0)
    receipt = sub.add_parser("presented")
    receipt.add_argument("--receipt", required=True)
    material = sub.add_parser("material")
    material.add_argument("--cut", type=int)
    for name in ("prepare", "generate"):
        s = sub.add_parser(name)
        s.add_argument("--cut", type=int)
        s.add_argument("--producer", required=True)
        s.add_argument("--max-view-bytes", type=int, default=32768)
        if name == "prepare":
            s.add_argument("--selection", required=True)
        else:
            s.add_argument("--command-json", required=True, help="JSON file with a program argv array")
            s.add_argument('--bounded-command',action='store_true',help='Windows suspended-root Job containment and live stream byte caps')
            s.add_argument('--max-output-bytes',type=int,default=1048576,help='Active with --bounded-command')
            s.add_argument('--max-stderr-bytes',type=int,default=65536,help='Active with --bounded-command')
    export = sub.add_parser("export")
    export.add_argument("--view", required=True)
    export.add_argument("--directory", required=True)
    export.add_argument('--archive-directory',help='Session-bound shared immutable cold-object directory')
    handoff = sub.add_parser("export-handoff")
    handoff.add_argument("--directory", required=True)
    discard = sub.add_parser("discard")
    discard.add_argument("--operation", required=True)
    source = sub.add_parser("read")
    source.add_argument("--source", required=True)
    source.add_argument("--offset", type=int, default=0)
    source.add_argument("--limit", type=int)
    sub.add_parser("status")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        # Local owner mode uses filesystem access; embedding hosts supply their
        # own live authorization callback and do not use this CLI policy.
        from .resource_io import ResourceIO
        core = WSC(Store(args.db, session_id=args.session, workspace=args.workspace),
                   access=lambda session, source, action: session == args.session,
                   resource_io=ResourceIO() if args.resource_io else None,
                   publication_policy='bounded_catalog_v1' if args.bounded_catalog else None,
                   query_policy='prefix_index_v1' if args.prefix_index else None)
        adapter = CodexCheckpointAdapter()
        if args.command == "import-native":
            value = load(args.input)
            items = value["items"] if isinstance(value, dict) else value
            ids = core.ingest(adapter.import_items(items, thread_id=args.thread or args.session,
                                                  start_ordinal=args.start_ordinal))
            result = {"source_ids": ids, "presentation": "unknown"}
        elif args.command == "presented":
            r = load(args.receipt)
            core.presented(r["request_id"], tuple(r["source_ids"]), receiver=r["receiver"])
            result = {"recorded": True, "semantic_status": "unverified"}
        elif args.command == "material":
            result = core.material(core.capture(cut=args.cut))
        elif args.command in {"prepare", "generate"}:
            snapshot = core.capture(cut=args.cut)
            limits = Limits(max_view_bytes=args.max_view_bytes)
            if args.command == "prepare":
                view = core.prepare(snapshot, selection_from_json(load(args.selection)),
                                    producer=args.producer, limits=limits)
            else:
                if args.bounded_command:
                    generator=build_generator('bounded-json-command',load(args.command_json),
                        max_output_bytes=args.max_output_bytes,max_stderr_bytes=args.max_stderr_bytes)
                else:
                    require_default=args.max_output_bytes==1048576 and args.max_stderr_bytes==65536
                    if not require_default:raise WSCError('generation_live_limits_require_bounded_command')
                    generator=build_generator('json-command',load(args.command_json))
                view = core.generate(snapshot, generator,
                                     producer=args.producer, limits=limits)
            result = {"view_id": view, "installation": "not_started"}
        elif args.command in {"export", "export-handoff"}:
            operation = (core.stage(args.view, directory=args.directory, adapter=adapter,archive_directory=args.archive_directory)
                         if args.command == "export" else
                         core.stage_detach(directory=args.directory, adapter=adapter))
            result = {"operation_id": operation, "installation": "not_started",
                      "checkpoint": str(Path(args.directory).resolve() / operation / "checkpoint.json")}
        elif args.command == "discard":
            core.discard(args.operation)
            result = {"state": "cancelled"}
        elif args.command == "read":
            result = core.read(args.source, offset=args.offset, limit=args.limit)
            # Hex keeps arbitrary byte slices exact, including split UTF-8.
            result["content_hex"] = result.pop("content").hex()
        else:
            result = core.status()
        print(encode(result))
        return 0
    except (WSCError, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        # No subprocess stderr, source content or instructions in error text.
        message = redact(str(exc), roots=(getattr(args, "workspace", None),)) \
            if isinstance(exc, WSCError) else type(exc).__name__
        print(encode({"error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
