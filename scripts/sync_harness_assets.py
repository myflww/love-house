"""Include the same prebuilt host adapter in Python wheels as in source/App distributions."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'extensions/deepseek-harness'
target=ROOT/'nkb/service/harness'
(target/'dist').mkdir(parents=True,exist_ok=True)
for name in ('index.js','configure.js','proxy.js'):
 p=source/'dist'/name
 if not p.is_file():raise SystemExit('请先构建宿主适配器：'+str(p))
 shutil.copy2(p,target/'dist'/name)
for name in ('configure.py','host-contract.json','README.md','LICENSE','NOTICE'):
 p=source/name
 if p.is_file():shutil.copy2(p,target/name)
shutil.copy2(source/'dist/THIRD_PARTY_LICENSES.txt',target/'dist/THIRD_PARTY_LICENSES.txt')
print('Synchronized portable Harness adapter resources for Python distribution.')
