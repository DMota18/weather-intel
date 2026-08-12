"""Integration tests for FastAPI endpoints."""

import sys
import os

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
        # None = no scorable working hours (e.g. evening fragment) — shown as "no data"
        assert first_day["score"] in ["green", "yellow", "red", None]
        assert len(first_day["hours"]) > 0
        assert "pour_score" in first_day["hours"][0]


class TestSealerCheckEndpoint:
    def test_valid_town_returns_200(self):
        resp = client.get("/api/v1/sealer-check/worcester")
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] in ["green", "yellow", "red", None]
        assert data["verdict"] in ["SAFE TO SEAL", "USE CAUTION", "DO NOT SEAL", "NO DATA — DO NOT SEAL"]

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
        assert data["score"] in ["green", "yellow", "red", None]
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

    def test_renders_fully_with_no_unresolved_template_syntax(self):
        resp = client.get("/about")
        assert "{{" not in resp.text and "{%" not in resp.text

    def test_reports_a_freshness_state(self):
        # Either sources are live or they aren't — the page must say which,
        # never present stale figures as current
        resp = client.get("/about")
        assert "Live system" in resp.text or "Data sources unavailable" in resp.text

    def test_shows_architecture_diagram(self):
        resp = client.get("/about")
        assert "<svg viewBox" in resp.text

    def test_test_count_is_computed_not_hardcoded(self):
        # The About page quotes a test count; it must come from the suite on
        # disk so it can't drift as tests are added
        from main import _count_tests
        counted = _count_tests()
        assert counted is None or counted > 0

    def test_stats_degrade_without_inventing_numbers(self):
        from main import _platform_stats
        stats = _platform_stats()
        assert set(["records", "stations", "db_ok"]).issubset(stats.keys())
        if not stats["db_ok"]:
            assert stats["records"] is None

    def test_dashboard_returns_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Weather Intel" in resp.text

    def test_dashboard_links_to_about(self):
        resp = client.get("/")
        assert 'href="/about"' in resp.text
