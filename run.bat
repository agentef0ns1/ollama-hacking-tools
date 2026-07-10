@echo off
cd /d "%~dp0"
set PYTHON=%~dp0.venv-win\Scripts\python.exe
if not exist "%PYTHON%" (
    echo [WARN] No existe .venv-win en esta carpeta.
    echo        Ejecuta: python -m venv .venv-win ^&^& .venv-win\Scripts\pip install -r requirements.txt
    set PYTHON=python
)
echo Starting Ollama-hacking-tool...
"%PYTHON%" app.py %*
pause
