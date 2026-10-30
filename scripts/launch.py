#!/usr/bin/env python3
"""Portable memory service entry. First launch is empty; examples require an explicit choice."""
from __future__ import annotations
import argparse,sys,json,os,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
 if sys.version_info<(3,11):sys.exit('需要Python3.11或更新版本')
 from nkb.service.httpd import LoopbackHTTPServer as ThreadingHTTPServer
 from nkb.service.host import MemoryHost,make_controller
 p=argparse.ArgumentParser(description='爱之屋记忆存储服务')
 p.add_argument('--data-dir',type=Path,default=ROOT/'data')
 p.add_argument('--brain',type=Path,help='旧库迁移入口；请使用独立data-dir以避免多进程写入')
 p.add_argument('--empty',action='store_true',help='兼容参数：默认就是空白个人库')
 p.add_argument('--demo',action='store_true',help='显式添加独立示例库')
 p.add_argument('--port',type=int,default=8768);p.add_argument('--no-browser',action='store_true')
 a=p.parse_args()
 if a.brain:
  sys.exit('独立旧文件请先用 nkb serve -b 文件；多库服务请指定 --data-dir，不自动合并或搬移记忆')
 a.data_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
 writer=(a.data_dir/'.desktop-writer.lock').open('a+')
 try:
  import fcntl
  fcntl.flock(writer,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except ImportError:pass
 except BlockingIOError:sys.exit('该数据目录已有星图服务，请使用正在运行的服务')
 host=MemoryHost(a.data_dir,with_demo=a.demo)
 if a.demo and not host.manager.demo_suppressed and not any(x['is_demo'] for x in host.manager.list_libraries()):
  from nkb.core.atlas import atlas_brain
  demo=a.data_dir/'framework-example.brain.json';atlas_brain(demo).save();host.manager.register_demo(demo)
 server=None
 for port in range(a.port,min(a.port+20,65536)):
  try:server=ThreadingHTTPServer(('127.0.0.1',port),make_controller(host));break
  except OSError:continue
 if server is None:host.stop();sys.exit('无法绑定本地端口')
 host.controller_port=server.server_port
 runtime=a.data_dir/'.runtime';runtime.mkdir(exist_ok=True,mode=0o700)
 ready=runtime/(uuid.uuid4().hex+'.json')
 ready.write_text(json.dumps({'pid':os.getpid(),'controller_port':server.server_port,'port':server.server_port,'personal_port':server.server_port,'service_version':'0.4.0','name':'爱之屋记忆服务'}))
 ready.chmod(0o600)
 print(f'爱之屋: http://127.0.0.1:{server.server_port}\n数据目录: {host.root}\n默认空白库；Ctrl+C停止。',flush=True)
 if not a.no_browser:
  import webbrowser;webbrowser.open(f'http://127.0.0.1:{server.server_port}')
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close();host.stop();ready.unlink(missing_ok=True);writer.close()
if __name__=='__main__':main()
