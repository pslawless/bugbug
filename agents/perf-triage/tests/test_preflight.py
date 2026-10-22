from __future__ import annotations

import pytest
from hackbot_agents.perf_triage.preflight import profile_urls, write_mode


@pytest.mark.parametrize(
    "value,mode",
    [
        ("?", "full"),
        ("---", "full"),
        ("", "full"),
        (None, "full"),
        ("none", "comment_only"),
        ("low", "comment_only"),
        ("high", "comment_only"),
    ],
)
def test_write_mode(value, mode):
    assert write_mode({"cf_performance_impact": value}) == mode


def test_write_mode_missing_field_is_full():
    assert write_mode({}) == "full"


def test_profile_urls_found_in_url_field_then_comments():
    bug = {"url": "https://profiler.firefox.com/public/abc123/calltree/?v=10"}
    comments = ["see https://share.firefox.dev/44agmdV."]
    assert profile_urls(bug, comments) == [
        "https://profiler.firefox.com/public/abc123/calltree/?v=10",
        "https://share.firefox.dev/44agmdV",
    ]


def test_profile_urls_deduplicated():
    comments = ["https://share.firefox.dev/x1 and again https://share.firefox.dev/x1"]
    assert profile_urls({}, comments) == ["https://share.firefox.dev/x1"]


def test_from_url_profiles_count():
    comments = ["(https://profiler.firefox.com/from-url/https%3A%2F%2Fx/calltree)"]
    assert profile_urls({}, comments) == [
        "https://profiler.firefox.com/from-url/https%3A%2F%2Fx/calltree"
    ]


def test_profiler_home_page_is_not_a_profile():
    assert (
        profile_urls({}, ["capture one at https://profiler.firefox.com/ please"]) == []
    )


def test_no_profile():
    assert profile_urls({"url": "https://example.com/"}, ["no links here"]) == []
