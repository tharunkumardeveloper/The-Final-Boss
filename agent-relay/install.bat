@echo off
setlocal
cd /d "%~dp0"
echo.
echo  Ping Me Later / Relay - install
echo  ==============================

where python >nul 2>nul || (echo  [x] Python 3.12+ not found. Install it from python.org, tick "Add to PATH", then re-run. & goto :fail)
where npm >nul 2>nul || (echo  [x] Node.js 20+ not found. Install it from nodejs.org, then re-run. & goto :fail)

echo.
echo  [1/4] Python packages
python -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail

echo  [2/4] Settings file
if exist ".env" (
  echo        using .env
) else if exist "..\falkor.env" (
  echo        using ..\falkor.env
) else (
  copy /y .env.example .env >nul
  echo        created .env from .env.example - open it and fill in your FalkorDB and Groq/Gemini keys
)

echo  [3/4] Embedding model + demo cache
python -m relay.warm || goto :fail

echo  [4/4] Web app packages
pushd web
call npm install --no-fund --no-audit --loglevel=error || (popd & goto :fail)
popd

echo.
echo  Done. Run start.bat to launch, or "start.bat mock" to try the web app without a backend.
echo.
pause
exit /b 0

:fail
echo.
echo  Install stopped - see the message above.
pause
exit /b 1
