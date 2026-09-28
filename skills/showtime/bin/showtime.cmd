@echo off
rem showtime: Windows cmd entry point. Finds Python and runs lib\st\launcher.py.
rem Override the interpreter with SHOWTIME_PYTHON. Safe for install paths with
rem spaces and parentheses (no parenthesised blocks around expanded paths).
setlocal
set "ST_LAUNCHER=%~dp0..\lib\st\launcher.py"
set "ST_HOME=%USERPROFILE%\.showtime"
if defined SHOWTIME_HOME set "ST_HOME=%SHOWTIME_HOME%"
if defined SHOWTIME_PYTHON goto custom
if exist "%ST_HOME%\venv\Scripts\python.exe" goto venv
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul && goto pylauncher
where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul && goto python
where uv >nul 2>nul && goto uv
rem a fresh uv install is not on this app's PATH until it restarts: try the installers' folders
set "ST_UV=%USERPROFILE%\.local\bin\uv.exe"
if exist "%ST_UV%" goto uvpath
set "ST_UV=%USERPROFILE%\.cargo\bin\uv.exe"
if exist "%ST_UV%" goto uvpath
set "ST_UV=%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
if exist "%ST_UV%" goto uvpath
echo showtime: no Python 3.8+ found. 1>&2
echo   Install uv: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" 1>&2
echo   or Python 3 from https://www.python.org/downloads/ , then run: showtime setup 1>&2
echo   If you just installed one, restart Claude Code (or open a new terminal) so it sees the new PATH. 1>&2
exit /b 127
:uvpath
"%ST_UV%" run --no-project --python 3.12 python "%ST_LAUNCHER%" %*
exit /b %ERRORLEVEL%
:custom
"%SHOWTIME_PYTHON%" "%ST_LAUNCHER%" %*
exit /b %ERRORLEVEL%
:venv
"%ST_HOME%\venv\Scripts\python.exe" "%ST_LAUNCHER%" %*
exit /b %ERRORLEVEL%
:pylauncher
py -3 "%ST_LAUNCHER%" %*
exit /b %ERRORLEVEL%
:python
python "%ST_LAUNCHER%" %*
exit /b %ERRORLEVEL%
:uv
uv run --no-project --python 3.12 python "%ST_LAUNCHER%" %*
exit /b %ERRORLEVEL%
