@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if not errorlevel 1 goto python_run
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if not errorlevel 1 goto py_run
echo 请安装 Python 3.8 或更高版本，并勾选 Add Python to PATH。
pause
exit /b 1
:python_run
python -X utf8 "%~dp0vivo_convert.py" %*
set "CONVERT_EXIT=%errorlevel%"
goto finish
:py_run
py -3 -X utf8 "%~dp0vivo_convert.py" %*
set "CONVERT_EXIT=%errorlevel%"
:finish
echo.
pause
exit /b %CONVERT_EXIT%
