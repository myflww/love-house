#!/usr/bin/env python3
"""Real isolated RemoteGateway for native mobile-engine QA; no public deployment."""
from __future__ import annotations
import faulthandler
faulthandler.enable()
faulthandler.dump_traceback_later(20,repeat=True)
print("fixture: interpreter entered; loading standard library",flush=True)
import argparse,json,os,signal,ssl,subprocess,threading,time
from pathlib import Path

ADMIN='IOS-SIMULATOR-SYNTHETIC-ADMIN-ONLY-000000000000'
USER='Synthetic iOS host user: remember the blue compass.'
ASSISTANT='Synthetic iOS host assistant: the blue compass is recorded.'

def mint(directory):
 directory.mkdir(parents=True,exist_ok=True)
 ca=directory/'root-ca.pem';key=directory/'root-private.pem';cert=directory/'server.pem';server_key=directory/'server-private.pem'
 ca_config=directory/'ca.cnf';ca_config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ca\nprompt=no\n[dn]\nCN=LoveHouse iOS Synthetic QA Root\n[ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n',encoding='utf-8')
 ext=directory/'server.cnf';ext.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n',encoding='utf-8')
 commands=[['openssl','req','-x509','-newkey','rsa:2048','-nodes','-sha256','-days','1','-config',str(ca_config),'-keyout',str(key),'-out',str(ca)],['openssl','req','-newkey','rsa:2048','-nodes','-sha256','-subj','/CN=127.0.0.1','-keyout',str(server_key),'-out',str(directory/'server.csr')],['openssl','x509','-req','-in',str(directory/'server.csr'),'-CA',str(ca),'-CAkey',str(key),'-CAcreateserial','-sha256','-days','1','-extfile',str(ext),'-out',str(cert)]]
 for command in commands:subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
 for private in (key,server_key):private.chmod(0o600)
 return ca,cert,server_key

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args();root=args.root.resolve();root.mkdir(parents=True,exist_ok=True)
 print('fixture: importing actual backend',flush=True)
 from nkb.service.httpd import LoopbackHTTPServer
 from nkb.service.credentials import KeyStore
 from nkb.service.host import MemoryHost,make_controller
 from nkb.service.remote_gateway import RemoteGateway,create_server
 print('fixture: minting isolated CA and TLS certificate',flush=True)
 ca,cert,key=mint(root/'tls')
 print('fixture: creating isolated MemoryHost',flush=True)
 host=MemoryHost(root/'memory',key_store=KeyStore(allow_keychain=False))
 print('fixture: creating loopback controller',flush=True)
 controller=LoopbackHTTPServer(('127.0.0.1',0),make_controller(host));host.controller_port=controller.server_port
 ct=threading.Thread(target=controller.serve_forever,kwargs={'poll_interval':.05});ct.start()
 print('fixture: creating actual HTTPS gateway',flush=True)
 gateway=RemoteGateway(host,origin='https://127.0.0.1',admin_token=ADMIN)
 context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_cert_chain(cert,key)
 server=create_server(gateway,tls_context=context);origin='https://127.0.0.1:'+str(server.server_port);gateway.origin=origin;gateway.authority='127.0.0.1:'+str(server.server_port)
 original_handler=server.RequestHandlerClass
 class TracedHandler(original_handler):
  def _trace(self):
   route=self.path.split('?',1)[0]
   kind=route if route in ('/api/remote/health','/api/remote/admin/session','/api/remote/admin/login','/api/remote/admin/libraries','/api/remote/admin/connections') else 'mcp' if route.startswith('/mcp/') else 'host-hook' if route.startswith('/api/remote/connections/') else 'asset'
   print('fixture request: '+self.command+' '+kind,flush=True)
  def do_GET(self):self._trace();return super().do_GET()
  def do_POST(self):self._trace();return super().do_POST()
 server.RequestHandlerClass=TracedHandler
 gt=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05});gt.start();stopping=threading.Event()
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stopping.set())
 (root/'ready.json').write_text(json.dumps({'origin':origin,'root_ca':str(ca),'backend_version':__import__('nkb._version',fromlist=['__version__']).__version__,'fixture':'synthetic_only_no_model_credentials'}),encoding='utf-8')
 if os.environ.get("LOVEHOUSE_QA_STACKS") != "1":faulthandler.cancel_dump_traceback_later()
 print('fixture: ready',flush=True)
 try:
  while not stopping.wait(.5):
   snapshot=host.snapshot('default');text=json.dumps(snapshot,ensure_ascii=False);connections=host.connections.list()
   report={'schema':'love-house-ios-service-state/v1','node_count':len(snapshot['nodes']),'original_user_saved':USER in text,'original_assistant_saved':ASSISTANT in text,'connections':[{'host':c['host'],'scope':c['session_scope'],'archive_status':c['archive_status'],'capture':c.get('capture')} for c in connections]}
   temporary=root/'service-state.tmp';temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,root/'service-state.json')
 finally:
  server.shutdown();server.server_close();gt.join();controller.shutdown();controller.server_close();ct.join();host.stop()

if __name__=='__main__':main()
