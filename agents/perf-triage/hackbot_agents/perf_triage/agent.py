"""One run: preflight, triage, stability check, optional root cause, then the writes.

The model makes the triage skill's judgement and, when asked, the root-cause
analysis. Everything that decides what reaches the bug is code: the write mode
(preflight), whether the rating is stable enough to apply unattended (the
calculator re-scored over the inputs the bug left open), and the comment text.
hackbot-api applies the recorded actions only when ``auto_apply`` is true;
otherwise they wait for a person.

Root cause rides the triage verdict. ``auto_apply`` is one flag per run, and a
rating that held should not wait on a profile analysis that found nothing
(Patricia, 2026-11-04). The root-cause comment carries its own confidence, and
a low-confidence analysis posts as "inconclusive" with the leads attached.
"""

import logging
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from claude_agent_sdk import McpServerConfig
from hackbot_agents.perf_triage.rootcause import RootCauseResult
from hackbot_agents.perf_triage.rootcause.comment import (
    render_root_cause_comment,
    render_root_cause_full,
)
from hackbot_agents.perf_triage.triage import TriageResult
from hackbot_agents.perf_triage.triage.stability import check_stability
from hackbot_runtime import HackbotAgentResult
from hackbot_runtime.actions import ActionsRecorder, bugzilla

from . import preflight
from .comment import render_comment
from .hooks import (
    REVIEW_FLAGS,
    ROOT_CAUSE_CONTENT_TYPE,
    add_attachment_hook,
    add_comment_hook,
    feedback_tags_hook,
    refuse_hook,
    root_cause_file_name,
    update_bug_hook,
)
from .preflight import WriteMode

logger = logging.getLogger("perf-triage")

Mode = Literal["triage", "triage+root-cause", "root-cause"]
TriageFn = Callable[[list[str]], Awaitable[TriageResult]]
# (profile_url, bug_summary) -> result
RootCauseFn = Callable[[str, str | None], Awaitable[RootCauseResult]]


class PerfTriageFindings(HackbotAgentResult):
    mode: Mode = "triage"
    triage: TriageResult | None = None
    stability: dict | None = None
    write_mode: WriteMode = "full"
    skipped_reason: str | None = None
    root_cause: RootCauseResult | None = None
    root_cause_skipped: str | None = None
    # This run's verdict on whether its recorded actions may reach the bug with
    # nobody in between. hackbot-api reads it as findings.auto_apply.
    auto_apply: bool = False


def _profile_for_root_cause(result: TriageResult | None, urls: list[str]) -> str | None:
    """The profile triage analysed, else the first one the bug links."""
    profile = result.profile if result else None
    if profile and profile.analysed:
        if profile.url:
            return profile.url
        if profile.attachment:
            return preflight.ATTACHMENT_URL.format(profile.attachment)
    return urls[0] if urls else None


async def _analyse(
    bug_id: int, bug: dict, profile_url: str | None, root_cause: RootCauseFn
) -> tuple[RootCauseResult | None, str | None]:
    """Run the analysis; a failure is a skip reason, never a failed run."""
    if not profile_url:
        return None, "no profile linked"
    try:
        return await root_cause(profile_url, bug.get("summary")), None
    except Exception as exc:  # a failed analysis must not cost the triage
        logger.exception("root cause failed for bug %s", bug_id)
        return None, f"root cause failed: {exc}"


def _record_root_cause(
    recorder: ActionsRecorder,
    bug_id: int,
    rc: RootCauseResult,
    profile_url: str,
    current_component: str,
) -> None:
    name = root_cause_file_name(bug_id)
    path = Path(tempfile.mkdtemp(prefix="perf-root-cause-")) / name
    path.write_text(render_root_cause_full(rc, profile_url=profile_url))
    recorder.record(
        "bugzilla.add_attachment",
        {
            "bug_id": bug_id,
            "file_name": name,
            "summary": "Automated profile analysis",
            "content_type": ROOT_CAUSE_CONTENT_TYPE,
            "is_patch": False,
            # Posted with the file, so the pointer in it cannot dangle.
            "comment": render_root_cause_comment(
                rc,
                current_component=current_component,
                profile_url=profile_url,
                attachment_name=name,
            ),
        },
        reasoning=f"Profile analysis: {rc.outcome} ({rc.confidence})",
        attachments={"file": path},
    )


async def run_perf_triage(
    *,
    bug_id: int,
    bugzilla_mcp_server: McpServerConfig,
    recorder: ActionsRecorder,
    triage: TriageFn,
    mode: Mode = "triage",
    root_cause: RootCauseFn | None = None,
    fetch_bug=preflight.fetch_bug,
    fetch_comments=preflight.fetch_comments,
    fetch_attachments=preflight.fetch_attachments,
    num_turns: Callable[[], int] = lambda: 0,
    total_cost_usd: Callable[[], float | None] = lambda: None,
) -> PerfTriageFindings:
    if mode != "triage" and root_cause is None:
        raise ValueError(f"mode {mode!r} needs a root_cause function")

    bug = await fetch_bug(bugzilla_mcp_server, bug_id)
    # Fail closed: preflight returns {} on a broker failure, and an empty bug
    # would read as unrated -- letting a confident run overwrite a person's rating.
    if bug.get("id") != bug_id or "cf_performance_impact" not in bug:
        return PerfTriageFindings(
            mode=mode, num_turns=0, skipped_reason="bug lookup failed"
        )
    comments = await fetch_comments(bugzilla_mcp_server, bug_id)
    write_mode = preflight.write_mode(bug)
    existing = bug.get("cf_performance_impact")
    current = f"{bug.get('product', '')} :: {bug.get('component', '')}"

    if mode == "root-cause":
        # No rating, no triage comment: refused at record time, not just unwritten.
        recorder.add_hook(
            "bugzilla.add_comment",
            refuse_hook("root-cause mode posts no triage comment"),
        )
        recorder.add_hook(
            "bugzilla.update_bug", refuse_hook("root-cause mode never rates the bug")
        )
    else:
        recorder.add_hook("bugzilla.add_comment", add_comment_hook(recorder, bug_id))
        recorder.add_hook("bugzilla.add_comment", feedback_tags_hook)
        recorder.add_hook(
            "bugzilla.update_bug", update_bug_hook(recorder, bug_id, write_mode)
        )
    if mode != "triage":
        recorder.add_hook(
            "bugzilla.add_attachment", add_attachment_hook(recorder, bug_id)
        )

    attachments = await fetch_attachments(bugzilla_mcp_server, bug_id)
    urls = preflight.profile_urls(bug, comments, attachments)

    if mode == "root-cause":
        assert root_cause is not None
        profile_url = _profile_for_root_cause(None, urls)
        rc, rc_skipped = await _analyse(bug_id, bug, profile_url, root_cause)
        if rc is not None and profile_url:
            _record_root_cause(recorder, bug_id, rc, profile_url, current)
        # Nothing here was gated by a stable rating, so a person applies it.
        return PerfTriageFindings(
            mode=mode,
            num_turns=num_turns(),
            total_cost_usd=total_cost_usd(),
            write_mode=write_mode,
            root_cause=rc,
            root_cause_skipped=rc_skipped,
            skipped_reason=rc_skipped,
        )

    result = await triage(urls)

    def findings(**kw) -> PerfTriageFindings:
        return PerfTriageFindings(
            mode=mode,
            num_turns=num_turns(),
            total_cost_usd=total_cost_usd(),
            triage=result,
            write_mode=write_mode,
            **kw,
        )

    if not result.ok:
        return findings(skipped_reason=f"triage failed: {result.failure_reason}")

    stability = check_stability(result.selections, result.unestablished)
    stability_dict = {
        "confident": stability.confident,
        "bands": sorted(stability.bands),
        "flipping": list(stability.flipping),
        "unknown": list(stability.unknown),
    }

    # Analyse before writing the triage comment: when the analysis succeeds the
    # triage comment drops its own profile paragraph and component suggestion
    # and defers to it (Patricia, 2026-11-04), so the bug gets one diagnosis.
    rc, rc_skipped, rc_profile = None, None, None
    if mode == "triage+root-cause":
        assert root_cause is not None
        rc_profile = _profile_for_root_cause(result, urls)
        rc, rc_skipped = await _analyse(bug_id, bug, rc_profile, root_cause)

    skipped_reason = None
    auto_apply = False
    if write_mode == "comment_only" and result.impact == existing:
        skipped_reason = "agrees with existing rating"
    else:
        text = render_comment(
            result,
            stability,
            write_mode,
            current_component=current,
            existing_impact=existing,
            profile_deferred_to=root_cause_file_name(bug_id) if rc else None,
        )
        await bugzilla.add_comment(
            recorder,
            bug_id=bug_id,
            text=text,
            reasoning=f"Performance triage: {result.impact} ({result.score})",
        )
        if write_mode == "full":
            changes: dict = {"cf_performance_impact": result.impact}
            if result.keywords:
                changes["keywords"] = {"add": list(result.keywords)}
            if result.impact == "high":
                changes["flags"] = REVIEW_FLAGS
            await bugzilla.update_bug(
                recorder,
                bug_id=bug_id,
                changes=changes,
                reasoning="Set from the triage calculator's rating and keywords",
            )
        auto_apply = stability.confident

    if rc is not None and rc_profile:
        _record_root_cause(recorder, bug_id, rc, rc_profile, current)

    return findings(
        stability=stability_dict,
        skipped_reason=skipped_reason,
        root_cause=rc,
        root_cause_skipped=rc_skipped,
        auto_apply=auto_apply,
    )
