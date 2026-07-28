"""Unit tests for NWS alert filtering and parsing (no network)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from weather_client import alert_is_relevant, parse_alerts


def _feature(event="", headline="", severity="Moderate"):
    return {"properties": {
        "event": event, "headline": headline, "severity": severity,
        "urgency": "Expected", "areaDesc": "Worcester County",
        "onset": "2026-07-16T12:00:00-04:00", "expires": "2026-07-16T20:00:00-04:00",
        "description": "x" * 500,
    }}


class TestAlertRelevance:
    def test_tornado_warning_is_relevant(self):
        # The old inline keyword list missed tornadoes entirely
        assert alert_is_relevant(_feature(event="Tornado Warning", severity="Extreme")["properties"])
        assert alert_is_relevant(_feature(event="Tornado Watch", severity="Moderate")["properties"])

    def test_excessive_heat_is_relevant(self):
        assert alert_is_relevant(_feature(event="Excessive Heat Warning", severity="Moderate")["properties"])

    def test_severe_severity_always_passes(self):
        assert alert_is_relevant(_feature(event="Special Weather Statement", severity="Severe")["properties"])

    def test_freeze_and_wind_still_pass(self):
        assert alert_is_relevant(_feature(event="Freeze Warning")["properties"])
        assert alert_is_relevant(_feature(event="High Wind Advisory")["properties"])

    def test_irrelevant_alert_filtered(self):
        assert not alert_is_relevant(_feature(event="Rip Current Statement", severity="Minor")["properties"])

    def test_missing_fields_do_not_crash(self):
        assert alert_is_relevant({"severity": None, "event": None, "headline": None}) is False


class TestParseAlerts:
    def test_sorted_most_severe_first(self):
        feats = [
            _feature(event="Wind Advisory", severity="Minor"),
            _feature(event="Tornado Warning", severity="Extreme"),
            _feature(event="Severe Thunderstorm Warning", severity="Severe"),
        ]
        alerts = parse_alerts(feats)
        assert [a["severity"] for a in alerts] == ["Extreme", "Severe", "Minor"]

    def test_description_truncated(self):
        alerts = parse_alerts([_feature(event="Freeze Warning")])
        assert len(alerts[0]["description"]) <= 300

    def test_irrelevant_dropped(self):
        alerts = parse_alerts([_feature(event="Rip Current Statement", severity="Minor")])
        assert alerts == []

    def test_empty_input(self):
        assert parse_alerts([]) == []
