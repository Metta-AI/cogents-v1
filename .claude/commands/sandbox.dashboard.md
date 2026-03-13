Launch the local dashboard (backend + frontend) in the background.

## Steps

1. Start the dashboard:
   ```bash
   cd /Users/daveey/code/cogents/cogents.1 && PYTHONPATH=src python -m cogos.cli -c local dashboard start
   ```

2. Wait a few seconds, then verify both are responding:
   ```bash
   source dashboard/ports.sh
   sleep 3
   curl -sf http://localhost:$DASHBOARD_FE_PORT > /dev/null && echo "Frontend OK" || echo "Frontend not ready yet — check /tmp/cogent-frontend.log"
   ```

3. Print: `Dashboard running at http://localhost:$DASHBOARD_FE_PORT`
