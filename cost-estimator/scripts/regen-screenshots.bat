@echo off
rem Regenerate cost-estimator README screenshots from the synthetic fixture.
rem Produces screenshot-trend.png and screenshot-compare.png at repo root.

setlocal

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "REPO_ROOT=%SCRIPT_DIR%\.."
set "FIXTURE=%REPO_ROOT%\tests\fixtures\sessions-demo.csv"
set "DEMO_RANGE=2026-03"

pushd "%REPO_ROOT%"

echo [1/4] rendering plot-trend HTML
python "scripts\plot-trend.py" --month %DEMO_RANGE% --csv "%FIXTURE%" --inline-js --out "reports\_trend-demo.html"
if errorlevel 1 goto :error

echo [2/4] rendering plot-compare HTML
python "scripts\plot-compare.py" --month %DEMO_RANGE% --csv "%FIXTURE%" --inline-js --out "reports\_compare-demo.html"
if errorlevel 1 goto :error

echo [3/4] capturing screenshot-trend.png
python "scripts\capture-screenshot.py" "reports\_trend-demo.html" "screenshot-trend.png"
if errorlevel 1 goto :error

echo [4/4] capturing screenshot-compare.png
python "scripts\capture-screenshot.py" "reports\_compare-demo.html" "screenshot-compare.png"
if errorlevel 1 goto :error

del "reports\_trend-demo.html" "reports\_compare-demo.html" 2>nul

echo done. screenshots at "%REPO_ROOT%\screenshot-trend.png" and "%REPO_ROOT%\screenshot-compare.png"
popd
endlocal
exit /b 0

:error
popd
endlocal
echo regen-screenshots.bat failed (errorlevel %errorlevel%) 1>&2
exit /b 1
