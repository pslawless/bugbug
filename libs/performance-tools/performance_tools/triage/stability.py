"""Whether a triage rating survives the inputs the bug did not establish.

This is the auto-apply gate for the perf-triage agent: a rating is confident when
every plausible value of every unestablished input lands in the same impact band.
It is computed, not judged -- the calculator is a pure function, so re-running it
over the variants costs nothing and needs no model.

The variants are the calculator's own choices, read from its tables, so a re-pin
that adds a choice is picked up without an edit here. An input the skill names but
the calculator does not have forces a hold: that is a renamed flag or a typo, and
neither is evidence the rating is stable.

An unestablished ``reproducible`` left at not-attempted is not varied: nobody
having tried is not evidence either way, so it scores as the neutral x1.

``reproducible`` and ``platforms`` are also varied even when the skill reports
them as established -- :data:`ALWAYS_VARY`. The gate above only catches
*acknowledged* uncertainty: an input the skill is confident about but gets wrong
is never re-tested, because nothing marks it unestablished in the first place.
Measured against mozilla's tier-a-62 corpus (perf-triage-validator, 2026-10-26):
of 30 wrong-bucket predictions, 17 (57%) had no unestablished input anywhere, so
the confidence gate as originally designed would have waved all of them through
regardless of its threshold. ``pages-affected`` had the single highest measured
leverage of any input (how often a wrong value on that field alone flips the
impact band) in that corpus, but its multiplier range (0.3x rare to 5x major) is
wide enough that always-varying it collapses the gate to near-uselessness --
tested at 1/62 bugs passing with every value checked, 29/62 even checking only
the claimed value's immediate neighbors on the severity ladder, and worse still
combined with anything else. Left out of :data:`ALWAYS_VARY` for that reason;
its real fix is ground-truth telemetry (the unmerged commit grounding
pages-affected's tiers in real pageload traffic), not a stability-gate
workaround. ``reproducible`` is varied to its immediate neighbors on its own
3-step ladder (not-reproduced / not-attempted / reproduced) rather than every
value, for the same reason at smaller scale; ``platforms`` is varied the same
way the gate already varies an acknowledged-unestablished ``platforms`` (the
chosen set vs. all four). Combined, this passes 47/62 tier-a-62 bugs as
confident -- see perf-triage-validator/reports/2026-10-26-hackbot-compare-15.md
and harness/attribute_leverage.py for the underlying measurement. Revisit this
list if criteria.md or the corpus it's measured against changes meaningfully.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from performance_tools.calculator import perf_triage as calc

# Selection key, its value prefix, and the calculate_impact parameter it feeds.
_RADIO = {
    "browser-impact": ("browser", "browser-", calc.BROWSER_IMPACT),
    "site-impact": ("site", "site-", calc.SITE_IMPACT),
    "configuration": ("configuration", "scenario-", calc.CONFIGURATION),
    "pageload-impact": ("pageload", "pageload-", calc.PAGELOAD_IMPACT),
    "pages-affected": ("pages", "pages-", calc.PAGES_AFFECTED),
    "resource-impact": ("resource", "resource-", calc.RESOURCE_IMPACT),
    "reproducible": ("reproducible", "reproducible-", calc.REPRODUCIBLE),
}
_BOOLEAN = tuple(calc.ADDITIONAL_FACTORS)  # animation, multiple-sites, ...
INPUTS = frozenset(_RADIO) | {"platforms"} | frozenset(_BOOLEAN)

# Always re-tested regardless of what the skill reports as established -- see the
# module docstring for why and the measurement these are drawn from. Deliberately
# excludes pages-affected (its multiplier range makes an always-vary check too
# blunt -- see the docstring).
ALWAYS_VARY = frozenset({"reproducible", "platforms"})

# reproducible's own severity order, for the adjacent-only variants ALWAYS_VARY
# uses (varying to every value, like an acknowledged-unestablished reproducible
# gets, would be as disruptive here as it is for pages-affected).
_REPRODUCIBLE_LADDER = ("not-reproduced", "not-attempted", "reproduced")


@dataclass(frozen=True)
class CalculatorArgs:
    """``calculate_impact``'s parameters, so ``asdict`` can be splatted into it."""

    platforms: list[str] = field(default_factory=list)
    browser_impact: str = "minor"
    site_impact: str = "minor"
    configuration: str = "general"
    pageload_impact: str = "none"
    pages_affected: str = "common"
    resource_impact: str = "none"
    additional_factors: list[str] = field(default_factory=list)
    reproducible: str = "not-attempted"


@dataclass(frozen=True)
class Stability:
    confident: bool
    bands: frozenset[str]
    flipping: tuple[str, ...]
    unknown: tuple[str, ...]


def _param(name: str) -> str:
    return name.replace("-", "_")


def args_from_selections(selections: dict[str, list[str]]) -> CalculatorArgs:
    """Invert the ``selections`` the calculator reports back into its arguments."""
    values: dict = {
        "platforms": [
            p.removeprefix("platform-") for p in selections.get("platforms", [])
        ],
        "additional_factors": list(selections.get("additional", [])),
    }
    for name, (key, prefix, _) in _RADIO.items():
        chosen = selections.get(key) or []
        if chosen:
            values[_param(name)] = chosen[0].removeprefix(prefix)
    return CalculatorArgs(**values)


def _variants(args: CalculatorArgs, name: str) -> list[CalculatorArgs]:
    if name == "platforms":
        return [args, replace(args, platforms=list(calc.PLATFORMS))]
    if name in _RADIO:
        return [replace(args, **{_param(name): c}) for c in _RADIO[name][2]]
    on = [f for f in args.additional_factors if f != name]
    return [
        replace(args, additional_factors=on),
        replace(args, additional_factors=[*on, name]),
    ]


def _adjacent_variants(args: CalculatorArgs, name: str) -> list[CalculatorArgs]:
    """Gentler than :func:`_variants`: only the claimed value's immediate
    neighbors on its severity ladder, not every value. Used for ALWAYS_VARY
    fields the skill did *not* flag as unestablished -- see the module
    docstring for why the full-range check would be too disruptive there.
    ``platforms`` has no ladder (it's an unordered set with a group cap), so it
    falls back to :func:`_variants`'s chosen-set-vs-all-four check unchanged.
    """
    if name == "platforms":
        return _variants(args, name)
    if name == "reproducible":
        ladder = _REPRODUCIBLE_LADDER
        current = args.reproducible
    else:
        return _variants(args, name)
    i = ladder.index(current) if current in ladder else len(ladder) // 2
    neighbors = {current}
    if i > 0:
        neighbors.add(ladder[i - 1])
    if i < len(ladder) - 1:
        neighbors.add(ladder[i + 1])
    return [replace(args, **{_param(name): v}) for v in neighbors]


def _band(args: CalculatorArgs) -> str:
    return calc.calculate_impact(**args.__dict__)[1]


def _bands(
    args: CalculatorArgs, names: Sequence[str], *, adjacent_only: frozenset[str] = frozenset()
) -> set[str]:
    combos = [args]
    for name in names:
        variants = _adjacent_variants if name in adjacent_only else _variants
        combos = [v for c in combos for v in variants(c, name)]
    return {_band(c) for c in combos}


def check_stability(
    selections: dict[str, list[str]], unestablished: Sequence[str]
) -> Stability:
    """Re-score every combination of the unestablished inputs' values, plus
    :data:`ALWAYS_VARY` for whichever of those the skill did not already name as
    unestablished (those get the gentler adjacent-only check; see the module
    docstring)."""
    args = args_from_selections(selections)
    acknowledged = list(dict.fromkeys(unestablished))
    always_vary_only = [n for n in ALWAYS_VARY if n not in acknowledged]
    names = [*acknowledged, *always_vary_only]
    unknown = tuple(n for n in acknowledged if n not in INPUTS)
    known = [
        n
        for n in names
        if n in INPUTS
        and not (n == "reproducible" and args.reproducible == "not-attempted")
    ]
    adjacent_only = frozenset(n for n in always_vary_only if n in known)
    bands = _bands(args, known, adjacent_only=adjacent_only)
    flipping = tuple(
        n for n in known if len(_bands(args, [n], adjacent_only=adjacent_only)) > 1
    )
    return Stability(
        confident=len(bands) == 1 and not unknown,
        bands=frozenset(bands),
        flipping=flipping,
        unknown=unknown,
    )


def input_label(name: str) -> str:
    """The calculator's own label for an input, as engineers see it in its comment."""
    if name == "platforms":
        return calc.SECTION_HEADERS["platforms"].rstrip(":")
    if name in _RADIO:
        return calc.SECTION_HEADERS[_RADIO[name][0]].rstrip(":")
    return calc.LABELS.get(name, name)


def value_label(name: str, value: object) -> str:
    """The calculator's label for one value of an input."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if name in _RADIO:
        return calc.LABELS.get(f"{_RADIO[name][1]}{value}", str(value))
    if name == "platforms" and isinstance(value, list):
        return ", ".join(calc.LABELS.get(f"platform-{p}", p) for p in value)
    return str(value)


def emittable_keywords() -> frozenset[str]:
    """Every keyword the vendored calculator can emit: the write allow-list."""
    tables = [
        calc.BROWSER_IMPACT,
        calc.SITE_IMPACT,
        calc.CONFIGURATION,
        calc.PAGELOAD_IMPACT,
        calc.PAGES_AFFECTED,
        calc.RESOURCE_IMPACT,
        calc.REPRODUCIBLE,
        calc.ADDITIONAL_FACTORS,
    ]
    return frozenset(
        k for t in tables for entry in t.values() for k in entry.get("keywords", ())
    )


__all__ = [
    "CalculatorArgs",
    "INPUTS",
    "Stability",
    "args_from_selections",
    "check_stability",
    "emittable_keywords",
    "input_label",
    "value_label",
]
