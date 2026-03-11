Launch the local dashboard (backend + frontend) in the background.

## Steps

1. Source ports from `.env`:
   ```bash
   source dashboard/ports.sh
   ```

2. Kill any existing processes on those ports:
   ```bash
   lsof -ti :$DASHBOARD_BE_PORT | xargs kill -9 2>/dev/null || true
   lsof -ti :$DASHBOARD_FE_PORT | xargs kill -9 2>/dev/null || true
   ```

3. Start the backend:
   ```bash
   cd $REPO_ROOT
   nohup env USE_LOCAL_DB=1 PYTHONPATH=src uvicorn dashboard.app:app --host 0.0.0.0 --port $DASHBOARD_BE_PORT > /tmp/cogent-backend.log 2>&1 & disown
   ```

4. Start the frontend:
   ```bash
   cd $REPO_ROOT/dashboard/frontend
   nohup npx next dev -p $DASHBOARD_FE_PORT > /tmp/cogent-frontend.log 2>&1 & disown
   ```

5. Wait a few seconds, then verify both are responding:
   ```bash
   curl -sf http://localhost:$DASHBOARD_BE_PORT/health || echo "Backend not ready yet — check /tmp/cogent-backend.log"
   curl -sf http://localhost:$DASHBOARD_FE_PORT > /dev/null || echo "Frontend not ready yet — check /tmp/cogent-frontend.log"
   ```

6. Print: `Dashboard running at http://localhost:$DASHBOARD_FE_PORT`
