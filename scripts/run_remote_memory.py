#!/usr/bin/env python3
"""Explicit private HTTPS gateway launcher; never installs a service or opens a public listener by default."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import ssl
import sys

ROOT=Path(__file__).resolve().parents[1]


def named_secret(name, environment):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,199}',name):
        raise ValueError('须明确指定存放私密口令的环境变量名称')
    value=environment.get(name)
    if not isinstance(value,str) or len(value)<32 or any(c.isspace() for c in value):
        raise ValueError('指定环境变量未提供至少32字符的可用私密口令')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--public-origin',required=True,help='Canonical HTTPS origin owned by this user, without a path')
    parser.add_argument('--admin-token-env',required=True,help='Explicit environment variable NAME; never pass the secret in argv')
    parser.add_argument('--bind',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=9443)
    parser.add_argument('--tls-cert',type=Path)
    parser.add_argument('--tls-key',type=Path)
    parser.add_argument('--proxy-secret-env',help='Explicit environment variable NAME used only with a trusted loopback HTTPS reverse proxy')
    args=parser.parse_args(argv);sys.path.insert(0,str(ROOT))
    from nkb.service.remote_gateway import RemoteGateway,create_server,public_origin
    try:
        origin=public_origin(args.public_origin);admin=named_secret(args.admin_token_env,os.environ)
        proxy=named_secret(args.proxy_secret_env,os.environ) if args.proxy_secret_env else None
        if bool(args.tls_cert)!=bool(args.tls_key):raise ValueError('TLS证书与私钥须一起指定')
        if not args.tls_cert and not proxy:raise ValueError('须提供TLS证书/私钥或显式可信loopback反代密钥')
        if not 1<=args.port<=65535:raise ValueError('监听端口须为1至65535')
        context=None
        if args.tls_cert:
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(args.tls_cert,args.tls_key)
    except (ValueError,OSError,ssl.SSLError) as error:
        parser.error(str(error) if isinstance(error,ValueError) else 'TLS文件无法加载，请检查自己提供的证书与私钥')
    # The same process and lock own the memory writer, local controller and
    # gateway. A desktop already owning this data directory fails closed.
    from desktop.windows_app import ControllerRuntime
    runtime=ControllerRuntime(args.data_dir).start();server=None
    try:
        gateway=RemoteGateway(runtime.host,origin=origin,admin_token=admin,proxy_secret=proxy)
        server=create_server(gateway,bind=args.bind,port=args.port,tls_context=context)
        print('爱之屋私有远程入口已启动：'+origin+'/mobile',flush=True)
        print('同份记忆由此进程独占；静态Bearer仅适用于允许自定义请求头的私有Agent客户端。',flush=True)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:
        if server:server.server_close()
        runtime.stop()
    return 0


if __name__=='__main__':raise SystemExit(main())
