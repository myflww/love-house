#!/usr/bin/env python3
"""Create one bound Agent activity source through a running local Controller.

Prints only metadata/private config path, never a model key or connection token.
It does not write capture.sqlite3 directly and cannot start a second graph writer.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError,URLError


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--library',default='default',help='Existing Agent memory identity')
    parser.add_argument('--name',required=True,help='Display name for this source')
    parser.add_argument('--adapter',choices=['astrbot','sdk'],required=True)
    parser.add_argument('--runtime-agent-id',required=True,help='Stable Agent identity configured in its host, not a nickname')
    parser.add_argument('--platform',action='append',dest='platforms',default=[])
    args=parser.parse_args(argv)
    data=args.data_dir.expanduser().resolve()
    try:
        ready=json.loads((data/'.runtime/app.json').read_text('utf-8'))
        pid=ready.get('pid')
        instance=ready.get('controller_instance_id')
        if type(pid) is not int or pid<=1 or not isinstance(instance,str) or len(instance)!=32:
            raise ValueError('stale controller metadata')
        if os.name=='posix':os.kill(pid,0)
        port=ready.get('controller_port')
        if type(port) is not int or not 1<=port<=65535:raise ValueError('invalid port')
        client=build_opener(ProxyHandler({}));base=f'http://127.0.0.1:{port}'
        with client.open(base+'/api/health',timeout=5) as response:health=json.load(response)
        if health.get('protocol_version')!='0.4.0' or health.get('mode')!='storage':raise ValueError('not a memory controller')
        if health.get('controller_instance_id')!=instance:raise ValueError('controller identity changed')
        body={'name':args.name,'adapter':args.adapter,'runtime_agent_id':args.runtime_agent_id,'platforms':args.platforms or ['*']}
        request=Request(base+'/api/agent/sources',data=json.dumps(body,ensure_ascii=False).encode(),
                        headers={'Content-Type':'application/json','X-NKB-Library':args.library})
        with client.open(request,timeout=15) as response:result=json.load(response)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except HTTPError as error:
        try:message=json.load(error).get('error','创建来源失败')
        except Exception:message='创建来源失败'
        parser.exit(1,'爱之屋：'+str(message)[:200]+'\n')
    except (OSError,ValueError,KeyError,URLError):
        parser.exit(1,'未发现可用的本机爱之屋服务；请先在这台服务器启动记忆服务。\n')


if __name__=='__main__':main()
