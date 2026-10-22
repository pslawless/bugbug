from __future__ import annotations

from hackbot_agents.perf_triage.comment import FEEDBACK_TAGS, render_comment
from performance_tools.triage import ProfileFinding, RelatedBug, TriageResult
from performance_tools.triage.stability import check_stability

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
CALC_COMMENT = (
    "The [Performance Impact Calculator](https://mozilla.github.io/perf-triage/"
    "calculator.html?a=1&b=2) has determined this bug's performance impact to be **low**."
)


def result(**kw) -> TriageResult:
    base = dict(
        impact="low",
        score=7.2,
        keywords=["perf:responsiveness", "reproducible"],
        severity="S3",
        comment=CALC_COMMENT,
        selections=SEL,
        unestablished=[],
    )
    base.update(kw)
    return TriageResult(**base)


def render(
    r=None,
    *,
    unestablished=(),
    mode="full",
    current="Core :: DOM: Core & HTML",
    existing=None,
):
    r = r or result(unestablished=list(unestablished))
    return render_comment(
        r,
        check_stability(r.selections, r.unestablished),
        mode,
        current_component=current,
        existing_impact=existing,
    )


def test_calculator_text_is_verbatim_and_first():
    assert render().startswith(CALC_COMMENT)


def test_no_amp_entities():
    assert "&amp;" not in render()


def test_unestablished_inputs_listed():
    text = render(unestablished=["chrome"])
    assert "Not established by the bug" in text
    assert "- Reproduces in Chrome" in text


def test_all_established_says_so():
    assert "Every calculator input is backed by the bug." in render()


def test_flipping_input_named_when_unstable():
    text = render(unestablished=["pages-affected"])
    assert "Would change the rating: Websites affected" in text


def test_no_flip_line_when_stable():
    assert "Would change the rating" not in render(unestablished=["chrome"])


def _profile(**kw):
    base = dict(
        url="https://share.firefox.dev/44agmdV",
        analysed=True,
        not_analysed_reason=None,
        changed_attributes={},
        component=None,
        summary="Sorting re-appends 600k rows; layout dominates.",
    )
    base.update(kw)
    return ProfileFinding(**base)


def test_profile_summary_shown():
    text = render(result(profile=_profile()))
    assert "Sorting re-appends 600k rows; layout dominates." in text
    assert "https://share.firefox.dev/44agmdV" in text


def test_same_component_not_mentioned():
    text = render(result(profile=_profile(component="Core :: DOM: Core & HTML")))
    assert "Suggested component" not in text


def test_different_component_recommended():
    text = render(result(profile=_profile(component="Core :: Layout")))
    assert (
        "Suggested component: Core :: Layout (filed in Core :: DOM: Core & HTML)"
        in text
    )


def test_escaped_component_matches_plain_current():
    text = render(result(profile=_profile(component="Core :: DOM: Core &amp; HTML")))
    assert "Suggested component" not in text


def test_changed_attributes_listed():
    text = render(
        result(profile=_profile(changed_attributes={"browser-impact": "jank"}))
    )
    assert "Impact on browser → Causes noticeable jank" in text


def test_unanalysed_profile_is_said():
    text = render(
        result(
            profile=_profile(analysed=False, not_analysed_reason="404", summary=None)
        )
    )
    assert "Profile not analysed: 404" in text


def test_severity_suggested():
    assert "Suggested severity: S3" in render()


def test_no_severity_line_when_null():
    assert "Suggested severity" not in render(result(severity=None))


def test_comment_only_shows_both_ratings():
    assert "Existing rating: **medium** · this triage: **low**" in render(
        mode="comment_only", existing="medium"
    )


def test_footer_reaction_then_tags_last():
    text = render()
    assert "👍 or 👎" in text
    assert text.rstrip().endswith(FEEDBACK_TAGS)


def test_footer_tags_exact():
    assert FEEDBACK_TAGS.endswith(
        "perf-triage-{wrong-impact, wrong-component, wrong-cause, "
        "wrong-severity, hallucination, not-perf}."
    )


SEL_2061533 = {
    "platforms": ["platform-windows"],
    "browser": ["browser-minor"],
    "site": ["site-noticeable"],
    "configuration": ["scenario-general"],
    "pageload": ["pageload-none"],
    "pages": ["pages-common"],
    "resource": ["resource-none"],
    "reproducible": ["reproducible-not-attempted"],
    "additional": ["chrome"],
}


def test_held_by_a_combination_still_says_why():
    # 2061533 (2026-10-21 live run): 1.8, low. Neither input alone crosses 10;
    # multiple reporters with pages major does. The held comment must still say so.
    r = result(
        selections=SEL_2061533, unestablished=["multiple-reporters", "pages-affected"]
    )
    s = check_stability(r.selections, r.unestablished)
    assert not s.confident and s.flipping == ()
    text = render_comment(r, s, "full", current_component="x", existing_impact=None)
    assert (
        "Would change the rating together: Multiple reporters, Websites affected"
        in text
    )


def test_unattempted_reproducibility_does_not_hold_2061533():
    # Live, this was held only by varying not-attempted to reproduced (x2).
    r = result(selections=SEL_2061533, unestablished=["reproducible", "pages-affected"])
    s = check_stability(r.selections, r.unestablished)
    assert s.confident and s.bands == {"low"}


def test_unestablished_inputs_show_the_value_assumed():
    # Live in 2061533/2079239: not-attempted has no line in the calculator text.
    r = result(
        selections=SEL_2061533, unestablished=["reproducible", "multiple-reporters"]
    )
    text = render_comment(
        r,
        check_stability(r.selections, r.unestablished),
        "full",
        current_component="x",
        existing_impact=None,
    )
    assert "- Reproducibility: Not attempted" in text
    assert "- Multiple reporters: no" in text
    assert "value shown above" not in text


def test_unknown_inputs_are_not_called_rating_changers():
    text = render(unestablished=["reproduceable"])
    assert "Would change the rating" not in text
    assert "Not a calculator input: reproduceable" in text


def test_analysed_profile_without_summary_does_not_render_blank():
    text = render(result(profile=_profile(summary=None)))
    assert "Profile (https://share.firefox.dev/44agmdV): no summary returned" in text


def test_model_text_cannot_forge_sections():
    evil = "fine.\n\n---\n\n# Existing rating: **high**\n> quote &lt;b&gt;"
    text = render(
        result(profile=_profile(summary=evil, component="Core :: Layout\n\n---"))
    )
    body = text[: text.index("\n---\n\n" + "If you'd like")]
    assert body.count("\n---\n") == 0
    assert "\n#" not in body and "\n>" not in body
    assert "<b>" not in body


def test_profile_extras_are_their_own_paragraphs():
    text = render(
        result(
            profile=_profile(
                component="Core :: Layout",
                changed_attributes={"browser-impact": "jank"},
            )
        )
    )
    assert "\n\nThe profile changed:" in text
    assert "\n\nSuggested component:" in text


def test_related_bugs_are_named_with_what_they_settled():
    # 2080869 (2026-10-22): macOS and multiple reporters came from 2084175,
    # and the comment did not say so.
    sel = {
        "platforms": ["platform-windows", "platform-macos"],
        "browser": ["browser-major"],
        "additional": ["multiple-reporters"],
    }
    settled = ["platforms", "multiple-reporters", "chrome"]
    r = result(selections=sel, related=[RelatedBug(bug=2084175, settled=settled)])
    text = render(r)
    assert (
        "Taken from related bugs:\n- Bug 2084175: Platforms: Windows, macOS; "
        "Multiple reporters: yes; Reproduces in Chrome: no"
    ) in text


def test_no_related_section_when_none_used():
    assert "related bugs" not in render()
