@echo off
setlocal
cd /d "%~dp0"
set API_PORT=8000
set WEB_PORT=5173

if /i "%~1"=="mock" (
  echo  Starting the web app on canned data - no backend, no API keys needed.
  start "WiFight web (mock)" cmd /k "cd /d web && npx vite --mode mock --port %WEB_PORT% --strictPort"
  timeout /t 4 /nobreak >nul
  start "" http://localhost:%WEB_PORT%/
  exit /b 0
)

if not exist ".env" if not exist "..\falkor.env" (
  echo  No .env found. Run install.bat, fill in .env, then run start.bat again.
  pause
  exit /b 1
)

echo.
echo  Relay (WiFight demo) - starting
echo  ===============================
start "Relay API :%API_PORT%" cmd /k "set CORS_ORIGINS=http://localhost:%WEB_PORT%&& python -m uvicorn api.main:app --host 127.0.0.1 --port %API_PORT%"
start "WiFight web :%WEB_PORT%" cmd /k "cd /d web && set VITE_API_URL=http://localhost:%API_PORT%&& set VITE_WS_URL=ws://localhost:%API_PORT%&& set VITE_MOCK=0&& npx vite --port %WEB_PORT% --strictPort"

echo  Waiting for the API to come up...
set /a tries=0
:wait
timeout /t 2 /nobreak >nul
curl -s -f http://127.0.0.1:%API_PORT%/health >nul 2>nul && goto :up
set /a tries+=1
if %tries% lss 45 goto :wait
echo  The API did not answer within 90 s. Check the "Relay API" window for the error.
pause
exit /b 1

:up
start "" http://localhost:%WEB_PORT%/
start "" http://localhost:%WEB_PORT%/console
echo.
echo  Portal   http://localhost:%WEB_PORT%/
echo  Console  http://localhost:%WEB_PORT%/console
echo  API      http://localhost:%API_PORT%/docs
echo.
echo  To stop: close the "Relay API" and "WiFight web" windows.
exit /b 0
