import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import _compute_time_series_metrics, calculate_summary_statistics


def test_compute_time_series_metrics_basic_growth():
    values = [
        {"year": 2010, "value": 100.0},
        {"year": 2012, "value": 125.0},
    ]

    metrics = _compute_time_series_metrics(values)

    assert metrics["start_year"] == 2010
    assert metrics["end_year"] == 2012
    assert metrics["absolute_change"] == pytest.approx(25.0)
    assert metrics["percent_change"] == pytest.approx(25.0)
    assert metrics["cagr"] is not None
    assert metrics["max_point"]["year"] == 2012


def test_compute_time_series_metrics_handles_missing_values():
    values = [
        {"year": 2010, "value": None},
        {"year": 2011, "value": 90.0},
        {"year": 2012, "value": None},
        {"year": 2013, "value": 95.0},
    ]

    metrics = _compute_time_series_metrics(values)

    assert metrics["start_year"] == 2011
    assert metrics["end_year"] == 2013
    assert metrics["absolute_change"] == pytest.approx(5.0)
    assert metrics["percent_change"] == pytest.approx(5.5555, rel=1e-3)


def test_calculate_summary_statistics_returns_expected_values():
    data = [
        {"NAME": "Region A", "B01003_001E": "100"},
        {"NAME": "Region B", "B01003_001E": 150},
        {"NAME": "Region C", "B01003_001E": "200"},
    ]

    stats = calculate_summary_statistics(data, "B01003_001E")

    assert stats is not None
    assert stats["mean"] == pytest.approx(150.0)
    assert stats["median"] == pytest.approx(150.0)
    assert stats["min_entity_name"] == "Region A"
    assert stats["max_entity_name"] == "Region C"
