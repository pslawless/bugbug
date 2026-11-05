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


def test_a_comment_profile_is_newer_than_the_url_field():
    bug = {"url": "https://profiler.firefox.com/public/abc123/calltree/?v=10"}
    comments = ["see https://share.firefox.dev/44agmdV."]
    assert profile_urls(bug, comments) == [
        "https://share.firefox.dev/44agmdV",
        "https://profiler.firefox.com/public/abc123/calltree/?v=10",
    ]


def test_later_comments_come_first():
    """The newest profile is usually the most representative (Patricia, 2026-11-05)."""
    comments = ["old https://share.firefox.dev/a", "new https://share.firefox.dev/b"]
    assert profile_urls({}, comments) == [
        "https://share.firefox.dev/b",
        "https://share.firefox.dev/a",
    ]


def test_a_repeated_link_keeps_its_first_appearance():
    comments = [
        "https://share.firefox.dev/a",
        "https://share.firefox.dev/b",
        "as in https://share.firefox.dev/a",
    ]
    assert profile_urls({}, comments)[0] == "https://share.firefox.dev/b"


def test_attachments_and_comments_interleave_by_time():
    comments = [
        {
            "text": "https://share.firefox.dev/a",
            "creation_time": "2024-01-01T00:00:00Z",
        },
        {
            "text": "https://share.firefox.dev/c",
            "creation_time": "2024-03-01T00:00:00Z",
        },
    ]
    atts = [_att(9, "profile.json.gz", creation_time="2024-02-01T00:00:00Z")]
    assert profile_urls({}, comments, atts) == [
        "https://share.firefox.dev/c",
        "https://bugzilla.mozilla.org/attachment.cgi?id=9",
        "https://share.firefox.dev/a",
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


def _att(id, name, **kw):
    return {"id": id, "file_name": name, "is_obsolete": 0, "is_private": 0, **kw}


def test_an_untimed_attached_profile_counts_after_the_comments():
    # Bug 2086588: a screenshot, an about:memory report and a profile, all
    # but the screenshot application/gzip.
    atts = [
        _att(1, "Screenshot_20261028_150619.png"),
        _att(2, "memory-report.json.gz"),
        _att(3, "Firefox-2026-10-28-15.03-profile.json.gz"),
    ]
    assert profile_urls({}, ["https://share.firefox.dev/x1"], atts) == [
        "https://bugzilla.mozilla.org/attachment.cgi?id=3",
        "https://share.firefox.dev/x1",
    ]


def test_obsolete_and_private_profiles_skipped():
    atts = [
        _att(1, "profile.json.gz", is_obsolete=1),
        _att(2, "profile.json", is_private=1),
    ]
    assert profile_urls({}, [], atts) == []
