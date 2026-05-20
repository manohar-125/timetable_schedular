"""timetable_scheduler.engine.pipeline

End-to-end pipeline:
- parseSemesterData
- buildConstraints
- scheduleLabs/scheduleElectives/scheduleCoreSubjects (implemented by scheduler module)
- validateTimetable
- renderTimetable

The entrypoint is `generate_from_ui_state()`.
"""

from __future__ import annotations

from typing import Any, Mapping

from .constraints import buildConstraints
from .parser import parse_ui_state
from .renderer import renderTimetable
from .scheduler import schedule, generate_elective_windows
from .validator import validateTimetable
from .models import EngineResult


def generate_from_ui_state(
    ui_state: Mapping[str, Any],
    *,
    max_restarts: int = 200,
    seed: int | None = None,
) -> EngineResult:
    parsed = parse_ui_state(ui_state, ignore_imtech=False)
    debug: list[str] = []

    # Log ignored semesters (explicitly not included)
    all_semesters = list((ui_state.get('semesterData') or {}).keys())
    ignored = [s for s in all_semesters if s not in parsed.included_semesters]
    if ignored:
        debug.append(f"Ignored semesters (not included): {', '.join(sorted(ignored))}")

    constraints = buildConstraints(
        cycle=str(ui_state.get("cycle", "odd")),
        teacherAvailability=(ui_state.get("teacherAvailability") or {}),
    )

    included = parsed.included_semesters

    # If nothing included, return error
    if not included:
        return EngineResult(
            success=False,
            semester_timetables={},
            faculty_timetables={},
            errors=["No semesters selected for generation in the current cycle."],
        )

    state, sched_errors = schedule(
        included_semesters=included,
        events=parsed.events,
        constraints=constraints,
        max_restarts=max_restarts,
        per_restart_shuffle_seed=seed,
    )

    if not state:
        res = EngineResult(
            success=False,
            semester_timetables={},
            faculty_timetables={},
            errors=sched_errors,
        )
        res.debug = debug
        return res

    # === Generate elective windows in free slots ===
    generate_elective_windows(state=state, constraints=constraints, included_semesters=included)
    debug.append("Generated elective windows in free slots for each semester.")

    validation_errors, validation_warnings = validateTimetable(
        state=state,
        constraints=constraints,
        included_semesters=included,
    )

    if validation_errors:
        res = EngineResult(
            success=False,
            semester_timetables={},
            faculty_timetables={},
            errors=validation_errors,
        )
        res.debug = debug
        return res

    result = renderTimetable(state=state, constraints=constraints, included_semesters=included)
    # merge pipeline debug hints
    result.debug = (result.debug or []) + debug + (validation_warnings or [])
    return result
