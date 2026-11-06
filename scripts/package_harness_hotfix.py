"""Package/apply adapter-only repairs without reading profiles or memory data."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def files():
    resource = ROOT / 'nkb/service/harness'
    result = {f'_internal/nkb/service/harness/{name}': resource / name for name in
              ('configure.py', 'host-capabilities.json', 'host-contract.json',
               'host-contract-fingerprints.json', 'README.md', 'LICENSE', 'NOTICE')}
    result.update({f'_internal/nkb/service/harness/dist/{name}': resource / 'dist' / name
                   for name in ('index.js', 'configure.js', 'proxy.js', 'THIRD_PARTY_LICENSES.txt')})
    result['_internal/nkb/viz/web/connection-ux.js'] = ROOT / 'nkb/viz/web/connection-ux.js'
    return result


def apply(installation):
    target = installation.resolve(strict=True)
    if not (target / 'LoveHouse.exe').is_file() or not (target / '_internal/nkb/service/harness/configure.py').is_file():
        raise ValueError('请选择现有爱之屋 Windows 程序目录')
    backup = target / ('HarnessFix-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir()
    for name, source in files().items():
        destination = target / name
        if not destination.resolve().is_relative_to(target):
            raise ValueError('修复目标越界')
        if destination.exists():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, saved)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if hashlib.sha256(destination.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
            raise ValueError('修复文件回读不一致')
    return backup


def package(output):
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files().items()}
    note = ('爱之屋 Harness 0.2.2-rc.1 连接修复\n\n'
            '适用于 Windows 爱之屋 0.10.6rc1 的适配器资源修复。\n'
            '1. 关闭爱之屋。备份程序目录中的 _internal/nkb/service/harness 和 _internal/nkb/viz/web/connection-ux.js。\n'
            '2. 将本补丁的 _internal 文件夹合并到 LoveHouse.exe 所在程序目录，覆盖同名文件。\n'
            '3. 打开爱之屋，在现有连接中重新检测并安装 Harness 插件，再重载 Harness。\n'
            '4. 在目标窗口完成一轮对话，确认用户原话和助手回复均已保存。\n\n'
            '程序版本号不变。补丁仅包含适配器和连接提示，不包含或覆盖记忆、个人配置、凭据、队列。\n'
            '旧适配器需重新安装到 Harness 的现有连接后生效；不用新建或清空记忆库。\n'
            '各文件 SHA256 见 SHA256SUMS.json。回退时恢复步骤1备份的程序资源。\n')
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in files().items():
            archive.write(path, name)
        archive.writestr('修复说明.txt', note.encode('utf-8-sig'))
        archive.writestr('SHA256SUMS.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    with zipfile.ZipFile(output) as archive:
        for name, expected in manifest.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected
    return {'package': str(output.resolve()), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'files': len(manifest)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply-to', type=Path)
    args = parser.parse_args()
    result = package(args.output)
    if args.apply_to:
        result['backup'] = str(apply(args.apply_to))
    print(json.dumps(result, ensure_ascii=False))
