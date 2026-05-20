"""timetable_scheduler.engine.validator

Validates a finished schedule for required constraints.

The scheduler already enforces most constraints incrementally, but we validate
again to produce readable error messages and to guard against regressions.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .constraint_utils import (
    validate_lab_constraints,
    validate_teacher_constraints,
    validate_subject_repetition,
    get_recourse_blocked_slots,
)
from .constants import LUNCH_BOUNDARY_PERIOD_INDEX, RECOURSE_TARGETS
from .models import (
    Assignment,
    Constraints,
    DAYS,
    ItemType,
    PERIODS,
    SLOTS_PER_DAY,
    TOTAL_SLOTS,
    slot_to_day_period,
)
from .scheduler import ScheduleState


def _iter_semester_day_slots(day_index: int) -> Iterable[int]:
    base = day_index * SLOTS_PER_DAY
    return range(base, base + SLOTS_PER_DAY)


def _validate_no_same_semester_overlaps(
    state: ScheduleState,
    included_semesters: list[str],
) -> list[str]:
    """CRITICAL: Validate that no semester has more than one assignment per slot.
    
    This is a hard constraint that prevents:
    - Two labs of same semester at overlapping times
    - A lab overlapping with core/recourse/elective of same semester
    - Any multi-assignment per semester per slot
    
    This serves as a safety net against the lab overlap bug.
    
    Args:
        state: Current schedule state
        included_semesters: List of semesters to validate
        
    Returns:
        List of error messages for any violations
    """
    errors: list[str] = []
    
    for sem in included_semesters:
        for slot, assns in state.by_semester.get(sem, {}).items():
            if len(assns) > 1:
                d, p = slot_to_day_period(slot)
                # Detailed error with all conflicting assignments
                assignment_list = []
                for a in assns:
                    item_type = "LAB" if a.item_type == ItemType.LAB else str(a.item_type)
                    assignment_list.append(f"{a.name}({item_type})")
                
                conflicts = ", ".join(assignment_list)
                errors.append(
                    f"CRITICAL VALIDATION FAILURE: {sem} has {len(assns)} simultaneous assignments at "
                    f"{DAYS[d]} {PERIODS[p]}: {conflicts}"
                )
    
    return errors


def _iter_semester_day_slots(day_index: int) -> Iterable[int]:
    base = day_index * SLOTS_PER_DAY
    return range(base, base + SLOTS_PER_DAY)


def validateTimetable(
    *,
    state: ScheduleState,
    constraints: Constraints,
    included_semesters: list[str],
 ) -> tuple[list[str], list[str]]:
    """Validate timetable using centralized constraint functions."""
    errors: list[str] = []
    warnings: list[str] = []

    # Use centralized validation functions
    errors.extend(validate_lab_constraints(state, included_semesters))
    errors.extend(validate_teacher_constraints(state, constraints, included_semesters))
    errors.extend(validate_subject_repetition(state, included_semesters))
    
    # CRITICAL: Add strict same-semester overlap validation for all event types
    errors.extend(_validate_no_same_semester_overlaps(state, included_semesters))

    # ---- Recourse conflicts (warnings only) ----
    # For each source semester with recourse-enabled offerings, ensure they do not overlap target semesters.
    for source_sem, targets in constraints.recourse_targets.items():
        if source_sem not in state.by_semester:
            continue
        source_slots = set()
        for slot, assns in state.by_semester[source_sem].items():
            for a in assns:
                if source_sem in set(a.recourse_sources):
                    source_slots.add(slot)
        
        for target_sem in targets:
            if target_sem not in state.by_semester:
                continue
            target_slots = set(state.by_semester[target_sem].keys())
            overlap = sorted(source_slots & target_slots)
            if overlap:
                d, p = slot_to_day_period(overlap[0])
                warnings.append(
                    f"Recourse clash: {source_sem} recourse-enabled offerings overlap {target_sem} at {DAYS[d]} {PERIODS[p]}."
                )

    # ---- Validate credit splitting correctness ----
    # Check that 3-credit courses use [2,1] and 4-credit use valid patterns
    for sem in included_semesters:
        # Group assignments by event_id to count blocks per course
        event_blocks: dict[str, list[int]] = defaultdict(list)
        event_credits: dict[str, int] = {}
        event_names: dict[str, str] = {}
        
        for slot, assns in state.by_semester.get(sem, {}).items():
            for a in assns:
                if a.item_type == ItemType.CORE:
                    event_blocks[a.event_id].append(slot)
                    event_credits[a.event_id] = getattr(a, 'credits', 3)
                    event_names[a.event_id] = a.name
        
        # Validate block structure for each course
        for event_id, slots in event_blocks.items():
            credits = event_credits.get(event_id, 3)
            name = event_names.get(event_id, "Unknown")
            
            # Group slots into contiguous blocks
            slots_sorted = sorted(slots)
            blocks: list[list[int]] = []
            current_block: list[int] = []
            
            for slot in slots_sorted:
                if not current_block or slot == current_block[-1] + 1:
                    current_block.append(slot)
                else:
                    blocks.append(current_block)
                    current_block = [slot]
            if current_block:
                blocks.append(current_block)
            
            # Check block sizes match expected pattern
            block_sizes = [len(b) for b in blocks]
            
            if credits == 3:
                # 3-credit must be [2, 1]
                if block_sizes != [2, 1] and block_sizes != [1, 2]:
                    errors.append(
                        f"{sem} {name}: 3-credit course has wrong block structure {block_sizes}, expected [2,1]"
                    )
            elif credits == 4:
                # 4-credit must be [2, 2] or [2, 1, 1]
                if block_sizes not in [[2, 2], [2, 1, 1], [1, 2, 1], [1, 1, 2]]:
                    errors.append(
                        f"{sem} {name}: 4-credit course has wrong block structure {block_sizes}, expected [2,2] or [2,1,1]"
                    )
            
            # Check no 2-period block crosses lunch boundary
            for block in blocks:
                if len(block) == 2:
                    day, start_period = slot_to_day_period(block[0])
                    end_period = start_period + 1
                    # Check if block crosses lunch (P4-P5 boundary)
                    if start_period < LUNCH_BOUNDARY_PERIOD_INDEX <= end_period:
                        errors.append(
                            f"{sem} {name}: 2-period block crosses lunch break at {DAYS[day]}"
                        )

    return errors, warnings
