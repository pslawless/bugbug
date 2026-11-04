"""Root-cause analysis (step 4): the result schema, the prompt, and the task.

Two things are load-bearing here and both are tested rather than trusted.

The SCHEMA has to make ``inconclusive`` cheap to say. An analysis that cannot
name a hot path must not be able to name one anyway, so the model validator
refuses a ``hot_path`` on an inconclusive result. That mirrors ``declined`` in
the generation agent, which produced the most valuable single output across
three pilots precisely because saying "no" was a first-class answer.

The PROMPT has to keep the profile primary. The scale bands are a second lens
that WIDENS what gets considered; phrased as "therefore" they would become a
rule that talks the model out of investigating what the profile plainly shows.
The tests below pin the "also consider" phrasing and the absence of "therefore"
because that distinction is the whole point of the guidance.
"""

from pathlib import Path

import pytest
from hackbot_agents.perf_triage.rootcause import (
    ROOT_CAUSE_TASK_DETAILS,
    RootCause,
    RootCauseResult,
    reference_points,
)
from hackbot_agents.perf_triage.tasks import RunTracker, TaskConfig
from pydantic import ValidationError


def _diagnosed(**overrides):
    base = dict(
        outcome="diagnosed",
        summary="Main thread spends 82% of samples decoding the hero image.",
        hot_path="mozilla::image::Decoder::Decode",
        component="Core :: ImageLib",
        headline="The main thread is busy decoding the hero image.",
        key_figures=["4100 of 5000 main-thread samples (82%) in Decoder::Decode"],
        main_limitation="Does not establish why the decode is synchronous.",
        evidence="4100 of 5000 main-thread samples; DecodeImage marker 1.2s.",
        confidence="high",
        caveats="Does not establish why the decode is synchronous.",
    )
    base.update(overrides)
    return base


# --- the result schema ---------------------------------------------------- #


@pytest.mark.parametrize("outcome", ["diagnosed", "partial", "inconclusive"])
def test_the_three_outcomes_validate(outcome):
    """All three are legitimate endings, not two endings and a failure."""
    kwargs = _diagnosed(outcome=outcome)
    if outcome == "inconclusive":
        kwargs["hot_path"] = None
        kwargs["component"] = None
    result = RootCauseResult(**kwargs)
    assert result.outcome == outcome


def test_an_unknown_outcome_is_rejected():
    with pytest.raises(ValidationError):
        RootCauseResult(**_diagnosed(outcome="fixed"))


def test_inconclusive_must_not_name_a_hot_path():
    """The point of `inconclusive` is that the evidence did not get there.

    Allowing a hot_path alongside it would let the model hedge the outcome
    while still handing a downstream reader something that looks like an
    answer -- which is exactly the plausible-story failure this outcome
    exists to prevent.
    """
    with pytest.raises(ValidationError, match="hot_path"):
        RootCauseResult(**_diagnosed(outcome="inconclusive"))


def test_inconclusive_with_no_hot_path_is_accepted():
    result = RootCauseResult(
        **_diagnosed(outcome="inconclusive", hot_path=None, component=None)
    )
    assert result.hot_path is None
    assert result.outcome == "inconclusive"


def test_a_diagnosed_result_must_name_a_hot_path():
    """A diagnosis with no hot path is a summary, not a diagnosis."""
    with pytest.raises(ValidationError, match="hot_path"):
        RootCauseResult(**_diagnosed(outcome="diagnosed", hot_path=None))


def test_evidence_must_not_be_empty():
    """Unquantified evidence is the failure mode the skill warns about."""
    with pytest.raises(ValidationError, match="evidence"):
        RootCauseResult(**_diagnosed(evidence="   "))


def test_component_is_optional():
    """A profile often shows where time goes without naming an owner."""
    result = RootCauseResult(**_diagnosed(component=None))
    assert result.component is None


def test_confidence_is_constrained():
    with pytest.raises(ValidationError):
        RootCauseResult(**_diagnosed(confidence="certain"))


# --- the prompt ----------------------------------------------------------- #


def test_the_prompt_says_the_profile_is_the_primary_evidence():
    lowered = ROOT_CAUSE_TASK_DETAILS.lower()
    assert "primary evidence" in lowered
    assert "profile" in lowered


def test_the_prompt_carries_all_three_scale_bands():
    """Roughly 2x / 2-10x / >10x, each widening what gets considered."""
    assert "2x" in ROOT_CAUSE_TASK_DETAILS
    assert "10x" in ROOT_CAUSE_TASK_DETAILS


def test_every_scale_band_is_phrased_as_also_consider():
    """Guidance, not a gate.

    "there isn't always a clear cut if A then B path... sometimes it really is
    a matter of making each hot spot faster." A band phrased as "therefore"
    becomes an instruction to stop looking at what the profile shows, which is
    worse than offering no scale guidance at all.
    """
    assert ROOT_CAUSE_TASK_DETAILS.lower().count("also consider") >= 3


def test_the_prompt_never_turns_a_scale_band_into_a_conclusion():
    lowered = ROOT_CAUSE_TASK_DETAILS.lower()
    for banned in ("therefore", "you must conclude", "it follows that"):
        assert banned not in lowered, (
            f"{banned!r} turns the scale guidance into a rule that overrides "
            "the profile"
        )


def test_the_prompt_gives_an_explicit_out_when_no_reference_applies():
    lowered = ROOT_CAUSE_TASK_DETAILS.lower()
    assert "no reference" in lowered or "none of the reference" in lowered


def test_the_prompt_forbids_scaling_against_container_timings():
    """Container timings are excluded from every scale comparison.

    The +277ms artifact: an emulated container fabricated a cross-browser
    delta out of nothing. Read as a large gap it would have made the analysis
    confidently wrong about the SHAPE of the problem, not merely its size.
    """
    lowered = ROOT_CAUSE_TASK_DETAILS.lower()
    assert "container" in lowered
    assert "277" in ROOT_CAUSE_TASK_DETAILS


def test_the_prompt_says_inconclusive_is_a_good_outcome():
    lowered = ROOT_CAUSE_TASK_DETAILS.lower()
    assert "inconclusive" in lowered
    assert "good outcome" in lowered or "good result" in lowered


def test_the_prompt_tells_the_model_to_use_the_skill():
    assert "profiler-analysis" in ROOT_CAUSE_TASK_DETAILS


# --- reference points ------------------------------------------------------ #


def test_reference_md_is_shipped_with_the_package():
    from hackbot_agents.perf_triage import rootcause

    path = Path(rootcause.__file__).parent / "reference.md"
    assert path.is_file()


def test_reference_points_are_short_enough_to_be_prompt_context():
    """It is prompt context, not a document.

    Long enough to drown the profile in numbers is a regression.
    """
    assert len(reference_points()) < 4000


def test_reference_points_cover_every_perf_area():
    text = reference_points().lower()
    for area in (
        "pageload",
        "responsiveness",
        "memory",
        "startup",
        "resource_use",
        "frontend",
        "animation",
    ):
        assert area in text, f"no reference points for perf_area={area!r}"


def test_reference_points_carry_the_perception_thresholds():
    text = reference_points()
    assert "100ms" in text
    assert "180ms" in text  # Firefox warm TTFP on reference hardware
    assert "16.7ms" in text  # one frame at 60fps


def test_reference_points_for_an_area_omit_the_other_areas():
    """One comparison, not a table to browse."""
    text = reference_points("animation")
    assert "16.7ms" in text  # the animation figures
    assert "180ms" not in text  # pageload's, which this bug is not about


def test_reference_points_for_an_area_keep_the_shared_thresholds():
    text = reference_points("memory")
    assert "100ms" in text  # Nielsen/Miller, relevant to every area


def test_every_area_keeps_the_no_reference_applies_escape_hatch():
    """The out must survive the per-area trim, or a narrow area loses it."""
    for area in ("pageload", "memory", "animation", None):
        assert "no reference point applies" in reference_points(area).lower()


def test_an_unknown_area_still_yields_the_shared_thresholds():
    """Not a crash, and not the whole file either.

    An unknown area gets the human thresholds plus the explicit permission to
    conclude that no reference applies.
    """
    text = reference_points("some_future_area")
    assert "100ms" in text
    assert "no reference point applies" in text.lower()
    assert "16.7ms" not in text


# --- the task ------------------------------------------------------------- #


def _task(**kwargs):
    defaults = dict(
        profile_url="https://share.firefox.dev/3ySYdnj",
        perf_area="pageload",
        symptom="blank page for ~10s before content appears",
        bug_summary="Slow load on example.com",
        stated_threshold_ms=10000.0,
    )
    defaults.update(kwargs)
    return RootCause(TaskConfig(), RunTracker(), **defaults)


def test_the_task_enables_the_vendored_skill():
    """`skills=` is what loads profiler-analysis.

    Without it the run has no profiler-cli procedure at all and quietly
    improvises one.
    """
    options = _task().agent_options()
    assert options.skills == ["profiler-analysis"]


def test_the_task_does_not_set_setting_sources_by_hand():
    """The SDK sets setting_sources itself when `skills` is passed.

    It also adds the Skill tool. Every other agent here passes
    setting_sources=[], which would disable the very discovery this task
    depends on.
    """
    assert _task().agent_options().setting_sources != []


def test_the_user_prompt_carries_the_profile_url():
    prompt = _task().user_prompt()
    assert "https://share.firefox.dev/3ySYdnj" in prompt


def test_the_user_prompt_carries_the_symptom_and_area():
    prompt = _task().user_prompt()
    assert "blank page" in prompt
    assert "pageload" in prompt


def test_the_user_prompt_carries_the_reference_points_for_the_area():
    """The second lens has to actually be in the prompt to be a lens."""
    prompt = _task().user_prompt()
    assert "180ms" in prompt or "100ms" in prompt


def test_a_stated_threshold_reaches_the_prompt_labelled_as_the_reporters():
    """A number from the bug is comparable; a container timing is not.

    So the prompt has to say which of the two this is.
    """
    prompt = _task(stated_threshold_ms=8000.0).user_prompt()
    assert "8000" in prompt
    assert "report" in prompt.lower()


def test_no_stated_threshold_is_stated_plainly_rather_than_faked():
    prompt = _task(stated_threshold_ms=None).user_prompt()
    assert "None" not in prompt.split("\n\n")[0]
    assert "no absolute" in prompt.lower() or "states no" in prompt.lower()


def test_the_task_allows_the_bash_tools_the_skill_needs():
    """profiler-cli and searchfox-cli are invoked through Bash."""
    assert "Bash" in _task().allowed_tools


def test_the_task_name_and_result_class_are_wired():
    task = _task()
    assert task.name == "root_cause"
    assert task.result_cls is RootCauseResult


def test_the_subject_identifies_the_profile_under_analysis():
    assert "share.firefox.dev" in str(_task().subject())
