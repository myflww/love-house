#!/usr/bin/env python3
"""Start Love House's existing single-writer service without a desktop window.

Run from the complete source checkout on Linux/macOS. This never installs an OS
service, opens a public listener, or reads another application's credentials.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


class ServiceBootstrapError(ValueError):
    """Sanitized configuration error; never includes an environment value."""


def make_host_initializer(args, *, environment=None):
    """Resolve only a user-named process variable, then install a session key.

    No implicit provider variable names are tried. The returned callable never
    prints a key or requests persistence to a system credential store. A process
    manager may inject the same named variable on every restart; this is not a
    claim that the secret itself has been saved by Love House.
    """
    name=getattr(args,'organizer_key_env_name',None)
    base=getattr(args,'organizer_base_url',None)
    model=getattr(args,'organizer_model',None)
    enabled=getattr(args,'enable_organizer',False)
    library=getattr(args,'organizer_library','default')
    trigger=getattr(args,'organizer_trigger_count',20)
    requested=bool(name or base or model or enabled or trigger!=20 or library!='default')
    if not requested:return None
    if (not isinstance(name,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,199}',name)
            or not isinstance(base,str) or not base or not isinstance(model,str) or not model.strip()):
        raise ServiceBootstrapError('整理启动配置需显式提供环境变量名、模型地址和模型名称。')
    if type(trigger) is not int or not 1<=trigger<=500:
        raise ServiceBootstrapError('整理触发条数须在1至500之间。')
    if not isinstance(library,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',library):
        raise ServiceBootstrapError('整理目标须为已有记忆库的固定身份。')
    if type(enabled) is not bool:
        raise ServiceBootstrapError('整理启用状态不正确。')
    # Validate the public endpoint before touching even the named secret.
    from nkb.organizer.config import endpoint
    try:endpoint(base)
    except ValueError:raise ServiceBootstrapError('整理模型地址无效；远程地址须使用HTTPS。') from None
    mapping=os.environ if environment is None else environment
    key=mapping.get(name)
    if (not isinstance(key,str) or not key or len(key)>4096
            or any(character.isspace() or ord(character)<32 for character in key)):
        raise ServiceBootstrapError('指定的整理环境变量未提供可用密钥；未读取其他变量。')
    def initialize(host):
        try:
            host.organizer_settings(library,{'provider_mode':'separate','base_url':base,'model':model.strip(),
                'api_key':key,'save_key':False,'enabled':enabled,'cadence':'batch','auto_trigger_count':trigger})
        except Exception:
            # Provider/KeyStore exceptions must not become a startup traceback
            # containing a secret or another application's configuration.
            raise ServiceBootstrapError('无法应用本库的整理启动配置；原始记录保持不变。') from None
    return initialize


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True,help='Private persistent directory for this memory service')
    parser.add_argument('--with-demo',action='store_true',help='Also register the independent visual example')
    parser.add_argument('--organizer-key-env-name',help='Explicit process environment variable NAME containing the organizer key; never pass the key itself')
    parser.add_argument('--organizer-base-url',help='Explicit model vendor HTTPS endpoint for this organizer')
    parser.add_argument('--organizer-model',help='Organizer model identifier')
    parser.add_argument('--organizer-library',default='default',help='Existing memory identity for the organizer')
    parser.add_argument('--enable-organizer',action='store_true',help='Explicitly enable model work after startup; default remains disabled')
    parser.add_argument('--organizer-trigger-count',type=int,default=20,help='Pending records before automatic organization, 1-500 (default 20)')
    args=parser.parse_args(argv)
    if sys.platform=='win32':
        parser.error('This source launcher currently supports POSIX; use the tested Windows desktop build on Windows.')
    data=args.data_dir.expanduser().resolve()
    sys.path.insert(0,str(ROOT))
    try:initializer=make_host_initializer(args)
    except ServiceBootstrapError as error:parser.error(str(error))
    from desktop.server import main as serve
    sys.argv=[str(ROOT/'desktop/server.py'),'--data-dir',str(data),'--ready-file',str(data/'.runtime/app.json')]
    if not args.with_demo:sys.argv.append('--no-demo')
    try:serve(host_initializer=initializer)
    except ServiceBootstrapError as error:parser.exit(1,'爱之屋：'+str(error)+'\n')


if __name__=='__main__':main()
