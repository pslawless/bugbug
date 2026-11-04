"""The root-cause comment and the full record, against real stored outputs.

The fixtures are real ``RootCauseResult`` payloads from probe runs on four bugs
(2026-11-03), not invented ones: a partial with a component, a partial with
none, a partial in another component, and an ``inconclusive``. The last is a
run that missed a blocked thread the profile does show (since fixed in the
prompt); it is kept because it is the shape an inconclusive result takes.
"""

import json
import re
from pathlib import Path

import pytest
from hackbot_agents.perf_triage.rootcause import RootCauseResult
from hackbot_agents.perf_triage.rootcause.comment import (
    _short_hot_path,
    render_root_cause_comment,
    render_root_cause_full,
)
from hackbot_agents.perf_triage.rootcause.result import ControlComparison

FIXTURES = Path(__file__).parent / "fixtures"
REAL = [
    "bug-1933799-partial-component",
    "bug-1931896-partial-no-component",
    "bug-1988762-partial-webrender",
    "bug-1933799-inconclusive",
]


def _load(name: str) -> tuple[RootCauseResult, dict]:
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    return RootCauseResult(**data["result"]), data


def _comment(name: str, **kwargs) -> str:
    rc, data = _load(name)
    kwargs.setdefault("profile_url", data["profile_url"])
    kwargs.setdefault("attachment_name", f"root-cause-{data['bug_id']}.md")
    return render_root_cause_comment(rc, **kwargs)


# --- every real output renders as something Bugzilla can show -------------- #


@pytest.mark.parametrize("name", REAL)
def test_real_results_validate_and_render(name):
    text = _comment(name, current_component="Core :: Performance")
    assert text.strip()


@pytest.mark.parametrize("name", REAL)
def test_comment_is_bugzilla_renderable_markdown(name):
    """No headings, no fences, no HTML entities: they post literally."""
    text = _comment(name)
    assert not re.search(r"^#", text, re.M)
    assert "```" not in text
    assert "&amp;" not in text and "&lt;" not in text


@pytest.mark.parametrize("name", REAL)
def test_comment_stays_concise(name):
    """A real analysis is 6-7K characters; the comment is the readable part."""
    assert len(_comment(name)) < 3000


@pytest.mark.parametrize("name", REAL)
def test_comment_is_composed_from_the_model_written_fields(name):
    rc, _ = _load(name)
    text = _comment(name)
    assert rc.headline in text
    assert rc.main_limitation in text
    for figure in rc.key_figures:
        assert f"- {figure}" in text


@pytest.mark.parametrize("name", REAL)
def test_comment_does_not_carry_the_attachment_only_fields(name):
    """Evidence and caveats belong in the attachment, not the comment."""
    rc, _ = _load(name)
    text = _comment(name)
    assert rc.evidence not in text
    assert rc.caveats not in text
    assert rc.summary not in text


# --- the label and what it claims ------------------------------------------ #


def test_a_partial_result_is_labelled_partial_with_its_confidence():
    text = _comment("bug-1931896-partial-no-component")
    assert text.startswith("**Partial diagnosis** (low confidence).")


def test_the_component_is_named_in_the_label_when_there_is_one():
    text = _comment("bug-1933799-partial-component")
    assert text.startswith(
        "**Partial diagnosis** in `Core :: Storage: localStorage & sessionStorage`"
        " (medium confidence)."
    )


def test_an_inconclusive_result_does_not_claim_a_diagnosis():
    """Its confidence is not shown: 'high confidence' on a no-conclusion reads wrong.

    The stored run really did return inconclusive with high confidence.
    """
    rc, _ = _load("bug-1933799-inconclusive")
    assert rc.confidence == "high"
    text = _comment("bug-1933799-inconclusive")
    assert text.startswith("**Profile analysis reached no conclusion.**")
    assert "confidence" not in text.split("\n")[0]
    assert "Hot path" not in text


def test_a_diagnosed_result_is_labelled_diagnosed():
    rc, _ = _load("bug-1933799-partial-component")
    rc = rc.model_copy(update={"outcome": "diagnosed", "confidence": "high"})
    assert render_root_cause_comment(rc).startswith("**Diagnosed**")


# --- component suggestion --------------------------------------------------- #


def test_a_different_component_is_a_suggestion_to_move():
    text = _comment(
        "bug-1988762-partial-webrender", current_component="Core :: Performance"
    )
    assert "Consider moving this to `Core :: Graphics: WebRender`" in text
    assert "a suggestion, not a reclassification" in text


def test_the_same_component_is_not_reported():
    """Agreement is not worth a sentence."""
    text = _comment(
        "bug-1988762-partial-webrender",
        current_component="Core :: Graphics: WebRender",
    )
    assert "Consider moving" not in text


def test_the_same_component_is_matched_across_product_and_spacing():
    text = _comment(
        "bug-1933799-partial-component",
        current_component="Storage:  localStorage & sessionStorage",
    )
    assert "Consider moving" not in text


def test_no_current_component_means_no_suggestion():
    assert "Consider moving" not in _comment("bug-1988762-partial-webrender")


def test_no_component_means_no_suggestion():
    text = _comment(
        "bug-1931896-partial-no-component", current_component="Core :: Performance"
    )
    assert "Consider moving" not in text


# --- pointers ---------------------------------------------------------------- #


def test_the_comment_points_at_the_profile_and_the_attachment():
    text = _comment("bug-1931896-partial-no-component")
    assert "Profile analysed: https://share.firefox.dev/4fxndEa" in text
    assert "attached as root-cause-1931896.md" in text


def test_no_attachment_name_means_no_attachment_pointer():
    rc, _ = _load("bug-1931896-partial-no-component")
    assert "attached" not in render_root_cause_comment(rc)


# --- the hot path ------------------------------------------------------------ #


def test_a_short_hot_path_is_kept_whole():
    assert _short_hot_path("A → B → C") == "A → B → C"


def test_a_long_chain_keeps_the_entry_and_the_leaf():
    chain = " → ".join(f"frame{i}" for i in range(60))
    out = _short_hot_path(chain, limit=100)
    assert out == "frame0 → ... → frame59"


def test_the_ascii_arrow_is_elided_too():
    chain = " -> ".join(f"frame{i}" for i in range(60))
    assert _short_hot_path(chain, limit=100) == "frame0 -> ... -> frame59"


def test_trailing_marker_prose_is_dropped_singular_and_plural():
    for tail in (". Marker: x 1.2s", ". Markers: x 1.2s, y 3s"):
        assert _short_hot_path("A → B → C" + tail) == "A → B → C"


def test_the_hot_path_is_an_indented_block():
    text = _comment("bug-1988762-partial-webrender")
    assert "Hot path:\n\n    RenderThread::UpdateAndRender" in text


# --- the full record --------------------------------------------------------- #


@pytest.mark.parametrize("name", REAL)
def test_the_full_record_carries_every_field_the_comment_leaves_out(name):
    rc, data = _load(name)
    full = render_root_cause_full(rc, profile_url=data["profile_url"])
    assert rc.summary in full
    assert rc.evidence in full
    assert rc.caveats in full
    assert data["profile_url"] in full
    assert rc.outcome in full


def test_the_full_record_shows_every_control_with_its_rationale():
    rc, _ = _load("bug-1931896-partial-no-component")
    rc = rc.model_copy(
        update={
            "controls": [
                ControlComparison(
                    control="the same page in Chrome",
                    rationale="Same URL, same navigation sequence.",
                    control_value="~2 s",
                    measured="5 s",
                    ratio="2.5x",
                ),
                ControlComparison(
                    control="the first navigation",
                    control_value="1769 samples",
                    measured="2115 samples",
                ),
            ]
        }
    )
    full = render_root_cause_full(rc)
    assert "the same page in Chrome" in full
    assert "Same URL, same navigation sequence." in full
    assert "the first navigation" in full


def test_the_full_record_says_container_timings_are_excluded():
    rc, _ = _load("bug-1931896-partial-no-component")
    assert "container" in render_root_cause_full(rc)


# --- model output hygiene ---------------------------------------------------- #


def test_html_escaped_model_text_is_unescaped():
    """The model has returned 'Core &amp; HTML' and escaped C++ templates."""
    rc, _ = _load("bug-1933799-partial-component")
    rc = rc.model_copy(
        update={
            "component": "Core :: DOM: Core &amp; HTML",
            "headline": "Time in nsTArray_Impl&lt;nsCOMPtr&gt; dominates.",
        }
    )
    text = render_root_cause_comment(rc)
    assert "`Core :: DOM: Core & HTML`" in text
    assert "nsTArray_Impl<nsCOMPtr>" in text
    assert "&amp;" not in text and "&lt;" not in text
