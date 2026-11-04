"""Root-cause analysis schema (step 4).

As in ``hackbot_agents.perf_triage.classify.result``, the pydantic ``Field`` descriptions are
not documentation: they are what the model reads while filling the schema, so
they are part of the analyst and must not be trimmed.

The shape here deliberately mirrors the honesty machinery that made the
generation agent trustworthy. ``declined`` there was the single most valuable
output across three pilots, because a stated refusal is actionable and a
plausible story is not. ``inconclusive`` is the same idea: it is a real
outcome, and the validator makes sure it cannot be quietly dressed up as an
answer by carrying a ``hot_path`` alongside it.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# What the analysis concluded.
#
# "partial" is not a softer "diagnosed": it means the profile located the cost
# but not what causes it -- the time is genuinely in this frame, and why it runs
# at all, or that often, is still open.
Outcome = Literal["diagnosed", "partial", "inconclusive"]

Confidence = Literal["high", "medium", "low"]


class ControlComparison(BaseModel):
    """One measurement of the suspect work against a CONTROL that should be cheap.

    Not a comparison against a published threshold. Measured across ten real rows
    on two bugs (2026-08-24), threshold rows restated slowness the diagnosis
    already showed -- 388x, 3882x and 33.8x over three different thresholds on the
    same bug -- while on a `partial` result four of five rows reported the bug as
    WITHIN budget, under a heading that implied the opposite. Patricia: "it's
    unclear which part of it is supposed to be actionable or important."

    A control comparison earns its place because it changes the diagnosis rather
    than restating it. Two kinds do that:

    * ANOTHER ENGINE on the same page. Chrome at ~2 s against Firefox's 338 s says
      the work is not inherent -- something in our implementation is wrong.
    * THE SAME OPERATION'S CHEAP HALF, in the same profile. Insert costing 40
      samples against removal's 93,208 localises the defect to the removal path,
      and no external reference can supply that.
    """

    control: str = Field(
        description=(
            "A SHORT NAME for what the suspect work is measured against -- at most "
            "about eight words, lower-case, no trailing explanation: 'Chrome on "
            "the same page', 'the insert half of the same re-sort', 'the same "
            "rAF loop before the simulation starts'. It is read inside a sentence "
            "('this is 200x the cost of <control>'), so a 200-character clause "
            "with a dash and a parenthetical breaks it. Put the reasoning -- why "
            "that control is comparable, what else it holds constant -- in "
            "`rationale`, which the full artifact renders and the comment does "
            "not. Never a published threshold or budget: a threshold says the "
            "work is slow, which the diagnosis already establishes."
        )
    )
    rationale: str | None = Field(
        default=None,
        description=(
            "Why this control is a fair comparison -- what it holds constant, "
            "where the figures came from. Any length; it goes to the artifact, "
            "not the bug comment. Null when the control's name says it all."
        ),
    )
    control_value: str = Field(
        description=(
            "What the control costs: ONE figure with its unit, nothing else. "
            "'~2 s', '40 samples (0.04%)', '0.35-1.85ms per callback'. No window, "
            "no call count, no provenance -- those go in `rationale`."
        )
    )
    measured: str = Field(
        description=(
            "What the suspect work costs: ONE figure with its unit, same unit as "
            "the control so the two are directly comparable. '338 s', '93,208 "
            "samples (95.8%)', 'avg 192.72ms per callback'. NOT '92.6ms-299.9ms "
            "per callback from t=728ms to end of profile (103 callbacks, avg "
            "192.72ms)' -- that is four facts where the comparison needs one; the "
            "range, the window and the count belong in `rationale`. This is read "
            "inside a one-line parenthetical, so keep it under ~40 characters."
        )
    )
    ratio: str | None = Field(
        default=None,
        description=(
            "The gap as a BARE MULTIPLIER and nothing else: '169x', '~2300x'. Not "
            "'~64x the slowest completed fetch, and unbounded (never completes)' "
            "-- that qualification belongs in `rationale`. Null when no ratio "
            "applies, e.g. when the control simply completes and this does not."
        ),
    )
    source: str | None = Field(
        default=None,
        description=(
            "Where the CONTROL figure came from, when it is not obvious: 'bug "
            "comment 0', 'this profile, t-2 function totals'. Null otherwise. A "
            "citation, never a measurement -- anything you measured goes in "
            "`measured` or `control_value`."
        ),
    )


class RootCauseResult(BaseModel):
    outcome: Outcome = Field(
        description=(
            "How far the profile actually got you. 'diagnosed' -- the profile "
            "shows where the time goes AND the evidence supports a cause you "
            "can name. 'partial' -- the profile localises the cost to a stack "
            "or marker, but what makes that code run, or run so often, is not "
            "established. 'inconclusive' -- the profile does not support a "
            "conclusion: it may be too short, sampled in the wrong thread, "
            "missing the slow interval, or dominated by idle. 'inconclusive' "
            "is a GOOD outcome when it is true. A stated 'the profile does "
            "not show this' is worth more to the engineer who reads it than a "
            "plausible story assembled from symbol names, because they can act "
            "on the first (capture a better profile) and the second only "
            "wastes their afternoon."
        )
    )

    summary: str = Field(
        description=(
            "What the profile shows, in two to five sentences, written to be "
            "pasted into a Bugzilla comment and read by the engineer who owns "
            "the code. Lead with the observation, not the inference. Firefox "
            "internals vocabulary is fine and expected -- Gecko, SpiderMonkey, "
            "Necko, the parent/content split -- there is no need to explain "
            "it. If the outcome is 'inconclusive', say plainly what is missing "
            "from the profile and what capture would answer the question."
        )
    )

    hot_path: str | None = Field(
        default=None,
        description=(
            "The stack, frame, or marker the evidence points at -- e.g. "
            "'mozilla::image::Decoder::Decode called under "
            "nsImageFrame::PaintImage', or a marker name and its duration. "
            "Name the specific thing you can point to in the profile, not the "
            "general area. Required when outcome is 'diagnosed' or 'partial'. "
            "MUST be null when outcome is 'inconclusive' -- if you can name a "
            "hot path, the outcome is at least 'partial', and if you cannot, "
            "do not guess one from a symbol that merely appeared in the "
            "output."
        ),
    )

    component: str | None = Field(
        default=None,
        description=(
            "The Bugzilla component the hot path belongs to, in "
            "'Product :: Component' form (e.g. 'Core :: ImageLib', "
            "'Core :: Layout', 'Firefox :: Address Bar'), when the profile "
            "names one clearly enough to route the bug. Null when it does not "
            "-- a profile often shows where time goes without identifying an "
            "owner, and a wrong component costs a triage round-trip. Do not "
            "infer a component from the bug's existing metadata; this field is "
            "for what the PROFILE indicates."
        ),
    )

    recommendation: str | None = Field(
        default=None,
        description=(
            "What you would do about it, in one or two sentences, when the "
            "evidence supports a concrete next step: the fix you would try, the "
            "measurement that would settle an open question, or the person or "
            "component that should look next. Null when the profile does not "
            "support one -- an invented recommendation is worse than none, "
            "because a reader will act on it. Do NOT restate the diagnosis here."
        ),
    )

    controls: list[ControlComparison] = Field(
        default_factory=list,
        description=(
            "The suspect work measured against a CONTROL that should be cheap, "
            "one entry per control. Include only comparisons that CHANGE the "
            "diagnosis: another engine on the same page (so the work is not "
            "inherent), or the same operation's cheap half in the same profile "
            "(so the defect is localised to one path). Do NOT list published "
            "thresholds or frame budgets -- those say the work is slow, which "
            "the diagnosis already establishes, and on a partial result they "
            "actively mislead by reporting the bug as within budget. Empty when "
            "no genuine control exists; one strong control beats four weak rows."
        ),
    )

    headline: str = Field(
        description=(
            "ONE sentence for the top of a Bugzilla comment: the finding, "
            "stated as an observation about the reported problem. 'The content "
            "main thread is blocked for the whole capture in a synchronous "
            "localStorage call.' Not the capture's metadata (browser version, "
            "device, duration), not the method, and not a hedge. When the "
            "outcome is 'inconclusive', say what the profile lacks."
        )
    )

    key_figures: list[str] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Up to three short quantified facts that carry the headline, each "
            "under about 120 characters, with the counts and units. "
            "'13,221 of 26,874 active samples (49%) under useSyncExternalStore'. "
            "Choose the figures that make the finding believable, not "
            "bookkeeping such as a symbolication gap, and not a figure that "
            "points the other way from the headline. Empty when the outcome is "
            "'inconclusive' and the profile has nothing that stands out."
        ),
    )

    main_limitation: str = Field(
        description=(
            "ONE sentence: the single thing that most limits how far an "
            "engineer should trust or act on this result. The missing evidence "
            "that would change the answer, or the part of the reported symptom "
            "the profile does not cover. Not a tooling detail such as "
            "minified names or sanitised URLs unless that is what actually "
            "blocks the conclusion. The full list stays in `caveats`."
        )
    )

    evidence: str = Field(
        description=(
            "The numbers behind the conclusion, quantified. Sample counts out "
            "of totals ('4200 of 5000 main-thread samples'), marker names with "
            "durations, thread and process identification, call counts. This "
            "field is what separates an analysis from a story: if you cannot "
            "put figures from the profile here, that is itself the signal that "
            "the outcome is 'inconclusive'. Never leave this empty and never "
            "fill it with prose that restates the summary."
        )
    )

    confidence: Confidence = Field(
        description=(
            "How much the evidence actually carries. 'high' -- the numbers are "
            "unambiguous and you validated the inference (searchfox, marker "
            "payloads, sample counts). 'medium' -- the profile is clear but "
            "part of the causal step is reasoned rather than shown. 'low' -- "
            "the reading is one of several the data admits. Confidence must "
            "match the outcome: 'diagnosed' with 'low' confidence is a "
            "contradiction, and 'partial' is the honest label for it."
        )
    )

    caveats: str = Field(
        description=(
            "What this analysis does NOT establish, stated plainly. The "
            "profile is one capture on one machine in one state: say what is "
            "unvalidated inference, what a different capture might show, and "
            "which parts of the reported symptom this does not account for. "
            "'None' is almost never true here -- if nothing comes to mind, the "
            "analysis has probably not been examined hard enough. This field "
            "is read by an engineer deciding how much to trust the rest."
        )
    )

    @model_validator(mode="after")
    def _check_outcome_matches_the_evidence(self) -> RootCauseResult:
        if not self.evidence.strip():
            raise ValueError(
                "evidence must be non-empty and quantified: sample counts, "
                "marker durations, thread identification. An analysis with no "
                "figures behind it is a story, and its outcome is "
                "'inconclusive'"
            )
        if not self.summary.strip():
            raise ValueError("summary must not be empty")
        if not self.headline.strip():
            raise ValueError("headline must not be empty")
        if not self.main_limitation.strip():
            raise ValueError("main_limitation must not be empty")
        if any(not f.strip() for f in self.key_figures):
            raise ValueError("key_figures must not contain empty entries")

        if self.outcome == "inconclusive":
            if self.hot_path is not None:
                raise ValueError(
                    "hot_path must be null when outcome is 'inconclusive': "
                    "naming one contradicts the outcome. If the profile does "
                    "point somewhere, the outcome is at least 'partial'; if it "
                    "does not, do not record a frame you merely saw in the "
                    "output"
                )
            return self

        if not (self.hot_path or "").strip():
            raise ValueError(
                f"hot_path is required when outcome is {self.outcome!r}: name "
                "the stack, frame, or marker the evidence points at, or use "
                "outcome='inconclusive'"
            )
        return self
