#!/bin/bash
# UserPromptSubmit hook -- tracks skill usage via Datadog when user types /skill-name.

set -euo pipefail

# Guard: need jq
command -v jq > /dev/null 2>&1 || exit 0

# Read hook payload from stdin
payload=$(cat)

# Extract prompt text
prompt=$(echo "$payload" | jq -r '.prompt // empty' 2> /dev/null)

# Only track slash commands (skill invocations)
[[ "$prompt" =~ ^/ ]] || exit 0

# Extract skill name: strip leading /, take first word, trim whitespace
skill=$(echo "$prompt" | sed 's|^/||' | awk '{print $1}')
[ -z "$skill" ] && exit 0

# Resolve DD API key: env var > cache file
api_key="${DD_API_KEY:-}"
if [ -z "$api_key" ] && [ -f "$HOME/.metta/dd_api_key" ]; then
  api_key=$(cat "$HOME/.metta/dd_api_key")
fi
[ -z "$api_key" ] && exit 0

# User tag: git user.name, sanitized
user=$(git config user.name 2> /dev/null | tr '[:upper:] ' '[:lower:]_' || echo "unknown")
[ -z "$user" ] && user="unknown"

# Skill prefix (everything before the first dot, or the skill itself)
skill_prefix="${skill%%.*}"

timestamp=$(date +%s)

# Fire and forget
(curl -s -X POST "https://api.datadoghq.com/api/v2/series" \
  -H "Content-Type: application/json" \
  -H "DD-API-KEY: ${api_key}" \
  -d "$(
    jq -n \
      --arg skill "$skill" \
      --arg user "$user" \
      --arg skill_prefix "$skill_prefix" \
      --argjson timestamp "$timestamp" \
      '{series: [{metric: "metta.skills.usage", type: 1, points: [{timestamp: $timestamp, value: 1}], tags: ["skill:\($skill)", "user:\($user)", "skill_prefix:\($skill_prefix)", "tool:claude"]}]}'
  )" > /dev/null 2>&1) &

exit 0
