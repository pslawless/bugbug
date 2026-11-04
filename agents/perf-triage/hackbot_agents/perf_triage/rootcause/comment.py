"""Render a root-cause result as a Bugzilla comment and as a full record.

Two outputs, different audiences. A real result (bug 1823474) measures 9,478
characters, and nobody reads a 10K bug comment.
:func:`render_root_cause_comment` writes what a Firefox engineer on the bug
reads; :func:`render_root_cause_full` writes every field for the attachment.
Nothing is lost; it is relocated, and the comment says where.

THE COMMENT IS COMPOSED FROM FIELDS THE MODEL WROTE FOR IT -- ``headline``,
``key_figures``, ``main_limitation`` -- and never from sentences picked out of
``evidence`` or ``caveats``. An earlier version picked sentences with
heuristics, and on four real results it led with a symbolication gap, with the
capture's device model, and with a 5.8% item in a profile that had no dominant
hot path. Heuristic selection over free text broke on each new bug, so the
selection moved to the one party that knows which sentence is the finding.

Pure functions, no I/O. Bugzilla-renderable Markdown only: bare URLs, backticks
for identifiers, ``**bold**``, ``- `` bullets. No ``#`` headings and no
triple-backtick fences.
"""

import html
import re

from hackbot_agents.perf_triage.rootcause.result import RootCauseResult
from hackbot_agents.perf_triage.text import clean as _clean

__all__ = ["render_root_cause_comment", "render_root_cause_full"]


def _component(name: str | None) -> str | None:
    """A component name fit to print.

    A live run returned "Core :: DOM: Core &amp; HTML" -- the model HTML-escaped
    the ampersand. Left alone that renders literally in a Bugzilla comment, and
    it also breaks _same_component, so a bug filed in "DOM: Core & HTML" would be
    reported as needing a move to "DOM: Core &amp; HTML". Unescape once, here,
    rather than at each of the several places a component is read.
    """
    if not name:
        return name
    return _clean(name)


def _same_component(a: str, b: str) -> bool:
    """Whether two component strings name the same place.

    Bugzilla writes "Core :: DOM: Core & HTML" while an analysis may say
    "DOM: Core & HTML" for the same component, so compare on the part after the
    product separator and ignore case and spacing.
    """

    def norm(x: str) -> str:
        tail = html.unescape(x).split("::")[-1]
        return " ".join(tail.split()).casefold()

    return norm(a) == norm(b)


# Marker prose some analyses append after the chain: ". Marker: ..." or
# ". Markers: ...". Matching only the singular left "k0). Markers: ..." in a
# posted comment.
_TRAILING_MARKER_PROSE = re.compile(r"\.\s+Markers?:", re.I)


def _short_hot_path(hot_path: str, limit: int = 200) -> str:
    """The hot path, shortened to the frames a reader can act on.

    Real hot paths are long: rc-1823474's is 528 characters of call chain from
    ``nsRefreshDriver::Tick`` down to ``nsJPEGDecoder``. Pasted whole into a
    concise comment it is a wall of arrows nobody reads, and the frame that
    matters -- the leaf, where the time actually is -- is at the far end. So
    when the chain is too long, keep the entry and the leaf and elide between
    them; the full chain is in the artifact.
    """
    body = _clean(hot_path).replace("\n", " ")
    # Only the chain itself, not the trailing marker prose some analyses append.
    chain = _TRAILING_MARKER_PROSE.split(body)[0].strip().rstrip(".")
    if len(chain) <= limit:
        return chain

    for arrow in ("→", "->", "←", "<-"):
        if arrow in chain:
            frames = [f.strip() for f in chain.split(arrow) if f.strip()]
            if len(frames) >= 3:
                return f"{frames[0]} {arrow} ... {arrow} {frames[-1]}"
            break
    return chain[:limit].rstrip() + "..."


def _field(label: str, value: object) -> str:
    return f"**{label}**: {value}"


def _full_root_cause(rc: RootCauseResult) -> list[str]:
    lines = [
        "**Profile analysis**",
        _field("Outcome", rc.outcome),
        _field("Confidence", rc.confidence),
        _field(
            "Component", _component(rc.component) or "not identified from the profile"
        ),
        _field(
            "Hot path",
            # _clean, not the raw field: the artifact prints the hot path in
            # full, so an escaped C++ template is a longer wall of entities here
            # than in the comment, not a shorter one.
            f"`{_clean(rc.hot_path)}`" if rc.hot_path else "none -- inconclusive",
        ),
        "**Summary**",
        _clean(rc.summary),
        "**Evidence**",
        _clean(rc.evidence),
    ]
    # EVERY control, with its rationale. The comment renders one control, drops
    # any over-long figure pair, and never shows `rationale` at all -- so without
    # this block the analyst's reasoning about WHY a control is comparable is
    # collected and silently discarded. This file is where the shortened material
    # is supposed to live.
    if rc.controls:
        lines.append("**Measured against controls**")
        for c in rc.controls:
            gap = f" -- {c.ratio}" if c.ratio else ""
            src = f" [{c.source}]" if c.source else ""
            lines.append(f"- {c.control}: {c.measured} vs {c.control_value}{gap}{src}")
            if c.rationale:
                lines.append(f"  {_clean(c.rationale)}")
    if rc.recommendation:
        lines.append("**Recommendation**")
        lines.append(_clean(rc.recommendation))
    lines.extend(
        [
            "**What this does not establish**",
            _clean(rc.caveats),
        ]
    )
    return lines


def render_root_cause_comment(
    rc: RootCauseResult,
    *,
    current_component: str | None = None,
    profile_url: str | None = None,
    attachment_name: str | None = None,
) -> str:
    """The comment an engineer on the bug reads.

    Order: the finding and how far to trust it, the few figures behind it, the
    hot path, what to do, and what is not established. ``attachment_name`` names
    the file carrying the full analysis.
    """
    component = _component(rc.component)
    headline = _clean(rc.headline)
    if rc.outcome == "inconclusive":
        # Only a finding: "reached no conclusion" is the outcome, the headline
        # says what the profile lacks.
        parts = [f"**Profile analysis reached no conclusion.** {headline}"]
    elif rc.confidence == "low":
        # A low-confidence partial is one reading of several. This comment can
        # post unattended alongside a confident rating, so it says no cause was
        # established rather than lead with a guess; the leads are attached.
        parts = [
            "**Profile analysis was inconclusive.** It found leads but could not "
            "support any of them with confidence, so this comment names no cause."
        ]
        parts.append(f"**Not established:** {_clean(rc.main_limitation)}")
        if profile_url:
            parts.append(f"Profile analysed: {profile_url}")
        if attachment_name:
            parts.append(
                f"The leads, evidence and caveats: attached as {attachment_name}."
            )
        return "\n\n".join(parts)
    else:
        label = "Diagnosed" if rc.outcome == "diagnosed" else "Partial diagnosis"
        where = f" in `{component}`" if component else ""
        parts = [f"**{label}**{where} ({rc.confidence} confidence). {headline}"]

    if rc.key_figures:
        parts.append("\n".join(f"- {_clean(f)}" for f in rc.key_figures))

    if rc.hot_path:
        parts.append(f"Hot path:\n\n    {_short_hot_path(rc.hot_path, limit=220)}")

    recommendation: list[str] = []
    if rc.recommendation:
        recommendation.append(_clean(rc.recommendation))
    # A component that is not the bug's own is a proposed move, and the owner
    # decides: both costs in a profile can be real. Only on `diagnosed`: a
    # partial result located the cost but not its cause, so it cannot route the
    # bug (1933799: partial pointed at localStorage while the cause, per the
    # bug's comments, was QuotaManager init).
    if (
        rc.outcome == "diagnosed"
        and component
        and current_component
        and not _same_component(component, current_component)
    ):
        recommendation.append(
            f"Consider moving this to `{component}` -- it is filed in "
            f"`{current_component}`, and the profile points at the former. "
            "That is a suggestion, not a reclassification."
        )
    if recommendation:
        parts.append("**Recommendation:** " + "\n\n".join(recommendation))

    parts.append(f"**Not established:** {_clean(rc.main_limitation)}")

    tail = []
    if profile_url:
        tail.append(f"Profile analysed: {profile_url}")
    if attachment_name:
        tail.append(
            f"Full analysis, evidence and caveats: attached as {attachment_name}."
        )
    if tail:
        parts.append("\n\n".join(tail))

    return "\n\n".join(parts)


def render_root_cause_full(
    rc: RootCauseResult, *, profile_url: str | None = None
) -> str:
    """The complete record, every field, for the bug attachment and the artifact."""
    blocks = ["**Automated profile analysis**"]
    if profile_url:
        blocks.append(_field("Profile", profile_url))
    blocks.extend(_full_root_cause(rc))
    blocks.append(
        "Absolute timings measured inside the agent's container are not evidence "
        "about the reported bug and do not appear here."
    )
    return "\n\n".join(b for b in blocks if b.strip()) + "\n"
