#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "$0")" && pwd)
if ! command -v node >/dev/null 2>&1; then
  echo "Install Node.js 22.12+ or 24+ (including npm), then run this script again." >&2
  exit 1
fi
exec node "$ROOT/scripts/start.cjs" "$@"
