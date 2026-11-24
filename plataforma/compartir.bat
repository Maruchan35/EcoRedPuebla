@echo off
rem Vigia Atoyac - enlace publico temporal con Cloudflare (Quick Tunnel, no necesita cuenta).
rem Requiere que el servidor ya este encendido (iniciar.bat). El enlace vive mientras esta ventana siga abierta.
setlocal
cd /d "%~dp0"
title Vigia Atoyac - enlace publico (Cloudflare)

set "VERSION=2026.10.7"
set "HUELLA=2493dbc168923bb3e59e5e7716f71deced92992eea9acd6e9d74f84ac7751343"
set "CF=herramientas\cloudflared.exe"

set "PUERTO=8000"
if exist "server\datos\puerto.txt" set /p PUERTO=<"server\datos\puerto.txt"

curl.exe -s -o nul -m 4 http://127.0.0.1:%PUERTO%/api/metricas
if errorlevel 1 goto :sinservidor

if exist "%CF%" goto :tunel
echo Descargando cloudflared %VERSION% desde github.com/cloudflare/cloudflared ...
if not exist herramientas mkdir herramientas
curl.exe -L --fail --progress-bar -o "%CF%.descarga" "https://github.com/cloudflare/cloudflared/releases/download/%VERSION%/cloudflared-windows-amd64.exe"
if errorlevel 1 goto :sindescarga
set "CALC="
for /f "skip=1 delims=" %%h in ('certutil -hashfile "%CF%.descarga" SHA256') do if not defined CALC set "CALC=%%h"
set "CALC=%CALC: =%"
if /i not "%CALC%"=="%HUELLA%" goto :huellamal
ren "%CF%.descarga" cloudflared.exe
echo Descarga verificada.

:tunel
echo.
echo  Abriendo el enlace publico. En unos segundos aparece abajo una direccion
echo  https://....trycloudflare.com  - esa es la que se comparte.
echo.
echo  Cualquiera que tenga esa direccion puede ver la pagina mientras esta ventana siga abierta.
echo  Para cortar el enlace: Ctrl+C o cierra esta ventana.
echo.
if exist "server\datos\tunel.log" del "server\datos\tunel.log"
"%CF%" tunnel --no-autoupdate --logfile "server\datos\tunel.log" --url http://127.0.0.1:%PUERTO%
echo.
echo El enlace publico se cerro.
pause
exit /b 0

:sinservidor
echo.
echo El servidor no responde en el puerto %PUERTO%. Abre primero iniciar.bat y vuelve a intentar.
pause
exit /b 1

:sindescarga
echo.
echo No se pudo descargar cloudflared. Revisa la conexion a internet y vuelve a intentar.
if exist "%CF%.descarga" del "%CF%.descarga"
pause
exit /b 1

:huellamal
echo.
echo La huella SHA-256 del archivo descargado no coincide con la publicada. No se va a ejecutar.
echo   Esperada:  %HUELLA%
echo   Obtenida:  %CALC%
del "%CF%.descarga"
pause
exit /b 1
