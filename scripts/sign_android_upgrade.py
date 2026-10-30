#!/usr/bin/env python3
"""Sign the reviewed 0.8 Android APK on the computer holding its ORIGINAL key.

Passwords are requested without echo and passed to apksigner only over stdin.
No key generation, key copying, package-ID change, candidate edit or upload.
"""
from __future__ import annotations
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
import warnings

from verify_android_release import badging_identity, signer_digest

APP_ID='io.github.myflww.lovehouse.preview'
VERSION_NAME='0.8.0rc1'
VERSION_CODE='2'
ORIGINAL_CERT='ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc'
MAX_APK_BYTES=100*1024*1024


class SigningError(ValueError):pass


def run(command,*,passwords=None,require_success=True):
    # Executables/jar paths and public arguments only. No .bat/shell wrapper,
    # password command argument, environment variable or external-command text
    # is exposed in an error or the signing report.
    try:
        result=subprocess.run([str(part) for part in command],input=passwords,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,check=False)
    except (OSError,subprocess.SubprocessError):
        raise SigningError('Android tool could not complete; no verified signed output was delivered') from None
    if require_success and result.returncode:
        raise SigningError('Android tool rejected the operation (exit '+str(result.returncode)+'); no verified signed output was delivered')
    return result.returncode,result.stdout.decode('utf-8',errors='replace')


def identity(aapt,apk):
    _,text=run([aapt,'dump','badging',apk]);value=badging_identity(text)
    if (value['package'],value['version_code'],value['version_name'])!=(APP_ID,VERSION_CODE,VERSION_NAME):
        raise SigningError('APK package/version differs from the intended existing-app upgrade')
    if value['min_sdk']!=['26'] or value['target_sdk']!=['36']:
        raise SigningError('APK SDK metadata differs from the verified 0.8 build')
    return value


def sign(args,*,prompt=getpass.getpass):
    source=args.unsigned_apk.expanduser().resolve();output=args.output_apk.expanduser().absolute()
    keystore=args.keystore.expanduser().resolve();tools=args.build_tools.expanduser().resolve()
    java=Path(args.java).expanduser().resolve() if args.java else Path(shutil.which('java') or '')
    suffix='.exe' if os.name=='nt' else ''
    aapt=tools/('aapt'+suffix);zipalign=tools/('zipalign'+suffix);jar=tools/'lib/apksigner.jar'
    for path in (source,keystore,java,aapt,zipalign,jar):
        if not path.is_file():raise SigningError('Required local APK, original keystore, Java or Android Build-Tools file is unavailable')
    report=output.with_name(output.name+'.verification.json')
    if output.exists() or output.is_symlink() or report.exists() or report.is_symlink():
        raise SigningError('Output APK/report already exists; choose a fresh output name')
    if not output.parent.is_dir():raise SigningError('Create the intended output directory first')
    if source.stat().st_size>MAX_APK_BYTES:raise SigningError('APK exceeds the reviewed artifact size budget')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if digest!=args.expected_sha256.lower():raise SigningError('Unsigned APK SHA-256 differs from the verified CI artifact')
    with zipfile.ZipFile(source) as archive:
        if archive.testzip() is not None or 'AndroidManifest.xml' not in archive.namelist():
            raise SigningError('Input is not an intact Android package')
    apk_identity=identity(aapt,source)
    run([zipalign,'-c','-P','16','4',source])
    code,_=run([java,'-Dfile.encoding=UTF-8','-jar',jar,'verify',source],require_success=False)
    if code==0:raise SigningError('Input is already signed; use the validated unsigned release artifact')
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        store_password=prompt('Original keystore password (hidden): ')
        key_password=prompt('Original key password (hidden; Enter = same as keystore): ') or store_password
    if not store_password or any('\n' in value or '\r' in value for value in (store_password,key_password)):
        raise SigningError('Password input is empty or cannot be passed as an stdin line')
    passwords=(store_password+'\n'+key_password+'\n').encode('utf-8')
    # All work stays beside the chosen output and is removed on a wrong key,
    # failed signature verification or mismatched public certificate.
    with tempfile.TemporaryDirectory(prefix='.love-house-sign-',dir=output.parent) as temporary:
        signed=Path(temporary)/'verified.apk'
        command=[java,'-Dfile.encoding=UTF-8','-jar',jar,'sign','--ks',keystore,'--ks-key-alias',args.alias,
                 '--ks-pass','stdin','--key-pass','stdin','--pass-encoding','utf-8','--v4-signing-enabled','false','--out',signed,source]
        try:run(command,passwords=passwords)
        finally:passwords=None;store_password='';key_password=''
        _,certificate=run([java,'-Dfile.encoding=UTF-8','-jar',jar,'verify','--verbose','--print-certs',signed])
        if signer_digest(certificate)!=ORIGINAL_CERT:
            raise SigningError('Signer differs from the ORIGINAL public certificate; no upgrade APK was delivered')
        if identity(aapt,signed)!=apk_identity:raise SigningError('Signed APK identity changed unexpectedly')
        run([zipalign,'-c','-P','16','4',signed])
        raw=signed.read_bytes();signed_hash=hashlib.sha256(raw).hexdigest()
        result={'schema':'love-house-local-android-signing/v1','application_id':APP_ID,'version_name':VERSION_NAME,
                'version_code':int(VERSION_CODE),'certificate_sha256':ORIGINAL_CERT,'unsigned_sha256':digest,
                'signed_sha256':signed_hash,'signed_bytes':len(raw),'signature_and_metadata':'passed',
                'same_original_signer':True,'device_upgrade_verified':False,'published':False}
        created=[]
        try:
            with output.open('xb') as stream:
                created.append(output);stream.write(raw);stream.flush();os.fsync(stream.fileno())
            with report.open('x',encoding='utf-8',newline='\n') as stream:
                created.append(report);json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        except BaseException:
            for path in created:path.unlink(missing_ok=True)
            raise
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unsigned-apk',required=True,type=Path)
    parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--build-tools',required=True,type=Path,help='Existing Android SDK build-tools/36.0.0 directory')
    parser.add_argument('--java',type=Path,help='Existing Java 17+ executable; otherwise resolved from PATH')
    parser.add_argument('--keystore',required=True,type=Path,help='Original PRIVATE keystore on this computer; never copied')
    parser.add_argument('--alias',required=True,help='Existing signing-key alias; no new alias is created')
    parser.add_argument('--output-apk',required=True,type=Path)
    args=parser.parse_args()
    import re
    if not re.fullmatch('[0-9a-fA-F]{64}',args.expected_sha256):parser.error('--expected-sha256 must be the 64-digit verified CI digest')
    try:result=sign(args)
    except (SigningError,ValueError,OSError,zipfile.BadZipFile,EOFError,KeyboardInterrupt,getpass.GetPassWarning):
        parser.exit(1,'Signing did not complete with the original verified signer. Check local paths, credentials and the original certificate; no release was published.\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
