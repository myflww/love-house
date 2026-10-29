@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo 源码启动需要 Python 3.12 和桌面依赖。
  echo 普通用户请下载免 Python 的 Windows 安装包：
  echo https://github.com/myflww/love-house/releases/latest
  pause
  exit /b 1
)
py -3.12 desktop\windows_app.py
if errorlevel 1 (
  echo 爱之屋未能启动。源码运行请先安装桌面依赖，或使用安装包。
  pause
  exit /b 1
)
