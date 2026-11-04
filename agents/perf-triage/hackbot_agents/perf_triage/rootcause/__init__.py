"""Root-cause analysis (step 4): read a bug's profile, say where the time goes.

Runs after classification, and only when classification recorded a profile:
``PerfTestPlanResult.profile`` is the routing input. The analysis itself is
done through the vendored ``profiler-analysis`` skill, which is enabled via
``ClaudeAgentOptions.skills`` rather than reimplemented here.
"""

from hackbot_agents.perf_triage.rootcause.prompt import ROOT_CAUSE_TASK_DETAILS
from hackbot_agents.perf_triage.rootcause.result import (
    Confidence,
    Outcome,
    RootCauseResult,
)
from hackbot_agents.perf_triage.rootcause.task import (
    SKILL_NAME,
    RootCause,
    reference_points,
)

__all__ = [
    "ROOT_CAUSE_TASK_DETAILS",
    "SKILL_NAME",
    "Confidence",
    "Outcome",
    "RootCause",
    "RootCauseResult",
    "reference_points",
]
