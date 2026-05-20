"""timetable_scheduler.engine.renderer

Clean timetable rendering - no elective window texts, visual-only slot classification.
"""

from __future__ import annotations

from .constraint_utils import get_recourse_blocked_slots
from .models import (
    Assignment,
    DAYS,
    EngineResult,
    PERIODS,
    SLOTS_PER_DAY,
    slot_to_day_period,
    ItemType,
)
from .scheduler import ScheduleState


def _empty_grid() -> list[list[list[Assignment]]]:
    """Create empty grid: 5 days x 8 periods, each cell is a list of assignments."""
    return [[[] for _ in range(SLOTS_PER_DAY)] for _ in range(5)]


def renderTimetable(*, state: ScheduleState, constraints, included_semesters: list[str]) -> EngineResult:
    """Render clean timetable with visual slot classification (no text labels)."""
    debug: list[str] = []
    semester_tts: dict[str, list[list[list[Assignment]]]] = {}

    # Build recourse-sensitive blocked slots map
    recourse_blocked = get_recourse_blocked_slots(
        state=state, constraints=constraints, included_semesters=included_semesters
    )

    # Semester-wise rendering
    for sem in included_semesters:
        grid = _empty_grid()
        occupied_count = 0
        elective_available_count = 0
        recourse_blocked_count = 0

        # First pass: place all real assignments
        for slot, assns in state.by_semester.get(sem, {}).items():
            d, p = slot_to_day_period(slot)
            for a in assns:
                if a.item_type != ItemType.WINDOW:  # Skip old window placeholders
                    grid[d][p].append(a)
                    occupied_count += 1

        # Second pass: classify empty slots
        blocked_slots = recourse_blocked.get(sem, set())
        for d in range(5):
            for p in range(SLOTS_PER_DAY):
                if not grid[d][p]:  # Empty slot
                    slot = d * SLOTS_PER_DAY + p

                    if slot in blocked_slots:
                        # Recourse blocked - subtle marker, no text
                        placeholder = Assignment(
                            event_id=f"recourse_blocked:{sem}:{slot}",
                            item_type=ItemType.WINDOW,
                            name="",  # No text
                            faculty="",
                            semesters=(sem,),
                        )
                        grid[d][p].append(placeholder)
                        recourse_blocked_count += 1
                    else:
                        # Elective available - visual marker only, no text
                        placeholder = Assignment(
                            event_id=f"elective_available:{sem}:{slot}",
                            item_type=ItemType.WINDOW,
                            name="",  # No text - visual only
                            faculty="",
                            semesters=(sem,),
                        )
                        grid[d][p].append(placeholder)
                        elective_available_count += 1

        semester_tts[sem] = grid
        debug.append(f"{sem}: {occupied_count} occupied, {elective_available_count} elective-available, {recourse_blocked_count} recourse-blocked")

    # Faculty-wise generation removed
    faculty_grids: dict[str, list[list[list[Assignment]]]] = {}

    # Build combined timetable view
    combined = _empty_grid()
    combined_occupied = 0
    combined_elective = 0

    for sem in included_semesters:
        for slot, assns in state.by_semester.get(sem, {}).items():
            d, p = slot_to_day_period(slot)
            existing_ids = {a.event_id for a in combined[d][p]}
            for a in assns:
                if a.item_type != ItemType.WINDOW and a.event_id not in existing_ids:
                    combined[d][p].append(a)
                    existing_ids.add(a.event_id)
                    combined_occupied += 1

    # Mark combined empty slots as elective-available (combined view)
    for d in range(5):
        for p in range(SLOTS_PER_DAY):
            if not combined[d][p]:
                slot = d * SLOTS_PER_DAY + p
                placeholder = Assignment(
                    event_id=f"elective_available:combined:{slot}",
                    item_type=ItemType.WINDOW,
                    name="",  # No text
                    faculty="",
                    semesters=(),
                )
                combined[d][p].append(placeholder)
                combined_elective += 1

    debug.append(f"Combined: {combined_occupied} occupied, {combined_elective} elective-available")

    return EngineResult(
        success=True,
        semester_timetables=semester_tts,
        faculty_timetables=faculty_grids,
        combined_timetable=combined,
        errors=[],
        debug=debug,
    )
