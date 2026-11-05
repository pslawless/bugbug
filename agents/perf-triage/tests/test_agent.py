import tempfile
from pathlib import Path

from hackbot_agents.perf_triage.agent import run_perf_triage
from hackbot_agents.perf_triage.hooks import FEEDBACK_TAGS
from hackbot_agents.perf_triage.triage import TriageResult
from hackbot_runtime.actions import ActionsRecorder

BUG = 1839859
SEL = {
    "platforms": [
        "platform-windows",
        "platform-macos",
        "platform-linux",
        "platform-android",
    ],
    "browser": ["browser-minor"],
    "site": ["site-major"],
    "configuration": ["scenario-general"],
    "pageload": ["pageload-none"],
    "pages": ["pages-rare"],
    "resource": ["resource-none"],
    "reproducible": ["reproducible-reproduced"],
    "additional": [],
}


def triage(**kw) -> TriageResult:
    base = dict(
        impact="low",
        score=7.2,
        keywords=["perf:responsiveness", "reproducible"],
        severity="S3",
        comment="rated **low**",
        selections=SEL,
        unestablished=[],
    )
    base.update(kw)
    return TriageResult(**base)


async def run(
    result: TriageResult,
    *,
    impact="?",
    comments=(),
    url="",
    attachments=(),
    **extra,
):
    recorder = ActionsRecorder(artifacts_dir=Path(tempfile.mkdtemp()))
    seen: dict = {}

    async def fake_fetch_bug(_server, _bug):
        return {
            "id": BUG,
            "product": "Core",
            "component": "DOM: Core & HTML",
            "cf_performance_impact": impact,
            "keywords": [],
            "url": url,
        }

    async def fake_fetch_comments(_server, _bug):
        return list(comments)

    async def fake_fetch_attachments(_server, _bug):
        return list(attachments)

    async def fake_triage(profile_urls):
        seen["profile_urls"] = profile_urls
        return result

    findings = await run_perf_triage(
        bug_id=BUG,
        bugzilla_mcp_server={"type": "http", "url": "http://broker.invalid/mcp"},
        recorder=recorder,
        triage=fake_triage,
        fetch_bug=fake_fetch_bug,
        fetch_comments=fake_fetch_comments,
        fetch_attachments=fake_fetch_attachments,
        **extra,
    )
    return findings, recorder, seen


def types(recorder):
    return [a["type"] for a in recorder.actions]


async def test_failed_triage_records_nothing():
    f, r, _ = await run(
        triage(impact="none", score=0, comment="", failure_reason="no bug")
    )
    assert r.actions == []
    assert not f.auto_apply


async def test_full_mode_confident_records_both_and_auto_applies():
    f, r, _ = await run(triage())
    assert types(r) == ["bugzilla.add_comment", "bugzilla.update_bug"]
    assert r.actions[1]["params"]["changes"] == {
        "cf_performance_impact": "low",
        "keywords": {"add": ["perf:responsiveness", "reproducible"]},
    }
    assert f.auto_apply
    assert f.write_mode == "full"


async def test_comment_ends_with_reaction_footer_then_tags():
    _, r, _ = await run(triage())
    text = r.actions[0]["params"]["text"]
    assert "\n\n---\n\nIf you'd like to provide feedback" in text
    assert text.endswith(FEEDBACK_TAGS)
    assert text.count("👍 or 👎") == 1


async def test_no_keywords_omits_the_keywords_change():
    _, r, _ = await run(triage(keywords=[]))
    assert r.actions[1]["params"]["changes"] == {"cf_performance_impact": "low"}


async def test_unstable_records_but_holds():
    f, r, _ = await run(triage(unestablished=["pages-affected"]))
    assert len(r.actions) == 2
    assert not f.auto_apply
    assert f.stability["flipping"] == ["pages-affected"]


async def test_comment_only_agreement_records_nothing():
    f, r, _ = await run(triage(), impact="low")
    assert r.actions == []
    assert f.skipped_reason == "agrees with existing rating"
    assert not f.auto_apply


async def test_comment_only_disagreement_records_comment_only():
    f, r, _ = await run(triage(), impact="medium")
    assert types(r) == ["bugzilla.add_comment"]
    assert "Existing rating: **medium**" in r.actions[0]["params"]["text"]
    assert f.auto_apply


async def test_comment_only_unstable_disagreement_holds():
    f, r, _ = await run(triage(unestablished=["pages-affected"]), impact="medium")
    assert types(r) == ["bugzilla.add_comment"]
    assert not f.auto_apply


async def test_profile_urls_reach_triage():
    _, _, seen = await run(triage(), comments=["see https://share.firefox.dev/44agmdV"])
    assert seen["profile_urls"] == ["https://share.firefox.dev/44agmdV"]


async def test_no_profile_urls_when_none_linked():
    _, _, seen = await run(triage())
    assert seen["profile_urls"] == []


async def test_failed_bug_lookup_records_nothing_and_skips_triage():
    # A broker failure returns {}; that must not read as "unrated" and let a
    # confident run overwrite a rating a person already set.
    recorder = ActionsRecorder(artifacts_dir=Path(tempfile.mkdtemp()))
    called = []

    async def empty(_s, _b):
        return {}

    async def no_comments(_s, _b):
        return []

    async def fake_triage(urls):
        called.append(urls)
        return triage()

    f = await run_perf_triage(
        bug_id=BUG,
        bugzilla_mcp_server={},
        recorder=recorder,
        triage=fake_triage,
        fetch_bug=empty,
        fetch_comments=no_comments,
    )
    assert recorder.actions == []
    assert not f.auto_apply
    assert f.skipped_reason == "bug lookup failed"
    assert called == []


async def test_high_needinfos_the_reviewer():
    _, r, _ = await run(triage(impact="high", score=60, keywords=[]))
    assert r.actions[1]["params"]["changes"]["flags"] == [
        {"name": "needinfo", "status": "?", "requestee": "bas@basschouten.com"}
    ]


async def test_below_high_sets_no_flag():
    _, r, _ = await run(triage(impact="medium", score=30))
    assert "flags" not in r.actions[1]["params"]["changes"]


# --- root cause --------------------------------------------------------------- #

import json  # noqa: E402

import pytest  # noqa: E402
from hackbot_agents.perf_triage.rootcause import RootCauseResult  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "agents/perf-triage/tests/fixtures"
PROFILE = "https://share.firefox.dev/44agmdV"


def rc_fixture(name="bug-1933799-partial-component") -> RootCauseResult:
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    return RootCauseResult(**data["result"])


def fake_root_cause(result=None, error=None, seen=None):
    async def fn(profile_url, bug_summary, comments):
        if seen is not None:
            seen["rc_profile"] = profile_url
            seen["rc_comments"] = comments
        if error:
            raise error
        return result or rc_fixture()

    return fn


async def test_default_mode_runs_no_root_cause():
    seen: dict = {}
    f, r, _ = await run(
        triage(), comments=[PROFILE], root_cause=fake_root_cause(seen=seen)
    )
    assert types(r) == ["bugzilla.add_comment", "bugzilla.update_bug"]
    assert "rc_profile" not in seen
    assert f.root_cause is None


async def test_combined_mode_attaches_root_cause_after_the_triage_writes():
    f, r, _ = await run(
        triage(),
        comments=[PROFILE],
        mode="triage+root-cause",
        root_cause=fake_root_cause(),
    )
    assert types(r) == [
        "bugzilla.add_comment",
        "bugzilla.update_bug",
        "bugzilla.add_attachment",
    ]
    att = r.actions[2]
    assert att["params"]["file_name"] == f"root-cause-{BUG}.md"
    assert att["params"]["comment"].startswith("**Partial diagnosis**")
    assert f"attached as root-cause-{BUG}.md" in att["params"]["comment"]
    assert [a["name"] for a in att["attachments"]] == ["file"]
    assert f.root_cause.outcome == "partial"


async def test_root_cause_rides_a_confident_triage():
    """Patricia, 2026-11-04: do not hold a confident rating for the analysis."""
    f, _, _ = await run(
        triage(),
        comments=[PROFILE],
        mode="triage+root-cause",
        root_cause=fake_root_cause(rc_fixture("bug-1931896-partial-no-component")),
    )
    assert f.auto_apply


async def test_root_cause_does_not_lift_an_unstable_triage():
    f, r, _ = await run(
        triage(unestablished=["pages-affected"]),
        comments=[PROFILE],
        mode="triage+root-cause",
        root_cause=fake_root_cause(),
    )
    assert "bugzilla.add_attachment" in types(r)
    assert not f.auto_apply


async def test_root_cause_uses_the_profile_triage_analysed():
    seen: dict = {}
    await run(
        triage(profile={"url": "https://share.firefox.dev/second", "analysed": True}),
        comments=[PROFILE, "and https://share.firefox.dev/second"],
        mode="triage+root-cause",
        root_cause=fake_root_cause(seen=seen),
    )
    assert seen["rc_profile"] == "https://share.firefox.dev/second"


async def test_no_profile_skips_root_cause_and_keeps_triage():
    f, r, _ = await run(
        triage(), mode="triage+root-cause", root_cause=fake_root_cause()
    )
    assert types(r) == ["bugzilla.add_comment", "bugzilla.update_bug"]
    assert f.root_cause_skipped == "no profile linked"
    assert f.auto_apply


async def test_a_failed_root_cause_keeps_triage():
    f, r, _ = await run(
        triage(),
        comments=[PROFILE],
        mode="triage+root-cause",
        root_cause=fake_root_cause(error=RuntimeError("profile expired")),
    )
    assert types(r) == ["bugzilla.add_comment", "bugzilla.update_bug"]
    assert "profile expired" in f.root_cause_skipped
    assert f.auto_apply


async def test_root_cause_only_mode_never_triages_and_is_held():
    async def no_triage(_urls):
        raise AssertionError("triage must not run")

    recorder = ActionsRecorder(artifacts_dir=Path(tempfile.mkdtemp()))

    async def bug(_s, _b):
        return {"id": BUG, "cf_performance_impact": "?", "summary": "slow"}

    async def empty(_s, _b):
        return []

    async def comments(_s, _b):
        return [PROFILE]

    f = await run_perf_triage(
        bug_id=BUG,
        bugzilla_mcp_server={"type": "http", "url": "http://broker.invalid/mcp"},
        recorder=recorder,
        triage=no_triage,
        mode="root-cause",
        root_cause=fake_root_cause(),
        fetch_bug=bug,
        fetch_comments=comments,
        fetch_attachments=empty,
    )
    assert types(recorder) == ["bugzilla.add_attachment"]
    assert f.triage is None
    assert not f.auto_apply


async def test_root_cause_only_mode_refuses_rating_writes():
    from agent_tools.registry import ToolError

    recorder = ActionsRecorder(artifacts_dir=Path(tempfile.mkdtemp()))

    async def bug(_s, _b):
        return {"id": BUG, "cf_performance_impact": "?"}

    async def none(_s, _b):
        return []

    await run_perf_triage(
        bug_id=BUG,
        bugzilla_mcp_server={"type": "http", "url": "http://broker.invalid/mcp"},
        recorder=recorder,
        triage=None,
        mode="root-cause",
        root_cause=fake_root_cause(),
        fetch_bug=bug,
        fetch_comments=none,
        fetch_attachments=none,
    )
    for action_type, params in [
        (
            "bugzilla.update_bug",
            {"bug_id": BUG, "changes": {"cf_performance_impact": "low"}},
        ),
        ("bugzilla.add_comment", {"bug_id": BUG, "text": "x", "is_private": False}),
    ]:
        with pytest.raises(ToolError):
            recorder.record(action_type, params)


async def test_a_root_cause_mode_without_a_function_is_an_error():
    with pytest.raises(ValueError):
        await run(triage(), mode="triage+root-cause")


PROFILED = dict(
    profile={
        "url": PROFILE,
        "analysed": True,
        "summary": "MINI-DIAGNOSIS of the hot path",
        "component": "Core :: Graphics",
        "changed_attributes": {"browser": "browser-jank"},
    },
)


def _move(basis):
    return {
        "action": "move",
        "name": "Core :: Graphics",
        "basis": basis,
        "verified": True,
    }


async def test_triage_comment_defers_the_profile_to_root_cause():
    """Patricia, 2026-11-04: one diagnosis on the bug, the root cause's."""
    _, r, _ = await run(
        triage(**PROFILED, component=_move("profile")),
        comments=[PROFILE],
        mode="triage+root-cause",
        root_cause=fake_root_cause(),
    )
    text = r.actions[0]["params"]["text"]
    assert "MINI-DIAGNOSIS" not in text
    assert "Suggested component" not in text
    assert f"posted with root-cause-{BUG}.md" in text
    assert "The profile changed:" in text  # still explains the rating


async def test_a_memory_report_component_move_is_kept():
    """Root cause reads the profile, not the memory report."""
    _, r, _ = await run(
        triage(**PROFILED, component=_move("memory_report")),
        comments=[PROFILE],
        mode="triage+root-cause",
        root_cause=fake_root_cause(),
    )
    assert "Suggested component: Core :: Graphics" in r.actions[0]["params"]["text"]


async def test_triage_keeps_its_profile_paragraph_when_root_cause_fails():
    _, r, _ = await run(
        triage(**PROFILED, component=_move("profile")),
        comments=[PROFILE],
        mode="triage+root-cause",
        root_cause=fake_root_cause(error=RuntimeError("expired")),
    )
    text = r.actions[0]["params"]["text"]
    assert "MINI-DIAGNOSIS" in text
    assert "Suggested component: Core :: Graphics" in text


async def test_triage_only_mode_keeps_its_profile_paragraph():
    _, r, _ = await run(triage(**PROFILED), comments=[PROFILE])
    assert "MINI-DIAGNOSIS" in r.actions[0]["params"]["text"]


async def test_root_cause_gets_the_bugs_comments():
    seen: dict = {}
    await run(
        triage(),
        comments=["slow on amazon " + PROFILE, "QuotaManager init, see bug 1671932"],
        mode="triage+root-cause",
        root_cause=fake_root_cause(seen=seen),
    )
    assert seen["rc_comments"][1] == "QuotaManager init, see bug 1671932"
