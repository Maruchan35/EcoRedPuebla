@echo off
rem Vigia Atoyac - inicia el servidor y abre la plataforma en el navegador.
rem La primera vez crea el entorno de Python e instala las dependencias: necesita internet.
rem Si el puerto 8000 esta ocupado, el servidor toma el siguiente libre y lo avisa en esta ventana.
setlocal
cd /d "%~dp0"
title Vigia Atoyac - servidor

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY goto :sinpython

if not exist ".venv\listo.txt" (
  echo Preparando el entorno por primera vez. Tarda uno o dos minutos...
  if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
  if not exist ".venv\Scripts\python.exe" goto :sinpython
  ".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r server\requirements.txt || goto :sininstalar
  echo ok> ".venv\listo.txt"
)

echo.
echo Cuentas de demostracion: server\datos\cuentas_demo.txt
echo Para detener el servidor: Ctrl+C o cierra esta ventana.
echo.
set "VA_ABRIR=1"
".venv\Scripts\python.exe" -m server
pause
exit /b 0

:sinpython
echo.
echo No se encontro Python. Instala Python 3.9 o mas nuevo desde https://www.python.org/downloads/
echo y marca la casilla "Add python.exe to PATH" durante la instalacion. Luego ejecuta este archivo otra vez.
pause
exit /b 1

:sininstalar
echo.
echo No se pudieron instalar las dependencias. Revisa la conexion a internet y ejecuta este archivo otra vez.
pause
exit /b 1
