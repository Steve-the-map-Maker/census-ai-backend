"""Unit tests for the refine_dashboard_data utility."""

from copy import deepcopy

import pytest

from tools import refine_dashboard_data


@pytest.fixture()
def sample_payload():
    return {
        "type": "dashboard_data",
        "summary_text": "Sample dashboard",
        "metadata": {
            "geography_level": "county",
            "primary_variable_code": "B01003_001E",
        },
        "data": [
            {"NAME": "Alpha County", "year": 2020, "value": 100, "state": "01", "county": "001"},
            {"NAME": "Beta County", "year": 2020, "value": 200, "state": "01", "county": "003"},
            {"NAME": "Gamma County", "year": 2021, "value": 150, "state": "01", "county": "005"},
        ],
    }


def test_refine_applies_filters(sample_payload):
    refined = refine_dashboard_data(
        raw_payload=sample_payload,
        filters=[{"field": "NAME", "operator": "contains", "value": "Beta"}],
    )

    assert isinstance(refined, dict)
    assert len(refined["data"]) == 1
    assert refined["data"][0]["NAME"] == "Beta County"
    assert refined["metadata"].get("applied_filters")


def test_refine_applies_sort_and_limit(sample_payload):
    refined = refine_dashboard_data(
        raw_payload=sample_payload,
        sort={"field": "value", "direction": "desc"},
        limit=2,
    )

    names = [row["NAME"] for row in refined["data"]]
    assert names == ["Beta County", "Gamma County"]
    assert refined["metadata"].get("applied_limit") == 2
    assert refined["metadata"].get("applied_sort")


def test_refine_filters_by_year(sample_payload):
    refined = refine_dashboard_data(
        raw_payload=sample_payload,
        current_year=2021,
    )

    assert all(row["year"] == 2021 for row in refined["data"])
    assert refined["metadata"].get("active_year") == 2021


def test_refine_does_not_mutate_input(sample_payload):
    original = deepcopy(sample_payload)
    refine_dashboard_data(raw_payload=sample_payload, limit=1)
    assert sample_payload == original