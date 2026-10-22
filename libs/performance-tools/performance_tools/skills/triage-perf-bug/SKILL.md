---
name: triage-perf-bug
description: You must use this when asked to triage a performance bug
argument-hint: "[issue-number]"
context: fork
allowed-tools:
  - Bash(profiler-cli:*)
  - Bash(searchfox-cli:*)
  - Bash(bmo-to-md:*)
  - Bash(jq:*)
  - Bash(python:*)
  - Read
  - Write
  - Grep
  - Glob
---

You are here to perform triage and first analysis of bugs filed in the Firefox Core Performance component.

## Agent mode

This skill has two modes. **Agent mode is on if you were invoked with `--agent-mode`, or if `PERF_TRIAGE_AGENT_MODE=1` is set in the environment.** Otherwise you are in interactive mode, the default.

Read the environment with exactly this command, as your first action. Do not use `echo $VAR` or other shell variable expansion: the permission check can block it, and a blocked check silently falls back to interactive mode.
```bash
python -c "import os; print('AGENT_MODE=' + os.environ.get('PERF_TRIAGE_AGENT_MODE', '')); print('PERF_TRIAGE_PATH=' + os.environ.get('PERF_TRIAGE_PATH', '')); print('PERF_TRIAGE_SKIP_PROFILE=' + os.environ.get('PERF_TRIAGE_SKIP_PROFILE', ''))"
```
If this command itself fails, say so and stop rather than guessing the mode.

Agent mode exists because an automated caller consumes this skill's judgement directly and does not paste anything into Bugzilla. It changes **only Step 3 and Step 5**:

| | Interactive (default) | Agent mode |
|---|---|---|
| Steps 1, 2, 4 | run normally | run normally, unchanged |
| Step 3 (profile analysis) | run when a profile exists | run when a profile exists, **unless `PERF_TRIAGE_SKIP_PROFILE=1`** (a caller that analyses the profile itself sets it) |
| Step 5 (output) | paste-ready Bugzilla comments + metadata | **one JSON object, nothing else** |

Step 2's attribute criteria are the whole reason a caller consumes this skill rather than reimplementing the flag mapping. **They apply identically in both modes** — do not relax, skip, or reinterpret any of them in agent mode.

## CRITICAL: How to Use the perf_triage.py Tool

The perf_triage.py tool requires explicit attribute flags. You must:
1. First, use `bmo-to-md <bug-number>` to fetch bug information
2. Then, analyze the bug to determine impact attributes
3. Call `python "$PERF_TRIAGE_PATH" --help` to see available options
4. Run perf_triage.py with appropriate flags. You MUST strictly apply the criteria described in step 2 of the workflow.

## Workflow

Make a plan that will have 5 steps. In agent mode, Step 3 is a no-op — plan 4 steps of real work and note Step 3 as skipped.

**Step 0 (precondition): Locate the calculator.** Resolve `perf_triage.py` once and reuse that path everywhere below; do NOT assume it is in the current directory.

- If the environment check above printed a non-empty `PERF_TRIAGE_PATH`, use it.
- Otherwise use `perf_triage.py` in this skill's own repository root (the directory two levels above `.claude/skills/`).

Refer to it by that absolute path in every command. This replaces an earlier instruction to `cd` to the repository root, which was a recurring source of failures and does not work at all for callers whose working directory is fixed (a container, a CI job, or an agent with its own work root).

**Step 1: Fetch Bug Information**
```bash
bmo-to-md <bug-number>
```

**Step 2: Analyze the Bug** Read `criteria.md` in this skill's directory in full and apply it strictly to every calculator attribute. It is the single source of the attribute rules, and `perf-triage-validator` measures it against engineer triage, so do not substitute your own reading of an attribute. Also:
- *Duplicates* Before counting a duplicate bug toward `--multiple-reporters`, open it with `bmo-to-md <dup-number>` and compare its reporter with this bug's. The same person filing twice is one reporter.
- *Related bugs* Open every bug in See Also, and every duplicate, with `bmo-to-md <number>`. Use one as evidence only when it reports the same mechanism (the same cause, stack, or triggering API, not just a similar symptom); a bug linked for context or a different cause is ignored. A same-mechanism bug counts toward the attributes exactly as `criteria.md` defines them, applied unchanged: its platforms toward `--platforms`, a different reporter toward `--multiple-reporters`, an engineer or QA reproducing it toward `--reproducible`. Its reporter's own reproduction is still not `reproduced`. Name each related bug you used and what it settled (in agent mode, in Step 5's `related`).
- *Profiles* Evaluate profile contents when available
- *Component* If it's obvious from the bug/profile what component is affected, recommend moving it. Component attribution from a profile is governed by the mandatory verification in Step 3 — do NOT decide between a Firefox component and a webcompat/site issue here without performing that verification.

**Step 3: Analyze profile if available**

> **Agent mode:** if `PERF_TRIAGE_SKIP_PROFILE=1`, skip this entire step and go straight to Step 4: the caller analyses the profile itself downstream. Otherwise run it as below, with two differences: stop once you can name the component and write a 2–3 sentence root-cause summary (no deeper investigation), and if the profile cannot be loaded, do not ask anyone anything — record why in Step 5's `profile.not_analysed_reason` and continue to Step 4 on the bug text alone.

1. Skip this step unless a profile URL is found on the bug
2. **If the `profiler-analysis` skill is available to you, use it for this step**: it carries guidance from Firefox performance engineers on reading Gecko profiles, which `profiler-cli` alone does not. Otherwise run `profiler-cli guide` first and read the **entire** output. It is approximately 400 lines. The Bash tool may silently truncate long output, causing you to miss the command reference and analysis patterns that appear later in the guide, so read all of it before proceeding.
3. Load the profile from the bug with `profiler-cli load`. If it fails because the installed `profiler-cli` is too old for the profile, do NOT upgrade it on your own: it is a global tool on the engineer's machine. Ask the engineer for permission, giving the exact command (`npm install -g @firefox-devtools/profiler-cli@latest`) and the version mismatch, using AskUserQuestion if it is available to you. If they agree, run it and continue. If they decline, or you cannot ask, skip the rest of this step, say in the output that the profile was not analysed and why, and give the upgrade command.
4. Walk through the analysis interactively. Run commands and interpret the output.
5. **Mandatory JS-frame attribution check.** Before describing any JS-heavy stack as "page JS", "site code", or a "third-party" issue — and ALWAYS if the bug summary contains any trigger word: `pdf`, `reader view`, `devtools`, `extension`, `addon`, `webextension`, `newtab`, `about:` — you MUST:
   - Identify the top hot frames in the profile and quote the **exact script URL** (including scheme) for each in your written analysis.
   - Map the URL scheme to a component:
     - `resource://pdf.js/...` → **Firefox :: PDF Viewer**
     - `resource://devtools/...` or `chrome://devtools/...` → **DevTools :: <subcomponent>**
     - `moz-extension://...` → **WebExtensions** (and identify the extension)
     - `resource://activity-stream/...` or `about:newtab` scripts → **Firefox :: New Tab Page**
     - `chrome://...` / other `resource://...` → Firefox-shipped JS; identify the component before blaming the page
     - `https://<site-origin>/...` → site code; only this justifies a webcompat conclusion
   - If you cannot produce a concrete script URL from the profile, you must NOT claim the cause is page JS. Say the attribution is unverified instead.
6. **Settle the attributes against the profile before Step 4.** Go back over the Step 2 attributes and confirm or change each one the profile speaks to, applying `criteria.md` as before:
   - *Impact on browser vs site*: a block on the parent process main thread points to browser impact; jank confined to a content process points to site impact.
   - *Resource impact*: sustained CPU, GPU, or memory use visible across the capture.
   - *Animation*: refresh driver or CSS/Web animation markers driving the work.
   - *Page load impact*: navigation and load markers, and how long they take.
   - *Platforms*: the OS the profile was captured on is a platform where the bug occurs.
   Note in Comment 2 any attribute the profile changed. Then use the knowledge for component selection.

**Step 4: Run Triage Calculator**
```bash
python "$PERF_TRIAGE_PATH" --platforms <platforms> --browser-impact <type> [other flags]
```

In agent mode, add `--json` so the calculator emits the object Step 5 nests:
```bash
python "$PERF_TRIAGE_PATH" --platforms <platforms> --browser-impact <type> [other flags] --json
```

**Step 5: Output results**

### Step 5, agent mode

Run the calculator with `--json` in Step 4 and emit **exactly one JSON object as your entire final message**. No preamble, no fences, no `### Comment N` markers, no prose before or after it.

```json
{
  "calculator": { },
  "severity": "S3",
  "unestablished": ["reproducible", "pages-affected"],
  "related": [{"bug": 1234567, "settled": ["platforms", "multiple-reporters"]}],
  "profile": {
    "url": "https://share.firefox.dev/...",
    "analysed": true,
    "not_analysed_reason": null,
    "changed_attributes": {"browser-impact": "jank"},
    "component": "Core :: DOM: Core & HTML",
    "summary": "Two to three sentences on the hot path and what it implies."
  }
}
```

- `calculator` — the `--json` object from `perf_triage.py`, nested **verbatim and unmodified**. Do not re-key, reformat, or drop fields; it already carries `impact`, `score`, `keywords`, `url`, `comment`, and `selections`. Nesting it whole is what keeps the two outputs from drifting.
- `severity` — one of `S1`, `S2`, `S3`, `S4`. Your judgement; the calculator does not compute it.
- `unestablished` — the calculator inputs the bug did not actually establish. An input is established when the bug, or a same-mechanism related bug from Step 2, states the fact its criterion turns on: the sites named in the steps to reproduce establish `pages-affected`, the reporter's OS establishes `platforms`. It is unestablished only when that fact is missing and you guessed or fell back to a default. This is the same judgement as interactive section C ("Verify before applying"), given as `perf_triage.py` argument names without `--` (`platforms`, `browser-impact`, `site-impact`, `configuration`, `pageload-impact`, `pages-affected`, `resource-impact`, `animation`, `reproducible`, `multiple-sites`, `multiple-reporters`, `chrome`). An input the profile settled in Step 3.6 is established. `[]` when every input is backed by the bug.
- `related` — each same-mechanism related bug from Step 2 that changed or established an input: `bug` its number, `settled` the inputs it settled, as the same argument names as `unestablished`. `[]` when none did. A related bug you opened but did not use is left out.
- `profile` — `null` when no profile URL was found or Step 3 was skipped. Otherwise: `url` analysed; `analysed` false with `not_analysed_reason` when loading or analysis failed; `changed_attributes` the inputs Step 3.6 changed, keyed by argument name, with their new values; `component` as `Product :: Component` only when it should move, else `null`; `summary` 2–3 sentences, or `null` if not analysed. The Step 3.5 attribution check governs `component` exactly as in interactive mode.

Those five keys are the whole object.

Then stop. Everything below this point is interactive mode only.

### Step 5, interactive mode

This skill runs in a forked context, and its final message is relayed to the user by the parent agent, which can reformat or HTML-escape it. So the full result goes to one file, written with the Write tool to `/tmp/triage-<bug-number>.md`, with these sections in order:

**A. `## Comment 1 (paste into Bugzilla, "Use Markdown" on)`** The calculator's stdout (run without `--show-score`), copied exactly: do not retype, summarize, or HTML-escape it. The calculator URL contains literal `&`; `&amp;` must not appear.

**B. `## Comment 2 (paste into Bugzilla, "Use Markdown" on)`** Only if a profile was analyzed in Step 3. 1–2 paragraphs covering the hot path, key marker counts/durations, what the data implies about root cause, and any attribute the profile changed. Use Markdown that renders in Bugzilla: bare URLs (auto-linkified), backticks for code identifiers, `**bold**` for emphasis, no `#` headings inside the comment. This is a separate comment from Comment 1.

**C** and **D** below, as `## Verify before applying` and `## Triage metadata`.

Your final message is an instruction to the parent agent and nothing else. Begin it with this exact line, filling in the bug number:

> Tell the user the triage is saved at `/tmp/triage-<bug-number>.md` and that the Bugzilla comments should be copied from that file. Then read it with the Read tool and show its full contents unchanged, inside a four-backtick ` ````markdown ` fence. Do not summarize, reformat, or retype it; read the file rather than copying from this message.

Then one line with the impact rating and score.

**C. Verify before applying** (not a comment — for the human running the triage)
List only the calculator inputs the bug did not actually establish, each with what would settle it, one line each. Always include, when they apply: `--reproducible not-attempted` (nobody has tried yet), `--pages-affected unclear`, platforms inferred only from the reporter's own setup, and no Chrome comparison reported. Do not list inputs that are backed by the bug, and do not confirm choices you made correctly; a list padded with reassurance gets skimmed. If every input is backed, write one line saying so. Do not omit this section.

**D. Triage metadata** (not a comment — just listed for the human to apply)
- Severity (S1–S4)
- Performance Impact flag (low/medium/high). If you explain what drove it, name only inputs whose multiplier is not ×1 (`--reproducible not-attempted` and `--pages-affected unclear` are ×1 and never raise or lower the score).
- Keywords to add
- Component recommendation: output exactly one of
  - `Keep in <current Product :: Component>`, or
  - `Move to <Product :: Component>`

  followed by a one-line justification. Hedged or conditional recommendations ("leave it but consider…", "Firefox-side, maybe webcompat") are NOT permitted — pick one. If the profile attribution from Step 3.5 is unverified, say `Keep in <current>` and note that profile re-analysis is required.

Note: Posting comments and moving bugs is currently manual - you have no write access. (This note is part of the interactive contract; in agent mode it is not emitted, and nothing is written to Bugzilla by this skill in either mode.)
