#!/usr/bin/env bash
# Refresh the SoCal WHP inventory and open it in the default browser.
# Designed to be double-clicked by someone who has never used a terminal.
cd "$(dirname "$0")" || exit 1

pause() { echo; read -n 1 -s -r -p "Press any key to close..."; echo; }

echo "============================================"
echo "  SoCal WHP Inventory  -  Refresh & Open"
echo "============================================"
echo

# --- Sanity check: Python on PATH ---
PY=""
if command -v python3 >/dev/null 2>&1; then PY="python3"
elif command -v python  >/dev/null 2>&1; then PY="python"; fi
if [ -z "$PY" ]; then
    echo "[ERROR] Python is not installed, or it is not on your PATH."
    echo
    echo "  How to fix:"
    echo "    1. Download Python from https://www.python.org/downloads/"
    echo "       (macOS), or install it with your package manager"
    echo "       (Linux, e.g.  sudo apt install python3 python3-pip)."
    echo "    2. Reopen this launcher."
    pause
    exit 1
fi
echo "[OK] Python found ($PY)."

# --- Sanity check: git on PATH (optional) ---
if command -v git >/dev/null 2>&1; then
    echo "[OK] Git found - fetching the latest data and code..."
    if ! git pull; then
        echo
        echo "[WARN] \"git pull\" did not finish cleanly (no network, no remote, or a conflict)."
        echo "       Continuing with the local copy you already have."
    fi
else
    echo "[WARN] Git is not installed - skipping the update step."
    echo "       You will rebuild from the data already on this machine."
    echo "       (Install Git from https://git-scm.com/downloads to enable auto-update.)"
fi
echo

# --- Sanity check: openpyxl importable ---
if ! "$PY" -c "import openpyxl" >/dev/null 2>&1; then
    echo "[WARN] The required Python package \"openpyxl\" is missing."
    read -r -p "      Install it now from requirements.txt? [Y/N] " INSTALL
    case "$INSTALL" in
        [Yy]*)
            if ! "$PY" -m pip install -r requirements.txt; then
                echo "[ERROR] Could not install the dependencies. See the messages above."
                pause
                exit 1
            fi ;;
        *)
            echo "Cannot continue without openpyxl. Exiting."
            pause
            exit 1 ;;
    esac
fi
echo "[OK] Dependencies present."
echo

# --- Rebuild the artifacts ---
echo "Rebuilding the inventory and explorer..."
echo
if ! "$PY" scripts/regenerate.py; then
    echo
    echo "[ERROR] The rebuild failed. The most likely causes:"
    echo "    - A file in the data/ folder is not valid JSON."
    echo "    - A required package is missing  (run: $PY -m pip install -r requirements.txt)."
    echo "    - Your Python is too old; version 3.9 or newer is required."
    echo "      Check it with:  $PY --version"
    echo "  Read the messages above for the exact error, then try again."
    pause
    exit 1
fi
echo

# --- Choose a view ---
echo "Which view would you like to open?"
echo
GLOBAL="output/global/global-explorer.html"
declare -a SLUGS=()
[ -f "$GLOBAL" ] && echo "  [G] Global cross-workspace view"
i=0
for d in output/*/; do
    name="$(basename "$d")"
    [ "$name" = "global" ] && continue
    if [ -f "${d}workspace_explorer.html" ]; then
        i=$((i + 1)); SLUGS[$i]="$name"; echo "  [$i] $name"
    fi
done
echo
read -r -p "Enter a number, G for the global view, or just press Enter for global: " CHOICE

TARGET=""
if [ -z "$CHOICE" ] || [ "$CHOICE" = "G" ] || [ "$CHOICE" = "g" ]; then
    [ -f "$GLOBAL" ] && TARGET="$GLOBAL"
elif [ -n "${SLUGS[$CHOICE]:-}" ]; then
    TARGET="output/${SLUGS[$CHOICE]}/workspace_explorer.html"
fi
if [ -z "$TARGET" ]; then
    if [ -f "$GLOBAL" ]; then TARGET="$GLOBAL"
    elif [ -n "${SLUGS[1]:-}" ]; then TARGET="output/${SLUGS[1]}/workspace_explorer.html"; fi
fi
if [ -z "$TARGET" ] || [ ! -f "$TARGET" ]; then
    echo "[ERROR] Could not find a view to open. Did the rebuild produce any output?"
    pause
    exit 1
fi

echo
echo "Opening $TARGET in your default browser..."
if command -v open >/dev/null 2>&1; then open "$TARGET"
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$TARGET"
else echo "Please open this file manually in your browser: $TARGET"; fi
echo
echo "Done."
pause
