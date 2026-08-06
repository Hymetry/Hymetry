#!/bin/bash
set -euo pipefail

# Run from this script's directory so npm finds package.json and input.css
# on every deployment target.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

REQUIRED_NODE_MAJOR=20

if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: Node.js ${REQUIRED_NODE_MAJOR}+ is required to build Tailwind, but node is not available in PATH." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm is required to install and build Tailwind, but npm is not available in PATH." >&2
  exit 1
fi

NODE_VERSION="$(node --version)"
NODE_MAJOR="${NODE_VERSION#v}"
NODE_MAJOR="${NODE_MAJOR%%.*}"

if [[ ! "$NODE_MAJOR" =~ ^[0-9]+$ ]] || (( NODE_MAJOR < REQUIRED_NODE_MAJOR )); then
  echo "ERROR: Tailwind requires Node.js ${REQUIRED_NODE_MAJOR}+; the deployment service resolved ${NODE_VERSION} at $(command -v node)." >&2
  exit 1
fi

NPM_VERSION="$(npm --version)"
echo "Tailwind runtime: node=$NODE_VERSION ($(command -v node)), npm=$NPM_VERSION ($(command -v npm))"

# Recreate node_modules from the committed lockfile so deployments never reuse
# stale or locally resolved packages.
npm ci --no-audit --no-fund

# Production build (minified) plus the CSS contract check. The build outputs to
# /static/css/output.css and the contract fails before collectstatic can run.
npm test

# Development build (with watch mode) - outputs to /static/css/output.css  
# npm run build:watch
