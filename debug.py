# debug.py

import google.generativeai as genai
import platform
import sys

print("=" * 60)
print("--- STARTING FINAL DEBUG SCRIPT ---")
print(f"Python version: {sys.version}")
print(f"Platform: {platform.platform()}")
print("-" * 60)

try:
    print(f"Installed 'google-generativeai' version: {genai.__version__}")
except Exception as e:
    print(f"ERROR: Could not get library version. Is it installed? {e}")

print("-" * 60)
print("Attempting to access 'genai.Client'...")

if hasattr(genai, 'Client'):
    print("✅✅✅ SUCCESS: 'genai.Client' attribute FOUND.")
    print("   This confirms the correct library version is installed.")
else:
    print("❌❌❌ FAILURE: 'genai.Client' attribute NOT FOUND.")
    print("   This indicates the installed library version is TOO OLD.")
    print("\nListing available attributes in 'google.generativeai':")
    # Show available module attributes for debugging
    print(dir(genai))

print("=" * 60)