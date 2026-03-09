#!/usr/bin/env bash
# Load dashboard ports from the repo root .env file.
# Usage: source dashboard/ports.sh  (from bash or zsh)

# Handle both bash and zsh
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  _PORTS_SCRIPT="${BASH_SOURCE[0]}"
elif [ -n "${(%):-%x}" 2>/dev/null ]; then
  _PORTS_SCRIPT="${(%):-%x}"
else
  _PORTS_SCRIPT="$0"
fi

REPO_ROOT="$(cd "$(dirname "$_PORTS_SCRIPT")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [ -f "$ENV_FILE" ]; then
  while IFS='=' read -r key val; do
    case "$key" in
      DASHBOARD_BE_PORT|DASHBOARD_FE_PORT)
        val="${val%%#*}"
        val="$(echo "$val" | xargs)"
        eval "export ${key}=\"\${${key}:-${val}}\""
        ;;
    esac
  done < "$ENV_FILE"
fi

# Fallback defaults
export DASHBOARD_BE_PORT="${DASHBOARD_BE_PORT:-8100}"
export DASHBOARD_FE_PORT="${DASHBOARD_FE_PORT:-5200}"

unset _PORTS_SCRIPT

# If executed (not sourced), print for eval.
if [ "${BASH_SOURCE[0]:-$0}" = "$0" ] 2>/dev/null; then
  echo "export DASHBOARD_BE_PORT=$DASHBOARD_BE_PORT"
  echo "export DASHBOARD_FE_PORT=$DASHBOARD_FE_PORT"
fi
