@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements-smart-home.txt
if errorlevel 1 goto fail
rem Ev otomasyonu: Bluetooth (bleak) ve Tuya ayri klasore; .venv paketleriyle cakismaz
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --upgrade --target lib\ev\pydeps bleak==3.1.0
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --upgrade --no-deps --target lib\ev\pydeps tinytuya==1.21.1
if errorlevel 1 goto fail
.venv\Scripts\python.exe setup_local.py
if errorlevel 1 goto fail
echo Kurulum tamamlandi. Yumi'yi Masaustundeki ya da Baslat menusundeki Yumi kisayoluyla acabilirsiniz.
exit /b 0
:fail
echo Kurulum tamamlanamadi. Internet ve Python kurulumunu kontrol edin.
pause
exit /b 1
