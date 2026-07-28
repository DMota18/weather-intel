#!/bin/bash
set -e

cd ~/weather-intel

# Commit to roll back to if the new release is unhealthy. The CI deploy step
# exports PREV_SHA *before* pulling; fall back to the pre-pull reflog entry (or
# current HEAD) when run manually.
PREV=${PREV_SHA:-$(git rev-parse 'HEAD@{1}' 2>/dev/null || git rev-parse HEAD)}
echo "Rollback target: $PREV"

echo "Pulling latest..."
git pull origin main 2>/dev/null || echo "(no remote yet — skipping pull)"

# Install any new/updated dependencies into the service venv BEFORE restarting.
# If this fails, set -e aborts here and the currently-running service is left
# untouched (no outage).
echo "Installing dependencies..."
venv/bin/pip install -q -r requirements.txt

echo "Restarting service..."
sudo systemctl restart weather-intel
sleep 3

STATUS=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/towns)
if [ "$STATUS" = "200" ]; then
    echo "Deploy OK — https://weather.zeladoranalytics.com"
else
    echo "DEPLOY FAILED (status $STATUS) — rolling back to $PREV"
    git checkout "$PREV"
    venv/bin/pip install -q -r requirements.txt
    sudo systemctl restart weather-intel
    sleep 3
    ROLLBACK_STATUS=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/towns)
    echo "Rollback status: $ROLLBACK_STATUS"
    exit 1
fi
