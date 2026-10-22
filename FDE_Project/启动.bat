@echo off
chcp 936 >nul
title 可被搜索性诊断器
set PYTHONIOENCODING=gbk:replace
cd /d "%~dp0"

echo ============================================================
echo    可被搜索性诊断器  -  本地版
echo ============================================================
echo.

if not exist "web\server.py" goto NOWEB

if not exist "sk\apikey.txt" (
  copy "sk\apikey.example.txt" "sk\apikey.txt" >nul
  echo [首次运行] 已生成 sk\apikey.txt
  echo.
  echo 请把 API Key 粘贴进去（只粘 sk- 开头那一串，不要引号、不要空格），
  echo 保存并关闭记事本，然后重新双击本文件。
  echo.
  echo Key 申请地址：https://platform.deepseek.com
  echo.
  notepad "sk\apikey.txt"
  exit /b 0
)

python --version >nul 2>&1
if errorlevel 1 goto NOPYTHON

python -c "import pdfplumber" >nul 2>&1
if not errorlevel 1 goto RUN

echo [提示] 正在安装 PDF 解析依赖，需要联网一次……
python -m pip install pdfplumber -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.

:RUN
echo 正在启动本地服务，浏览器会自动打开……
echo 关闭这个黑窗口 = 停止服务。
echo.
python -u web\server.py
echo.
echo 服务已停止。
pause
exit /b 0

:NOPYTHON
echo [错误] 没有找到 Python。
echo.
echo 请先安装 Python 3.10 或更高版本。
echo 下载地址：https://www.python.org/downloads/
echo 安装时务必勾选 "Add Python to PATH"。
echo.
pause
exit /b 1

:NOWEB
echo [错误] 找不到 web\server.py
echo.
echo   当前目录：%CD%
echo   脚本目录：%~dp0
echo.
echo 请把「启动.bat」放在项目根目录（和 web 文件夹同级）。
echo.
pause
exit /b 1