#!/bin/bash

# Council Capital - start the stock council backend + dashboard
#
# Prereqs:
#   - .env with OPENROUTER_API_KEY in this directory (for real council runs;
#     the UI works without it on cached/demo data)
#   - The dashboard repo checked out as a sibling directory, or set DASHBOARD_DIR

DASHBOARD_DIR="${DASHBOARD_DIR:-../nextjs-admin-dashboard}"

echo "Starting Council Capital..."
echo ""

# Seed demo data on first boot so the dashboard isn't empty
if [ ! -f data/stocks/index.json ]; then
  echo "No runs found - seeding clearly-labeled demo data..."
  uv run python -m backend.stocks.seed_demo
fi

echo "Starting backend on http://localhost:8001..."
uv run python -m backend.main &
BACKEND_PID=$!

sleep 2

echo "Starting dashboard on http://localhost:3000..."
cd "$DASHBOARD_DIR" || { echo "Dashboard not found at $DASHBOARD_DIR (set DASHBOARD_DIR)"; kill $BACKEND_PID; exit 1; }
[ -d node_modules ] || npm install
npm run dev &
FRONTEND_PID=$!

echo ""
echo "Council Capital is running!"
echo "  Backend:   http://localhost:8001"
echo "  Dashboard: http://localhost:3000"
echo ""
echo "First real steps (needs OPENROUTER_API_KEY in .env):"
echo "  Dry run   (~\$0.01):  uv run python -m backend.stocks.council_runner --dry-run"
echo "  Backfill  (12 months): uv run python -m backend.stocks.backfill"
echo ""
echo "Press Ctrl+C to stop both servers"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
