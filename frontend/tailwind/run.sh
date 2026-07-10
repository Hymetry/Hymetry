#!/bin/bash
set -euo pipefail

# Run from this script's directory so npm finds package.json and input.css
# on every deployment target.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Production build (minified) - outputs to /static/css/output.css
npm run build:prod

# Development build (with watch mode) - outputs to /static/css/output.css  
# npm run build
