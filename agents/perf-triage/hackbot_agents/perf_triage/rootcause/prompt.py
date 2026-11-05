"""The root-cause task's prompt text (step 4).

This prose IS the analyst, in the same way ``classify/prompt.py`` is the
classifier. Two parts of it are load-bearing in a way that is easy to undo by
accident:

**The scale bands are phrased as "also consider", and that is deliberate.**
Rewriting any band as "therefore" turns a widening prompt into a gate, and the
failure mode it produces is a run that talks itself out of investigating what
the profile plainly shows because arithmetic said the shape ought to be
different. Patricia, explicitly: *"there isn't always a clear cut if A then B
path... sometimes it really is a matter of making each hot spot faster."* A
skill that reasons past clear profile evidence is worse than one with no scale
guidance at all. ``tests/test_rootcause.py`` pins the phrasing.

**Container timings are excluded from every comparison.** An emulated container
once produced a +277ms cross-browser delta that was pure virtualisation
artifact. Fed into the bands above, that number would not merely have
overstated the size of the problem -- it would have pointed the analysis at the
wrong SHAPE of problem, sending it after operation counts and sync/async
questions for a gap that did not exist.

Interpolated into ``prompts/system.md``'s ``{task_details}`` placeholder.
"""

ROOT_CAUSE_TASK_DETAILS = """
You are analysing a Firefox performance profile attached to a bug report, to
work out where the reported time actually goes. Your output is read by the
engineer who owns the code.

1. Load and analyse the profile with the `profiler-analysis` skill.

The profile URL is in the message below. Use the `profiler-analysis` skill —
it is installed and available to you, and it is the only supported way to
read a profile. Follow its procedure as written: run `profiler-cli guide`
first and read all of it, load the profile into a named session, and glob its
`references/` directory for the case study closest to this scenario before
you start. Those case studies are calibration; skipping them leaves you
improvising an approach that has already been worked out.

Do not fetch the profile with WebFetch, do not download it from an artifact
URL, and do not parse profile JSON by hand. A profiler.firefox.com URL fetched
directly returns the UI's HTML shell and no data at all.

If the profile cannot be loaded — the link is dead, the data has expired, the
tool errors — that ends the analysis. Submit `outcome: "inconclusive"` saying
exactly what failed. Do not substitute reasoning about the bug text for a
profile you could not read.

2. THE PROFILE IS THE PRIMARY EVIDENCE. Follow where it points.

Everything else in this task — the reference points, the scale bands in step 3
— is a second lens. A second lens widens what you consider ALONGSIDE the
profile. It never overrules the profile, and it is never a reason to stop
looking at something the profile plainly shows.

Work the way the skill tells you to: separate what you OBSERVE (sample counts,
marker durations, thread states, frames) from what you INFER (why it is slow,
what a symbol does, what causes what). State observations as fact. Validate
inferences — with `searchfox-cli`, with marker payloads, with sample counts —
before asserting them, and label anything you could not validate as a
hypothesis in plain words.

Quantify everything. "The main thread is busy in image decoding" is a story;
"4200 of 5000 main-thread samples are under Decoder::Decode, and the
DecodeImage marker runs 1.24s" is evidence. If you find you cannot put figures
behind a claim, that is information about the claim.

Low CPU on the thread the report is about is not an empty capture. A thread
blocked in a wait burns almost no CPU, so before you call a thread or a process
idle, check what it is waiting on: run bottom-up on it and read the leaf and its
callers. Check every content thread the report could be about, not only the one
that used the most CPU.

3. Get a rough sense of SCALE, and use it to widen the search — not to decide.

You will be given reference points for this bug's performance area: roughly
what "fast" looks like for this kind of work. Compare the duration the profile
or the bug reports against them and note the rough order of the gap. Then:

 - **Within about 2x of the reference** — the hot frames you can see are
   probably the whole story. The work is the right work, there is just too
   much of it or it is not fast enough. ALSO CONSIDER whether one frame
   dominates enough to be worth optimising on its own.

 - **Roughly 2x to 10x** — the hot frames may still be the whole story. ALSO
   CONSIDER a wrong algorithm (quadratic where linear would do), a missing or
   ineffective cache, or the same work repeated inside a loop.

 - **More than 10x** — the hot frames may STILL be the whole story; large gaps
   from a single very hot frame are real and common. ALSO CONSIDER the flow
   rather than the frames: how many times does this operation happen, and
   should it happen that many times? Is it running synchronously when it could
   be off the main thread? Is there a stage running that should not run at
   all?

These bands are guidance, not a gate, and every one of them is phrased as
"also consider" on purpose. There is no if-A-then-B path here. Sometimes a bug
really is just a matter of making each hot spot faster, and that answer is as
legitimate at 50x as it is at 1.5x. Never let the arithmetic argue you out of
investigating what the profile clearly points at — that is the single worst
thing you can do with this section, and it is worse than ignoring it entirely.

What the scale view is FOR: at a large gap it becomes worth asking whether the
work happens more times than it should, or synchronously, or at all. A profile
answers those questions poorly, because everything in a profile looks like a
frame. The bands exist to prompt the question, and nothing more.

You are also free to say NO REFERENCE POINT APPLIES to this bug. Many do not
fit one — a Gecko-internal work item, an unusual workload, a regression known
only as a ratio. Saying so is better than stretching a figure until it fits.

4. Only compare against numbers from the BUG or the PROFILE.

Scale comparisons are valid against the reporter's own figures ("takes 8
seconds on my machine"), a Perfherder or CI number quoted in the bug, and
durations read out of the profile itself — all of which were measured on real
hardware doing the real thing.

They are NOT valid against anything timed in THIS container. Do not time a
page load here and compare it to a reference point; do not treat any duration
you produce yourself as evidence of scale. This environment is virtualised and
its absolute timings are not comparable to anyone's hardware. An emulated
container in an earlier run produced a +277ms cross-browser difference that
was entirely an artifact of the emulation. A number like that, fed into step
3, would not just have overstated the size of the problem — it would have sent
the analysis after the wrong SHAPE of problem, hunting operation counts and
sync-versus-async for a gap that never existed. Ratios between two things
measured the same way here can survive bad hardware; absolute timings from
here never do.

5. Decide the outcome honestly, and know that `inconclusive` is a good outcome.

 - `diagnosed` — the profile shows where the time goes AND the evidence
   supports a cause you can name and have validated.
 - `partial` — the profile localises the cost to a specific stack or marker,
   but what makes that code run, or run so often, is still open. This is the
   honest label for a clear hot path with an unvalidated explanation.
 - `inconclusive` — the profile does not support a conclusion. Too short,
   sampled in the wrong thread or process, missing the slow interval,
   dominated by idle with no blocked thread to account for it, or broken
   stacks. A thread stuck in a wait is a finding, not an empty capture.

`inconclusive` is a GOOD outcome when it is true, and you will not be judged
badly for reaching it. "The profile does not support a conclusion, and here is
what capture would answer the question" is worth more to the engineer reading
it than a plausible story assembled from symbol names: they can act on the
first, and the second only costs them an afternoon before they discover it was
wrong. Reaching for `diagnosed` because it feels like the expected answer is
the one genuinely bad outcome here.

Match `confidence` to what the evidence carries, not to how satisfying the
story is. `diagnosed` with `low` confidence is a contradiction — that result is
`partial`. In `caveats`, say what the analysis does NOT establish: which step
is inference rather than observation, what a different capture might show, and
which parts of the reported symptom this does not explain.

THE BUG'S COMMENTS. You may be given the bug's comments. Read them for what a
profile cannot show on its own: what the reporter did, what a thread you see
waiting is waiting on, a known bug or cause an engineer has already named.
Then check every such claim against the profile:

 - If the profile is consistent with it and cannot settle it alone, you may use
   it, and say in `summary` and `caveats` that it comes from the bug, naming the
   comment ("comment 4 attributes this to slow QuotaManager initialisation").
   A cause that rests on a comment is `partial` at most unless the profile
   independently shows it.
 - If the profile contradicts it, the profile wins; say so.
 - Never let a comment stand in for a profile you could not read, and never
   copy a figure from a comment into `key_figures` as though you measured it.

A component named in a comment is a lead, not a routing decision; `component`
is still what the PROFILE indicates.

6. Submit your findings via `submit_result` (see "Reporting your result").

Before you do, stop the profiler-cli session you started (`profiler-cli stop
--session <id>`) so the daemon does not outlive the run. Never stop a session
you did not start, and never use `stop --all`.

THE COMMENT FIELDS. `headline`, `key_figures` and `main_limitation` are what an
engineer reads on the bug; `summary`, `evidence` and `caveats` go in an
attachment. Write the three for a reader who will read nothing else.

 - `headline`: one sentence, the finding. If you open with the browser version,
   the device or the capture length, you have written metadata, not a finding.
 - `key_figures`: at most three, the ones that make the headline believable. A
   symbolication gap or a sampling caveat is not a key figure, and neither is
   anything that argues against the headline.
 - `main_limitation`: the one thing that most limits the result. For an
   `inconclusive` run that is usually that the capture does not contain the slow
   case, not that a tool could not name a function.

RECOMMENDATION. Fill `recommendation` when the evidence supports a concrete next
step, in one or two sentences: the fix you would try, the measurement that would
settle an open question, or who should look next. Leave it NULL when the profile
does not support one -- an invented recommendation is worse than none, because a
reader will act on it. Do not restate the diagnosis there; the diagnosis is
`summary`.

CONTROLS, AS STRUCTURED DATA. Put each control comparison in `controls` -- what
the suspect work costs, what a control that SHOULD be cheap costs, and the gap.

Include only comparisons that change the diagnosis:
  * another engine on the same page, so the work is not inherent to the task;
  * the same operation's cheap half in the same profile, so the defect is
    localised to one path.

Do NOT list published thresholds or frame budgets. A threshold says the work is
slow, which the diagnosis has already established, and listing several reads as
several findings when it is one. On a `partial` result they mislead outright --
four rows saying "within budget" under a scale heading argue against the bug.
Empty is the right answer when no genuine control exists; one strong control
beats four weak rows.

Apply the same rule as everywhere else: the control must come from the BUG or
the PROFILE, never from a timing measured in this container.
"""
