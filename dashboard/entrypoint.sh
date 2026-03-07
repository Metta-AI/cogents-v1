#!/bin/sh
set -e

# Download frontend assets from S3 if configured
if [ -n "$DASHBOARD_ASSETS_S3" ]; then
    echo "Downloading frontend assets from $DASHBOARD_ASSETS_S3 ..."
    mkdir -p /app/frontend
    aws s3 cp "$DASHBOARD_ASSETS_S3" /tmp/frontend.tar.gz --quiet
    tar xzf /tmp/frontend.tar.gz -C /app/frontend
    rm /tmp/frontend.tar.gz
    echo "Frontend assets ready."
else
    echo "WARNING: DASHBOARD_ASSETS_S3 not set, frontend may not be available."
fi

# Start FastAPI backend
python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8100 &
BACKEND_PID=$!

# Start Next.js frontend (if assets were downloaded)
if [ -f /app/frontend/server.js ]; then
    node /app/frontend/server.js &
    FRONTEND_PID=$!
else
    echo "WARNING: /app/frontend/server.js not found, frontend not started."
    FRONTEND_PID=""
fi

# Trap signals to clean up both processes
trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0' TERM INT

# Wait for both; if either exits, kill the other
if [ -n "$FRONTEND_PID" ]; then
    while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
        sleep 1
    done
else
    wait "$BACKEND_PID"
fi

kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
exit 1
