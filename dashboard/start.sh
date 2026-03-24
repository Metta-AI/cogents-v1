#!/bin/sh
set -e

# Start FastAPI backend
python -m uvicorn cogos.api.app:app --host 0.0.0.0 --port 8100 &
BACKEND_PID=$!

# Start Next.js frontend
node /app/frontend/server.js &
FRONTEND_PID=$!

trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0' TERM INT

# Wait — if either exits, shut down
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 1
done

kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
exit 1
