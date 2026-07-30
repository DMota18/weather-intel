"""Unit tests for the concrete work scoring engine."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from scoring import (
    score_pour_hour, score_sealer_hour, score_cure_window, find_best_window,
    summarize_day, explain_pour_day, explain_sealer, _span_phrase, _clock,
)


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
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0, precip_prob_next_24h=5,
                                           dewpoint_f=55, wind_mph=5, min_temp_next_12h=60)
        assert score == "green"
        assert "data" not in factors

    def test_missing_wind_or_cure_temp_blocks_green(self):
        # Green requires the full picture — omitting wind or the overnight low caps at yellow
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0, precip_prob_next_24h=5,
                                           dewpoint_f=55)
        assert factors["data"] == "yellow"
        assert score == "yellow"

    def test_cold_night_after_warm_afternoon_is_red(self):
        # 70°F at application time must not hide a 35°F night — sealer cures overnight
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0, precip_prob_next_24h=5,
                                           dewpoint_f=55, wind_mph=5, min_temp_next_12h=35)
        assert factors["cure_temp"] == "red"
        assert score == "red"

    def test_cool_night_is_yellow(self):
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0, precip_prob_next_24h=5,
                                           dewpoint_f=55, wind_mph=5, min_temp_next_12h=45)
        assert factors["cure_temp"] == "yellow"

    def test_high_wind_is_red(self):
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0, precip_prob_next_24h=5,
                                           dewpoint_f=55, wind_mph=18, min_temp_next_12h=60)
        assert factors["wind"] == "red"
        assert score == "red"

    def test_moderate_wind_is_yellow(self):
        score, factors = score_sealer_hour(temp_f=70, humidity_pct=50, precip_last_24h_in=0, precip_prob_next_24h=5,
                                           dewpoint_f=55, wind_mph=12, min_temp_next_12h=60)
        assert factors["wind"] == "yellow"

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

    def test_gusts_scored_even_when_sustained_is_calm(self):
        # 10mph sustained but 40mph gusts — gusts drive shrinkage cracking
        hours = [dict(self._hour(wind=10), wind_gust_mph=40) for _ in range(48)]
        overall, factors, issues = score_cure_window(hours)
        assert factors["wind_drying"] == "red"
        assert any("gust" in i.lower() for i in issues)

    def test_moderate_gusts_yellow(self):
        hours = [dict(self._hour(wind=10), wind_gust_mph=28) for _ in range(48)]
        _, factors, _ = score_cure_window(hours)
        assert factors["wind_drying"] == "yellow"


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
        day = self._mk([(h, "green") for h in range(7, 16)] + [(16, None)])
        assert summarize_day(day) == "yellow"

    def test_any_red_wins(self):
        day = self._mk([(h, "green") for h in range(7, 16)] + [(16, "red")])
        assert summarize_day(day) == "red"

    def test_hour_17_outside_working_window(self):
        # Working day is 7AM–5PM: hour 17 (5–6PM) matches find_best_window's exclusion
        day = self._mk([(h, "green") for h in range(7, 17)] + [(17, "red")])
        assert summarize_day(day) == "green"

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


class TestClockAndSpans:
    def test_clock_formats(self):
        assert _clock(0) == "12am"
        assert _clock(7) == "7am"
        assert _clock(12) == "12pm"
        assert _clock(13) == "1pm"
        assert _clock(23) == "11pm"

    def test_span_all_day(self):
        assert _span_phrase(list(range(7, 17)), 7, 17) == "all day"

    def test_span_before(self):
        assert _span_phrase([7, 8, 9], 7, 17) == "before 10am"

    def test_span_after(self):
        assert _span_phrase([14, 15, 16], 7, 17) == "after 2pm"

    def test_span_middle_range(self):
        assert _span_phrase([10, 11, 12, 13], 7, 17) == "10am-2pm"

    def test_span_scattered_few(self):
        assert _span_phrase([8, 12, 15], 7, 17) == "8am, 12pm, 3pm"

    def test_span_scattered_many(self):
        assert "on and off" in _span_phrase([8, 10, 12, 14, 16], 7, 17)

    def test_span_empty(self):
        assert _span_phrase([], 7, 17) == ""


class TestExplainPourDay:
    def _day(self, per_hour):
        """per_hour: {hour: (temp, humidity, wind, precip_prob)}"""
        out = []
        for hr, (t, hum, w, p) in sorted(per_hour.items()):
            score, factors = score_pour_hour(t, hum, w, p)
            out.append({"hour": hr, "temp_f": t, "humidity_pct": hum, "wind_mph": w,
                        "precip_prob_pct": p, "pour_score": score, "pour_factors": factors})
        return out

    def _good(self):
        return {h: (72, 50, 5, 5) for h in range(7, 17)}

    def test_clear_day_has_no_reasons(self):
        assert explain_pour_day(self._day(self._good())) == []

    def test_afternoon_rain_named_with_window(self):
        spec = self._good()
        for h in range(12, 17):
            spec[h] = (70, 60, 8, 70)
        reasons = explain_pour_day(self._day(spec))
        assert "Rain likely" in reasons[0]
        assert "70%" in reasons[0]
        assert "after 12pm" in reasons[0]

    def test_red_factor_outranks_yellow_factor(self):
        # Cold morning (yellow) + high wind (red): the red must lead, because
        # compact views show only the first reason and it must explain the verdict
        spec = self._good()
        for h in range(7, 10):
            spec[h] = (42, 55, 7, 5)
        for h in range(14, 17):
            spec[h] = (72, 50, 24, 5)
        reasons = explain_pour_day(self._day(spec))
        assert "High wind" in reasons[0]
        assert any("Cold" in r for r in reasons)

    def test_cold_and_hot_read_differently(self):
        cold = explain_pour_day(self._day({h: (35, 50, 5, 5) for h in range(7, 17)}))
        hot = explain_pour_day(self._day({h: (98, 40, 5, 5) for h in range(7, 17)}))
        assert "Too cold" in cold[0] and "35" in cold[0]
        assert "Too hot" in hot[0] and "98" in hot[0]

    def test_no_working_hours_says_no_go(self):
        evening = self._day({h: (70, 50, 5, 90) for h in range(18, 24)})
        reasons = explain_pour_day(evening)
        assert len(reasons) == 1
        assert "no-go" in reasons[0]

    def test_unscorable_hours_says_no_go(self):
        hours = [{"hour": h, "temp_f": None, "humidity_pct": None, "wind_mph": None,
                  "precip_prob_pct": None, "pour_score": None, "pour_factors": {}}
                 for h in range(7, 17)]
        assert "no-go" in explain_pour_day(hours)[0]

    def test_missing_data_reported(self):
        spec = self._good()
        hours = self._day(spec)
        hours[3] = {**hours[3], "pour_score": None, "pour_factors": {}}
        reasons = explain_pour_day(hours)
        assert any("Missing data" in r for r in reasons)

    def test_hour_17_not_described(self):
        # 5PM is outside the working window; a red 5pm must not generate a reason
        spec = self._good()
        spec[17] = (70, 50, 5, 95)
        assert explain_pour_day(self._day(spec)) == []


class TestExplainSealer:
    def test_wet_slab_leads_with_amount(self):
        _, factors = score_sealer_hour(70, 50, 0.42, 5, 50, 5, 60)
        reasons = explain_sealer(factors, 0.42, 5, 60, {"temp_f": 70, "humidity_pct": 50, "wind_mph": 5, "dewpoint_f": 50})
        assert "0.42" in reasons[0]
        assert "dry" in reasons[0]

    def test_cold_night_explained(self):
        _, factors = score_sealer_hour(70, 50, 0, 5, 50, 5, 34)
        reasons = explain_sealer(factors, 0, 5, 34, {"temp_f": 70, "humidity_pct": 50, "wind_mph": 5, "dewpoint_f": 50})
        assert any("overnight" in r and "34" in r for r in reasons)

    def test_wind_explained_with_consequence(self):
        _, factors = score_sealer_hour(70, 50, 0, 5, 50, 19, 60)
        reasons = explain_sealer(factors, 0, 5, 60, {"temp_f": 70, "humidity_pct": 50, "wind_mph": 19, "dewpoint_f": 50})
        assert any("windy" in r.lower() for r in reasons)

    def test_clear_conditions_no_reasons(self):
        _, factors = score_sealer_hour(72, 45, 0, 5, 50, 4, 62)
        assert explain_sealer(factors, 0, 5, 62, {"temp_f": 72, "humidity_pct": 45, "wind_mph": 4, "dewpoint_f": 50}) == []

    def test_missing_data_surfaced(self):
        _, factors = score_sealer_hour(70, 50, None, 5, 50, 5, 60)
        reasons = explain_sealer(factors, None, 5, 60, {"temp_f": 70, "humidity_pct": 50, "wind_mph": 5, "dewpoint_f": 50})
        assert any("unavailable" in r for r in reasons)

    def test_no_crash_on_empty_current(self):
        _, factors = score_sealer_hour(None, None, None, None, None, None, None)
        assert explain_sealer(factors or {}, None, None, None, None) == []
