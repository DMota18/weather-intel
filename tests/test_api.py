"""Integration tests for FastAPI endpoints."""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestTownsEndpoint:
    def test_returns_all_towns(self):
        resp = client.get("/api/v1/towns")
        assert resp.status_code == 200
        data = resp.json()
        assert "worcester" in data
        assert "hyannis" in data
        assert len(data) == 10

    def test_town_has_name_and_covers(self):
        resp = client.get("/api/v1/towns")
        worcester = resp.json()["worcester"]
        assert "name" in worcester
        assert "covers" in worcester


class TestForecastEndpoint:
    def test_valid_town_returns_200(self):
        resp = client.get("/api/v1/forecast/worcester")
        assert resp.status_code == 200
        data = resp.json()
        assert data["town"] == "Worcester"
        assert "days" in data
        assert "best_window" in data

    def test_invalid_town_returns_404(self):
        resp = client.get("/api/v1/forecast/faketown")
        assert resp.status_code == 404

    def test_forecast_has_scored_hours(self):
        resp = client.get("/api/v1/forecast/worcester")
        data = resp.json()
        assert len(data["days"]) > 0
        first_day = data["days"][0]
        assert first_day["score"] in ["green", "yellow", "red"]
        assert len(first_day["hours"]) > 0
        assert "pour_score" in first_day["hours"][0]


class TestSealerCheckEndpoint:
    def test_valid_town_returns_200(self):
        resp = client.get("/api/v1/sealer-check/worcester")
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] in ["green", "yellow", "red"]
        assert data["verdict"] in ["SAFE TO SEAL", "USE CAUTION", "DO NOT SEAL"]

    def test_has_factors_and_details(self):
        resp = client.get("/api/v1/sealer-check/worcester")
        data = resp.json()
        assert "factors" in data
        assert "details" in data
        assert "last_24h" in data
        assert "current" in data

    def test_invalid_town_returns_404(self):
        resp = client.get("/api/v1/sealer-check/faketown")
        assert resp.status_code == 404


class TestCureCheckEndpoint:
    def test_valid_town_returns_200(self):
        resp = client.get("/api/v1/cure-check/worcester")
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] in ["green", "yellow", "red"]
        assert "factors" in data
        assert "issues" in data

    def test_invalid_town_returns_404(self):
        resp = client.get("/api/v1/cure-check/faketown")
        assert resp.status_code == 404


class TestHistoricalEndpoint:
    def test_invalid_date_returns_400(self):
        resp = client.get("/api/v1/weather/worcester/2024-13-45")
        assert resp.status_code == 400
        assert "Invalid date" in resp.json()["detail"]

    def test_invalid_town_returns_404(self):
        resp = client.get("/api/v1/weather/faketown/2024-06-15")
        assert resp.status_code == 404


class TestStreamStatus:
    def test_returns_status(self):
        resp = client.get("/api/v1/stream/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "connected_clients" in data


class TestAboutPage:
    def test_returns_html(self):
        resp = client.get("/about")
        assert resp.status_code == 200
        assert "Weather Intel" in resp.text

    def test_dashboard_returns_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Weather Intel" in resp.text
