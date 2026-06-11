"""
regenerate.py — rebuild both the Excel inventory and the HTML explorer
from whatever JSONs currently sit in data/forms/ and data/workflows/.

Usage:
    python scripts/regenerate.py

Run this whenever you add or update form/workflow JSON exports.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

print("Regenerating inventory + explorer...\n")
print("[1/2] Excel inventory")
import build_inventory
build_inventory.build()
print("\n[2/2] HTML explorer")
import build_explorer
build_explorer.build()
print("\nDone. Open output/workspace_explorer.html in your browser.")
