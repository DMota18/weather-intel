"""Unit tests for the concrete work scoring engine."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from scoring import score_pour_hour, score_sealer_hour, score_cure_window, find_best_window, summarize_day


class TestPourScoring:
    def test_all_green(self):
        score, factors = score_pour_hour(temp_f=70, humidity_pct=50, wind_mph=5, precip_prob_pct=10, dewpoint_f=55)
        assert score == "green"
        assert all(v == "green" for v in factors.values())

    def test_boundary_temp_50_is_green(self):
        score, factors = score_pour_hour(temp_f=50, humidity_pct=50, wind_mph=5, precip_prob_pct=10)
        assert factors["temperature"] == "green"

    def test_boundary_temp_90_is_green(self):
        score, factors = score_pour_hour(temp_f=90, humidity_pct=50, wind_mph=5, precip_prob_pct=10)
        assert factors["temperature"] == "green"

    def test_boundary_temp_49_is_yellow(self):
        score, factors = score_pour_hour(temp_f=49, humidity_pct=50, wind_mph=5, precip_prob_pct=10)
        assert factors["temperature"] == "yellow"

    def test_boundary_temp_91_is_yellow(self):
        score, factors = score_pour_hour(temp_f=91, humidity_pct=50, wind_mph=5, precip_prob_pct=10)
        assert factors["temperature"] == "yellow"

    def test_boundary_temp_39_is_red(self):
        score, factors = score_pour_hour(temp_f=39, humidity_pct=50, wind_mph=5, precip_prob_pct=10)
        assert factors["temperature"] == "red"
        assert score == "red"

    def test_boundary_temp_96_is_red(self):
        score, factors = score_pour_hour(temp_f=96, humidity_pct=50, wind_mph=5, precip_prob_pct=10)
        assert factors["temperature"] == "red"

    def test_wind_boundaries(self):
        _, f1 = score_pour_hour(temp_f=70, humidity_pct=50, wind_mph=9.9, precip_prob_pct=10)
        assert f1["wind"] == "green"
        _, f2 = score_pour_hour(temp_f=70, humidity_pct=50, wind_mph=10, precip_prob_pct=10)
        assert f2["wind"] == "yellow"
        _, f3 = score_pour_hour(temp_f=70, humidity_pct=50, wind_mph=20, precip_prob_pct=10)
        assert f3["wind"] == "red"

    def test_precip_boundaries(self):
        _, f1 = score_pour_hour(temp_f=70, humidity_pct=50, wind_mph=5, precip_prob_pct=14)
        assert f1["precipitation"] == "green"
        _, f2 = score_pour_hour(temp_f=70, humidity_pct=50, wind_mph=5, precip_prob_pct=15)
        assert f2["precipitation"] == "yellow"
        _, f3 = score_pour_hour(temp_f=70, humidity_pct=50, wind_mph=5, precip_prob_pct=40)
        assert f3["precipitation"] == "red"

    def test_humidity_boundaries(self):
        _, f1 = score_pour_hour(temp_f=70, humidity_pct=25, wind_mph=5, precip_prob_pct=10)
        assert f1["humidity"] == "green"
        _, f2 = score_pour_hour(temp_f=70, humidity_pct=24, wind_mph=5, precip_prob_pct=10)
        assert f2["humidity"] == "yellow"
        _, f3 = score_pour_hour(temp_f=70, humidity_pct=14, wind_mph=5, precip_prob_pct=10)
        assert f3["humidity"] == "red"
        _, f4 = score_pour_hour(temp_f=70, humidity_pct=86, wind_mph=5, precip_prob_pct=10)
        assert f4["humidity"] == "red"

    def test_dewpoint_spread(self):
        _, f1 = score_pour_hour(temp_f=70, humidity_pct=50, wind_mph=5, precip_prob_pct=10, dewpoint_f=55)
        assert f1["dewpoint"] == "green"
        _, f2 = score_pour_hour(temp_f=70, humidity_pct=50, wind_mph=5, precip_prob_pct=10, dewpoint_f=63)
        assert f2["dewpoint"] == "yellow"
        _, f3 = score_pour_hour(temp_f=70, humidity_pct=50, wind_mph=5, precip_prob_pct=10, dewpoint_f=66)
        assert f3["dewpoint"] == "red"

    def test_single_red_makes_overall_red(self):
        score, _ = score_pour_hour(temp_f=30, humidity_pct=50, wind_mph=5, precip_prob_pct=10)
        assert score == "red"

    def test_single_yellow_no_red_makes_yellow(self):
        score, _ = score_pour_hour(temp_f=45, humidity_pct=50, wind_mph=5, precip_prob_pct=10)
        assert score == "yellow"

    def test_none_values_excluded(self):
        score, factors = score_pour_hour(temp_f=None, humidity_pct=None, wind_mph=None, precip_prob_pct=None)
        assert score is None
        assert factors == {}

    def test_partial_none_values_capped_at_yellow(self):
        # Missing inputs must never allow green — unknown is not safe
        score, factors = score_pour_hour(temp_f=70, humidity_pct=None, wind_mph=5, precip_prob_pct=None)
        assert "temperature" in factors
        assert "wind" in factors
        assert "humidity" not in factors
        assert "precipitation" not in factors
        assert factors["data"] == "yellow"
        assert score == "yellow"

    def test_partial_none_values_red_still_red(self):
        score, factors = score_pour_hour(temp_f=30, humidity_pct=None, wind_mph=5, precip_prob_pct=None)
        assert score == "red"

    def test_complete_inputs_have_no_data_factor(self):
        _, factors = score_pour_hour(temp_f=70, humidity_pct=50, wind_mph=5, precip_prob_pct=10, dewpoint_f=55)
        assert "data" not in factors


class TestSealerScoring:
    def test_safe_to_seal(self):
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0, precip_prob_next_24h=5, dewpoint_f=55)
        assert score == "green"

    def test_rain_last_24h_red(self):
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0.5, precip_prob_next_24h=5)
        assert factors["rain_last_24h"] == "red"
        assert score == "red"

    def test_rain_last_24h_trace_is_yellow(self):
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0.05, precip_prob_next_24h=5)
        assert factors["rain_last_24h"] == "yellow"

    def test_high_humidity_red(self):
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=90, precip_last_24h_in=0, precip_prob_next_24h=5)
        assert factors["humidity"] == "red"

    def test_cold_temp_red(self):
        score, factors = score_sealer_hour(temp_f=35, humidity_pct=50, precip_last_24h_in=0, precip_prob_next_24h=5)
        assert factors["temperature"] == "red"

    def test_rain_forecast_red(self):
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0, precip_prob_next_24h=50)
        assert factors["rain_next_24h"] == "red"

    def test_none_handling(self):
        score, factors = score_sealer_hour(temp_f=None, humidity_pct=None, precip_last_24h_in=None, precip_prob_next_24h=None)
        assert score is None

    def test_missing_input_capped_at_yellow(self):
        # Unknown last-24h rain must never allow a green sealer verdict
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=None, precip_prob_next_24h=5)
        assert factors["data"] == "yellow"
        assert score == "yellow"

    def test_trace_below_sensor_noise_is_green(self):
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0.003, precip_prob_next_24h=5)
        assert factors["rain_last_24h"] == "green"

    def test_measurable_trace_is_yellow(self):
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0.01, precip_prob_next_24h=5)
        assert factors["rain_last_24h"] == "yellow"


class TestCureWindow:
    def _hour(self, temp=70, prob=5, precip=0.0, wind=5):
        return {"temp_f": temp, "precip_prob_pct": prob, "precip_in": precip, "wind_mph": wind}

    def test_good_window_is_green(self):
        overall, factors, issues = score_cure_window([self._hour() for _ in range(48)])
        assert overall == "green"
        assert "data" not in factors

    def test_empty_forecast_returns_none(self):
        overall, _, _ = score_cure_window([])
        assert overall is None

    def test_all_null_hours_not_green(self):
        hours = [{"temp_f": None, "precip_prob_pct": None, "precip_in": None, "wind_mph": None}] * 48
        overall, factors, issues = score_cure_window(hours)
        assert overall is None
        assert issues

    def test_missing_wind_caps_at_yellow(self):
        hours = [dict(self._hour(), wind_mph=None) for _ in range(48)]
        overall, factors, _ = score_cure_window(hours)
        assert factors["data"] == "yellow"
        assert overall == "yellow"

    def test_missing_temps_caps_at_yellow(self):
        hours = [dict(self._hour(), temp_f=None) for _ in range(48)]
        overall, factors, _ = score_cure_window(hours)
        assert "freeze_risk" not in factors
        assert factors["data"] == "yellow"
        assert overall == "yellow"

    def test_freeze_is_red(self):
        overall, factors, issues = score_cure_window([self._hour(temp=35) for _ in range(48)])
        assert overall == "red"
        assert factors["freeze_risk"] == "red"

    def test_rain_first_24h_is_red(self):
        hours = [self._hour(prob=80) for _ in range(24)] + [self._hour() for _ in range(24)]
        overall, factors, _ = score_cure_window(hours)
        assert factors["rain_during_cure"] == "red"
        assert overall == "red"


class TestSummarizeDay:
    def _mk(self, pairs):
        return [{"hour": h, "pour_score": s} for h, s in pairs]

    def test_no_working_hours_returns_none(self):
        # Evening-only fragment — even all-red hours must yield "no data", never green
        day = self._mk([(h, "red") for h in range(18, 24)])
        assert summarize_day(day) is None

    def test_all_scores_missing_returns_none(self):
        day = self._mk([(h, None) for h in range(7, 18)])
        assert summarize_day(day) is None

    def test_full_green_day(self):
        day = self._mk([(h, "green") for h in range(7, 18)])
        assert summarize_day(day) == "green"

    def test_unscored_working_hour_caps_at_yellow(self):
        day = self._mk([(h, "green") for h in range(7, 17)] + [(17, None)])
        assert summarize_day(day) == "yellow"

    def test_any_red_wins(self):
        day = self._mk([(h, "green") for h in range(7, 17)] + [(17, "red")])
        assert summarize_day(day) == "red"

    def test_night_hours_ignored(self):
        day = self._mk([(3, "red"), (22, "red")] + [(h, "green") for h in range(7, 18)])
        assert summarize_day(day) == "green"


class TestBestWindow:
    def _make_hours(self, scores_by_hour):
        return [{"hour": h, "score": s} for h, s in scores_by_hour]

    def test_full_green_day(self):
        hours = self._make_hours([(h, "green") for h in range(7, 18)])
        result = find_best_window(hours)
        assert result == "07:00-17:00"

    def test_green_window_in_middle(self):
        hours = self._make_hours(
            [(6, "red"), (7, "red"), (8, "green"), (9, "green"), (10, "green"),
             (11, "red"), (12, "red")] + [(h, "red") for h in range(13, 20)]
        )
        result = find_best_window(hours)
        assert result == "08:00-11:00"

    def test_no_green_falls_back_to_yellow(self):
        hours = self._make_hours(
            [(6, "red"), (7, "yellow"), (8, "yellow"), (9, "yellow"),
             (10, "red")] + [(h, "red") for h in range(11, 20)]
        )
        result = find_best_window(hours)
        assert result == "07:00-10:00"

    def test_all_red_returns_none(self):
        hours = self._make_hours([(h, "red") for h in range(6, 20)])
        result = find_best_window(hours)
        assert result is None

    def test_ignores_hours_outside_work_window(self):
        hours = self._make_hours(
            [(3, "green"), (4, "green"), (5, "green"), (6, "green"),
             (7, "red")] + [(h, "red") for h in range(8, 18)]
        )
        result = find_best_window(hours)
        assert result is None

    def test_empty_input(self):
        result = find_best_window([])
        assert result is None
