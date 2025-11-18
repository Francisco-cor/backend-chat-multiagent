# debug.py

import google.generativeai as genai
import platform
import sys

print("=" * 60)
print("--- INICIANDO SCRIPT DE DEPURACIÓN DEFINITIVO ---")
print(f"Python version: {sys.version}")
print(f"Platform: {platform.platform()}")
print("-" * 60)

try:
    print(f"Versión de 'google-generativeai' instalada: {genai.__version__}")
except Exception as e:
    print(f"ERROR: No se pudo obtener la versión de la librería. ¿Está instalada? {e}")

print("-" * 60)
print("Intentando acceder a 'genai.Client'...")

if hasattr(genai, 'Client'):
    print("✅✅✅ ÉXITO: El atributo 'genai.Client' FUE ENCONTRADO.")
    print("   Esto significa que la versión de la librería es la correcta.")
else:
    print("❌❌❌ FALLO: El atributo 'genai.Client' NO FUE ENCONTRADO.")
    print("   Esto confirma que la versión de la librería instalada es DEMASIADO ANTIGUA.")
    print("\nListando todo lo que hay disponible en 'google.generativeai':")
    # Esto nos mostrará todo lo que Python puede ver dentro del módulo
    print(dir(genai))

print("=" * 60)