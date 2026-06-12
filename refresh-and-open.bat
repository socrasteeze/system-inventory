@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo   SoCal WHP Inventory  -  Refresh ^& Open
echo ============================================
echo.

REM --- Sanity check: Python on PATH ---
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY (
    py --version >nul 2>&1 && set "PY=py"
)
if not defined PY (
    echo [ERROR] Python is not installed, or it is not on your PATH.
    echo.
    echo   How to fix:
    echo     1. Download Python from https://www.python.org/downloads/
    echo     2. Run the installer.
    echo     3. IMPORTANT: on the first installer screen, check "Add Python to PATH".
    echo     4. Finish the install, then double-click this launcher again.
    echo.
    pause
    exit /b 1
)
echo [OK] Python found.

REM --- Sanity check: git on PATH (optional) ---
git --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] Git is not installed - skipping the update step.
    echo        You will rebuild from the data already on this machine.
    echo        ^(Install Git from https://git-scm.com/download/win to enable auto-update.^)
) else (
    echo [OK] Git found - fetching the latest data and code...
    git pull
    if errorlevel 1 (
        echo.
        echo [WARN] "git pull" did not finish cleanly ^(no network, no remote, or a conflict^).
        echo        Continuing with the local copy you already have.
    )
)
echo.

REM --- Sanity check: openpyxl importable ---
%PY% -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
    echo [WARN] The required Python package "openpyxl" is missing.
    set "INSTALL="
    set /p INSTALL="      Install it now from requirements.txt? [Y/N] "
    if /i "!INSTALL!"=="Y" (
        %PY% -m pip install -r requirements.txt
        if errorlevel 1 (
            echo [ERROR] Could not install the dependencies. See the messages above.
            pause
            exit /b 1
        )
    ) else (
        echo Cannot continue without openpyxl. Exiting.
        pause
        exit /b 1
    )
)
echo [OK] Dependencies present.
echo.

REM --- Rebuild the artifacts ---
echo Rebuilding the inventory and explorer...
echo.
%PY% scripts\regenerate.py
if errorlevel 1 (
    echo.
    echo [ERROR] The rebuild failed. The most likely causes:
    echo     - A file in the data\ folder is not valid JSON.
    echo     - A required package is missing  ^(run: %PY% -m pip install -r requirements.txt^).
    echo     - Your Python is too old; version 3.9 or newer is required.
    echo       Check it with:  %PY% --version
    echo   Read the messages above for the exact error, then try again.
    echo.
    pause
    exit /b 1
)
echo.

REM --- Choose a view ---
echo Which view would you like to open?
echo.
set "N=0"
if exist "output\global\global-explorer.html" echo   [G] Global cross-workspace view
for /d %%D in (output\*) do (
    if /i not "%%~nxD"=="global" (
        if exist "%%D\workspace_explorer.html" (
            set /a N+=1
            set "WS_!N!=%%~nxD"
            echo   [!N!] %%~nxD
        )
    )
)
echo.
set "CHOICE="
set /p CHOICE="Enter a number, G for the global view, or just press Enter for global: "

set "TARGET="
if "!CHOICE!"=="" set "CHOICE=G"
if /i "!CHOICE!"=="G" (
    if exist "output\global\global-explorer.html" set "TARGET=output\global\global-explorer.html"
) else (
    if defined WS_!CHOICE! (
        for %%V in (!CHOICE!) do set "TARGET=output\!WS_%%V!\workspace_explorer.html"
    )
)
if not defined TARGET (
    if exist "output\global\global-explorer.html" (
        set "TARGET=output\global\global-explorer.html"
    ) else if defined WS_1 (
        set "TARGET=output\!WS_1!\workspace_explorer.html"
    )
)
if not defined TARGET (
    echo [ERROR] Could not find a view to open. Did the rebuild produce any output?
    pause
    exit /b 1
)
if not exist "!TARGET!" (
    echo [ERROR] Expected file was not found: !TARGET!
    pause
    exit /b 1
)

echo.
echo Opening !TARGET! in your default browser...
start "" "!TARGET!"
echo.
echo Done. You can close this window.
pause
endlocal
