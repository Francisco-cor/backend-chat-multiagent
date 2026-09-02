#!/usr/bin/env bash
# scripts/gen_sdk.sh — Fase 10.3
# Regenerates SDKs from live OpenAPI spec.
# Requires: docker (openapi-generator) or npx @openapitools/openapi-generator-cli
set -e
BASE_URL=${1:-http://localhost:8005}
OUT_PY="sdk/python"
OUT_TS="sdk/typescript"
SPEC="/tmp/openapi.json"

echo "[gen_sdk] Fetching $BASE_URL/openapi.json -> $SPEC"
curl -sf "$BASE_URL/openapi.json" -o "$SPEC" || { echo "Failed to fetch $BASE_URL/openapi.json — is the backend running?"; exit 1; }

if command -v openapi-generator-cli >/dev/null 2>&1; then
  echo "[gen_sdk] Generating Python SDK..."
  openapi-generator-cli generate -i "$SPEC" -g python -o "$OUT_PY/generated" --additional-properties packageName=backend_chat_sdk_generated || true
  echo "[gen_sdk] Generating TS SDK..."
  openapi-generator-cli generate -i "$SPEC" -g typescript-fetch -o "$OUT_TS/generated" || true
elif command -v docker >/dev/null 2>&1; then
  echo "[gen_sdk] Via docker openapitools/openapi-generator-cli"
  docker run --rm -v "$PWD:/local" openapitools/openapi-generator-cli generate -i "/local/$SPEC" -g python -o "/local/$OUT_PY/generated" || true
  docker run --rm -v "$PWD:/local" openapitools/openapi-generator-cli generate -i "/local/$SPEC" -g typescript-fetch -o "/local/$OUT_TS/generated" || true
else
  echo "[gen_sdk] No generator found — hand-written SDK in $OUT_PY/backend_chat_sdk and $OUT_TS/src is used as fallback."
fi
echo "[gen_sdk] Done. Hand-written SDK remains authoritative for DX; generated/ contains reference."
