"""Read one real Agent host turn/tool event from stdin and submit/queue it locally."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE if (HERE/'nkb').is_dir() else HERE.parent))
from nkb.service.agent_client import AgentClient,AgentConnectionError,MAX_EVENT,_constant,_unique

def main():
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='strict')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--connection-config',required=True,type=Path)
    args=parser.parse_args()
    try:
        raw=sys.stdin.buffer.read(MAX_EVENT+1)
        if len(raw)>MAX_EVENT:raise AgentConnectionError('单事件超过32MiB','input_too_large')
        event=json.loads(raw,parse_constant=_constant,object_pairs_hook=_unique)
        result=AgentClient(args.connection_config).submit_hook(event)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0
    except (AgentConnectionError,ValueError,UnicodeError,RecursionError) as exc:
        code=getattr(exc,'code','invalid_input')
        print(json.dumps({'saved':False,'queued':False,'status':code,'error':'真实宿主事件未保存；请检查本机连接状态或事件字段。'},ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
