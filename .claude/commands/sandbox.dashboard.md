Launch the local dashboard (backend + frontend) in the background.

## Steps

1. Start the dashboard:
   ```bash
   uv run cogos dashboard start
   ```

2. Wait a few seconds, then verify both are responding:
   ```bash
   source dashboard/ports.sh
   sleep 3
   curl -sf http://localhost:$DASHBOARD_FE_PORT > /dev/null && echo "Frontend OK" || echo "Frontend not ready yet — check dashboard-frontend.log (run 'cogent status' for log_dir)"
   ```

3. Print: `Dashboard running at http://localhost:$DASHBOARD_FE_PORT`

## Troubleshooting

If the dashboard fails to start, check the logs:

```bash
uv run cogent status   # shows log_dir path
```

Then read `{log_dir}/dashboard-backend.log` and `{log_dir}/dashboard-frontend.log`.
