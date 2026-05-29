@echo off
rem Run all unit tests in cost-estimator/scripts. Exits non-zero on first failure.
setlocal
cd /d "%~dp0"
python test_buckets.py
if errorlevel 1 exit /b %errorlevel%
python test_roots.py
if errorlevel 1 exit /b %errorlevel%
python test_compare.py
if errorlevel 1 exit /b %errorlevel%
python test_stats_cache.py
if errorlevel 1 exit /b %errorlevel%
python test_cache_ttl.py
if errorlevel 1 exit /b %errorlevel%
echo All tests passed.
