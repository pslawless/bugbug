# Reference points

Rough figures for what "fast" means, so a duration in the profile can be given a
sense of scale. These are a SECOND LENS, not a specification and not a budget to
check against. They are here to prompt a question — "is this 3x off or 300x
off?" — and the answer only ever widens what you consider alongside the profile.

Compare against numbers from the BUG or the PROFILE. Never against anything
timed in this container.

Sources: Nielsen (1993) after Miller (1968); Firefox internal targets; Core Web
Vitals; RAIL.

## The three human thresholds (all areas)

- **~100ms** — feels instantaneous; the user perceives direct causation.
- **~1s** — noticeable, but the user's train of thought is unbroken.
- **~10s** — the attention limit; beyond it users disengage or leave.

Users perceive delays as ~15% longer than they are, so a figure sitting just
inside a threshold is not comfortable.

## pageload

- Good < 1s; acceptable 1–3s; slow > 5s.
- LCP: good ≤ 2.5s, poor > 4s (p75 of real sessions).
- Firefox time-to-first-paint on reference hardware: **~180ms warm**.

## responsiveness

- Interaction to Next Paint (INP): good ≤ 200ms, poor > 500ms.
- Button/tap, in-page navigation, search: unnoticed < 100ms, noticeably slow
  above ~300ms, unacceptable > 1s.
- **50ms** is the RAIL "long task" threshold — past it, a task risks blocking
  visible response to input.

## animation

- **16.7ms** per frame = 60fps; **8.3ms** for 120Hz displays.
- ~10ms is the practical per-frame JS budget; the browser needs the rest.
- One dropped frame (a 33ms gap) is detectable by most people; sustained gaps
  above 33ms read as broken.

## startup

- Cold start: good < 1s, acceptable 1–2s, slow > 5s.
- Warm start: good < 500ms, acceptable up to ~1.5s, slow > 2s.
- Cold startup is largely I/O-bound — page faults, `read`/`stat` — so a profile
  dominated by I/O wait is expected here rather than anomalous.

## frontend

Firefox's own UI is held to interaction figures, not page-load ones: menus,
panels, and the urlbar should paint within the ~100ms instantaneous threshold,
and anything over ~300ms is noticeable. A chrome-process main-thread task over
50ms is already a jank risk.

## memory

No perception threshold applies — nobody feels a megabyte. Judge by shape
instead: growth that does not return to baseline after the work finishes,
allocation counts that scale with something that should be constant, or a
single allocation site dominating. Absolute RSS on unfamiliar hardware means
little.

## resource_use

Same caution as memory: CPU, power, and network have no perception threshold.
What matters is work happening when nothing should be happening — a timer that
keeps firing in a background tab, polling that continues after the page is
idle, wakeups per second on an otherwise quiet browser.

## When none of these fits

Say so. Plenty of bugs — a Gecko-internal work item, an unusual workload, a
regression measured only as a ratio — have no meaningful reference point here.
"No reference point applies; the profile is judged on its own" is a perfectly
good statement, and better than stretching a figure until it fits.
