#!/usr/bin/env python3
"""Copy only a generated public test CA into the independent QA APK project."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from urllib.parse import urlsplit


def prepare(ready_file, qa_project, output):
    ready=json.loads(Path(ready_file).read_text('utf-8'))
    parsed=urlsplit(ready['origin'])
    if parsed.scheme!='https' or parsed.hostname!='127.0.0.1' or not parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('Only the isolated HTTPS loopback fixture is accepted')
    ca=Path(ready['root_ca']);data=ca.read_bytes()
    if len(data)>65536 or b'-----BEGIN CERTIFICATE-----' not in data or b'PRIVATE KEY' in data:
        raise ValueError('Only the generated public CA certificate may enter the QA APK')
    project=Path(qa_project).resolve()
    if not (project/'build.gradle').is_file() or not (project/'src/main/AndroidManifest.xml').is_file():
        raise ValueError('The independent instrumentation-only APK project is absent')
    target=project/'src/main/res/raw/remote_test_ca.pem';target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ca,target)
    report={'schema':'love-house-android-remote-fixture/v1','origin':ready['origin'],
            'test_ca_sha256':hashlib.sha256(data).hexdigest(),'backend_version':ready['backend_version'],
            'production_app_modified':False,'public_ca_only':True,'tls_verification_bypassed':False}
    Path(output).parent.mkdir(parents=True,exist_ok=True);Path(output).write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-ready',type=Path,required=True)
    parser.add_argument('--qa-project',type=Path,default=Path(__file__).resolve().parents[1]/'android/app/src/androidTest/remote-gateway')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();prepare(args.fixture_ready,args.qa_project,args.output)
    print('Prepared the isolated native WebView HTTPS fixture public CA.')


if __name__=='__main__':main()
