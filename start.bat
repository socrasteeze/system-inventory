@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo   System Inventory  -  Start
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
    echo [OK] Git found - checking out main and fetching the latest data and code...
    git checkout main
    if errorlevel 1 (
        echo.
        echo [WARN] "git checkout main" did not finish cleanly ^(local changes or a conflict^).
        echo        Continuing with whatever branch is currently checked out.
    )
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

REM --- Guard rail: data\ is the one folder nothing auto-creates (output\ and
REM     docs\ are created by the build scripts themselves as needed). We only
REM     create the bare data\ folder here — NOT per-workspace subfolders —
REM     because an empty forms\/workflows\ folder is enough for the rebuild
REM     to think a workspace exists there and choke on it having no content. ---
if not exist "data\" (
    echo [SETUP] Creating missing data\ folder.
    mkdir "data"
)
if not exist "data\README.txt" (
    (
        echo Drop workspace data here to build the inventory / explorer.
        echo.
        echo Any platform export JSON goes anywhere under data\^<slug^>\ - the rebuild
        echo detects what each file is ^(whole-workspace export, individual form design,
        echo or individual workflow^) and routes it automatically. No manual placement:
        echo the forms\ and workflows\ subfolders still work but nothing requires them.
        echo.
        echo   data\^<slug^>\^<any-name^>.json    e.g. data\liwp\low-income_weatherization_program.json
        echo.
        echo An individual form/workflow export always overrides the same form/workflow
        echo in the whole-workspace baseline ^(a surgical update^).
        echo.
        echo Known slugs already published from this repo: liwp, nve-qar, sce-be, sdge-whp, socal-whp
        echo Slugs use hyphens, not underscores.
        echo.
        echo Full details: see "Adding a new workspace" in CLAUDE.md.
    ) > "data\README.txt"
    echo [SETUP] Wrote data\README.txt with drop-in instructions.
)
echo.

REM --- Rebuild the artifacts ---
echo Rebuilding the inventory and explorer...
echo.
%PY% scripts\regenerate.py
if errorlevel 1 (
    echo.
    echo [ERROR] The rebuild failed or found nothing to build. The most likely causes:
    echo     - data\ has no export JSON yet ^(drop any export under data\^<slug^>\ - see data\README.txt^).
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
REM --- Remember the last-opened view. output\last-view.txt holds G or a slug;
REM     Enter re-opens it. A number, G, or a slug typed directly all work. ---
set "LASTV="
if exist "output\last-view.txt" set /p LASTV=<"output\last-view.txt"
if not defined LASTV set "LASTV=G"

set "CHOICE="
set /p CHOICE="Enter a number, G for global, or press Enter for the last view [!LASTV!]: "

set "TARGET="
set "PICKED="
if "!CHOICE!"=="" set "CHOICE=!LASTV!"
if /i "!CHOICE!"=="G" (
    if exist "output\global\global-explorer.html" (
        set "TARGET=output\global\global-explorer.html"
        set "PICKED=G"
    )
) else (
    if defined WS_!CHOICE! (
        for %%V in (!CHOICE!) do (
            set "TARGET=output\!WS_%%V!\workspace_explorer.html"
            set "PICKED=!WS_%%V!"
        )
    ) else (
        if exist "output\!CHOICE!\workspace_explorer.html" (
            set "TARGET=output\!CHOICE!\workspace_explorer.html"
            set "PICKED=!CHOICE!"
        )
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
if defined PICKED >"output\last-view.txt" echo !PICKED!

echo.
echo Opening !TARGET! in your default browser...
start "" "!TARGET!"
echo.
echo Done. You can close this window.
pause
endlocal
