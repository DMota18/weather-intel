#!/bin/bash
set -e

cd ~/weather-intel
echo "Pulling latest..."
git pull origin main 2>/dev/null || echo "(no remote yet — skipping pull)"

echo "Restarting service..."
sudo systemctl restart weather-intel
sleep 3

STATUS=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/towns)
if [ "$STATUS" = "200" ]; then
    echo "Deploy OK — https://weather.zeladoranalytics.com"
else
    echo "FAILED — status $STATUS"
    sudo journalctl -u weather-intel --no-pager -n 10
    exit 1
fi
