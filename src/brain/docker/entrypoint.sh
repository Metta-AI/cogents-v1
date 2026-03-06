#!/usr/bin/env bash
set -euo pipefail

# Start SSM agent in background (required for ECS Exec)
nohup amazon-ssm-agent &>/var/log/ssm-agent.log &

# Write the ecs_entry runner script (captures exit code and signals tmux)
cat > /tmp/run-ecs-entry.sh << 'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
cd /app
python -m brain.lambdas.executor.ecs_entry
EXIT_CODE=$?
# Write exit code for entrypoint to read
echo "$EXIT_CODE" > /tmp/ecs-exit-code
# Signal tmux wait-for
tmux wait-for -S claude-done
SCRIPT
chmod +x /tmp/run-ecs-entry.sh

# Start tmux session running the entry point
tmux new-session -d -s claude /tmp/run-ecs-entry.sh

# Block until the session signals completion
tmux wait-for claude-done

# Exit with the same code as the Python process
EXIT_CODE=$(cat /tmp/ecs-exit-code 2>/dev/null || echo 1)
exit "$EXIT_CODE"
