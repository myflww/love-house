#!/bin/zsh
cd -- "${0:A:h}" || exit 1
for nkb_python in python3.13 python3.12 python3.11 "$HOME/.local/bin/python3.12" python3; do
  if command -v "$nkb_python" >/dev/null 2>&1 && "$nkb_python" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
    exec "$nkb_python" scripts/launch.py "$@"
  fi
done
print '需要 Python 3.11 或更新版本。没有修改你的系统或安装软件。'
read -k 1 '?按任意键关闭…'
