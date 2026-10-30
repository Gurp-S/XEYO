"""Explicit owner CLI; no implicit native Codex hook or model invocation."""
import argparse
import json
from pathlib import Path
import sys
import sqlite3
from . import ResultStore,RuntimeResults,ResultPolicy,ToolText
from .strategies import KINDS


def main(argv=None):
    p=argparse.ArgumentParser(prog='wsc-results')
    p.add_argument('--root',required=True);p.add_argument('--session',required=True)
    subs=p.add_subparsers(dest='op',required=True)
    capture=subs.add_parser('present');capture.add_argument('--input',required=True)
    capture.add_argument('--call-id',required=True);capture.add_argument('--kind',choices=sorted(KINDS),default='unknown')
    capture.add_argument('--status',choices=['unknown','success','error','cancelled'],default='unknown')
    capture.add_argument('--exit-code',type=int);capture.add_argument('--timed-out',action='store_true',default=None)
    capture.add_argument('--metadata',help='JSON object: source, facts, observed_at only')
    capture.add_argument('--threshold',type=int,default=32768);capture.add_argument('--summary-bytes',type=int,default=2048)
    for name in ('read','read-lines','find','json-pointer'):
        sub=subs.add_parser(name);sub.add_argument('--id',required=True)
        if name in ('read','read-lines'):
            sub.add_argument('--limit',type=int,default=8192)
            sub.add_argument('--offset' if name=='read' else '--start-line',type=int,default=0 if name=='read' else 1)
        elif name=='find':
            sub.add_argument('--literal',required=True);sub.add_argument('--cursor',type=int,default=0);sub.add_argument('--limit',type=int,default=8)
        else:sub.add_argument('--pointer',required=True)
    args=p.parse_args(argv)
    try:
        api=RuntimeResults(ResultStore(args.root,session=args.session),policy=ResultPolicy(enabled=True,
            externalize_bytes=getattr(args,'threshold',32768),summary_bytes=getattr(args,'summary_bytes',2048)))
        if args.op=='present':
            extra=json.loads(Path(args.metadata).read_text(encoding='utf-8')) if args.metadata else {}
            if not isinstance(extra,dict) or set(extra)-{'source','facts','observed_at'}:raise ValueError('tool_result_metadata_invalid')
            # newline='' retains CRLF and standalone CR exactly.
            with Path(args.input).open(encoding='utf-8',newline='') as f:text=f.read()
            result=api.present(args.call_id,ToolText(text,kind=args.kind,status=args.status,
                 exit_code=args.exit_code,timed_out=args.timed_out,**extra))
        elif args.op=='read':result=api.read(args.id,offset=args.offset,limit=args.limit)
        elif args.op=='read-lines':result=api.read_lines(args.id,start_line=args.start_line,limit=args.limit)
        elif args.op=='find':result=api.find(args.id,args.literal,cursor=args.cursor,limit=args.limit)
        else:result=api.json_pointer(args.id,args.pointer)
        print(json.dumps(result,ensure_ascii=False,separators=(',',':')));return 0
    except (OSError,ValueError,RecursionError,sqlite3.Error) as error:
        print(json.dumps(dict(status='error',code=str(error)),ensure_ascii=False));return 2


if __name__=='__main__':sys.exit(main())
