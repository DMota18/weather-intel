#!/bin/bash
set -e

cd ~/weather-intel

# Tag current commit for rollback
PREV=$(git rev-parse HEAD)
echo "Current: $PREV"

echo "Pulling latest..."
git pull origin main 2>/dev/null || echo "(no remote yet — skipping pull)"

echo "Restarting service..."
sudo systemctl restart weather-intel
sleep 3

STATUS=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/towns)
if [ "$STATUS" = "200" ]; then
    echo "Deploy OK — https://weather.zeladoranalytics.com"
else
    echo "DEPLOY FAILED (status $STATUS) — rolling back to $PREV"
    git checkout $PREV
    sudo systemctl restart weather-intel
    sleep 3
    ROLLBACK_STATUS=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/towns)
    echo "Rollback status: $ROLLBACK_STATUS"
    exit 1
fi
