from scripts.generate_public_stats import build_stats, count_tests
from pathlib import Path


def test_build_stats_shape_and_values():
    stats = build_stats(
        companies_watched=29, ats_adapters=["lever", "greenhouse"], tests_passing=120,
        commit_sha="abc123", commit_date="2026-01-01T00:00:00+00:00",
        latest_release={"tag": "v0.1.0", "summary": "First release", "date": "2026-01-01"},
    )
    assert stats["companies_watched"] == 29
    assert stats["ats_adapters_supported"] == ["greenhouse", "lever"]
    assert stats["tests_passing"] == 120
    assert stats["latest_commit"] == {"sha": "abc123", "date": "2026-01-01T00:00:00+00:00"}
    assert stats["latest_release"]["tag"] == "v0.1.0"
    assert "generated_at" in stats


def test_build_stats_handles_no_release_yet():
    stats = build_stats(companies_watched=1, ats_adapters=[], tests_passing=1,
                         commit_sha="x", commit_date="x", latest_release=None)
    assert stats["latest_release"] is None


def test_build_stats_never_includes_personal_or_tracker_fields():
    stats = build_stats(companies_watched=1, ats_adapters=[], tests_passing=1,
                         commit_sha="x", commit_date="x")
    forbidden = {"applications", "ta_name", "ta_email", "ta_linkedin", "email", "phone",
                 "rejection_reason", "response_rate", "interview_conversion"}
    assert forbidden.isdisjoint(stats.keys())


def test_count_tests_counts_real_test_functions():
    tests_dir = Path(__file__).parent
    n = count_tests(tests_dir)
    # This file alone defines 4 test_* functions, and there are many more
    # test files in the suite - just confirm it's finding real ones.
    assert n >= 50
