@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" main.py
  goto :end
)
rem Usa o ambiente existente somente para executar, sem instalar ou alterar pacotes.
if exist "..\.venv\Scripts\python.exe" (
  "..\.venv\Scripts\python.exe" main.py
  goto :end
)
python main.py
:end
if errorlevel 1 (
  echo.
  echo Nao foi possivel abrir a previa. Consulte README.md nesta pasta.
  pause
)
