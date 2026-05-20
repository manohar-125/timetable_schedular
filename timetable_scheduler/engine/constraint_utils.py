"""timetable_scheduler.engine.constraint_utils

Centralized constraint checking functions for timetable scheduling.

This module provides reusable functions to avoid scattered constraint logic
across multiple modules. All constraint checks should use these functions
to ensure consistency.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from .constants import (
    DAYS,
    PERIODS,
    SLOTS_PER_DAY,
    TOTAL_SLOTS,
    LAB_BLOCK_SIZE,
    LAB_VALID_START_PERIODS,
    MAX_LABS_PER_SLOT,
    RECOURSE_TARGETS,
)
from .models import (
    Assignment,
    Constraints,
    ItemType,
    slot_to_day_period,
)

# Forward declaration to avoid circular imports
class ScheduleState:
    pass


def is_teacher_available(constraints: Constraints, teacher: str, slot: int) -> bool:
    """Check if a teacher is available at a specific slot.
    
    Args:
        constraints: Constraint configuration
        teacher: Teacher name/ID
        slot: Time slot index (0-39)
        
    Returns:
        True if teacher is available, False if forbidden
    """
    forbidden = constraints.teacher_forbidden.get(teacher)
    if not forbidden:
        return True
    return slot not in forbidden


def is_slot_blocked_by_recourse(
    state: ScheduleState,
    constraints: Constraints,
    slot: int,
    event_semesters: Set[str],
    event_recourse_sources: Set[str],
) -> Tuple[bool, str]:
    """Check if a slot is blocked due to recourse constraints.
    
    This centralized function handles both forward and reverse recourse blocking:
    - Forward: If this event offers recourse, ensure no target semesters occupy the slot
    - Reverse: If existing assignments offer recourse, ensure they don't target this event's semesters
    
    Args:
        state: Current schedule state
        constraints: Constraint configuration
        slot: Time slot index to check
        event_semesters: Set of semesters for the event being placed
        event_recourse_sources: Set of recourse source semesters for the event
        
    Returns:
        Tuple of (is_blocked, reason_string)
    """
    # Forward recourse blocking: this event offers recourse for its source semesters
    for src in event_recourse_sources:
        targets = constraints.recourse_targets.get(src, set())
        for tgt in targets:
            if tgt in state.by_semester and state.by_semester.get(tgt, {}).get(slot):
                assns = state.by_semester.get(tgt, {}).get(slot, [])
                occ = ", ".join(sorted({f"{a.name}({','.join(a.semesters)})" for a in assns}))
                return True, f"recourse would overlap existing assignment in target semester {tgt}: {occ}"

    # Reverse recourse blocking: existing assignments may target this event's semesters
    for other_sem, slots_map in state.by_semester.items():
        assns = slots_map.get(slot, [])
        if not assns:
            continue
        for a in assns:
            for src in a.recourse_sources:
                targets = constraints.recourse_targets.get(src, set())
                if any(ts in targets for ts in event_semesters):
                    return True, f"recourse reserved for semester(s) {', '.join(sorted(event_semesters))} by {a.name} ({src})"

    return False, ""


def can_place_lab(
    state: ScheduleState,
    start_slot: int,
    block_size: int,
) -> Tuple[bool, str]:
    """Check if a lab can be placed following all lab-specific constraints.

    Valid lab start periods (0-indexed): 0 (P1), 1 (P2), 4 (P5), 5 (P6).
    This gives windows P1-P3, P2-P4, P5-P7, P6-P8.
    P3-P5 and P4-P6 are invalid because they cross the lunch boundary.

    Args:
        state: Current schedule state
        start_slot: Starting time slot index
        block_size: Size of the lab block
        
    Returns:
        Tuple of (can_place, reason_string)
    """
    if block_size != LAB_BLOCK_SIZE:
        return False, f"invalid lab block size (must be {LAB_BLOCK_SIZE})"
    
    day, period = slot_to_day_period(start_slot)
    if period not in LAB_VALID_START_PERIODS:
        return False, f"invalid lab start period (must be P1, P2, P5, or P6)"
    
    # Check lab capacity constraint
    for slot in range(start_slot, start_slot + block_size):
        if state.lab_count_at_slot.get(slot, 0) >= MAX_LABS_PER_SLOT:
            d, p = slot_to_day_period(slot)
            return False, f"global lab capacity exceeded at {DAYS[d]} {PERIODS[p]} (max {MAX_LABS_PER_SLOT})"
    
    return True, ""


def can_place_lab_with_semester_check(
    state: ScheduleState,
    start_slot: int,
    block_size: int,
    event_semesters: Set[str],
) -> Tuple[bool, str]:
    """Check if a lab can be placed without causing same-semester overlaps.
    
    This function enforces the critical rule: a semester can NEVER have two labs
    at overlapping time slots. This prevents students from attending two labs simultaneously.
    
    Args:
        state: Current schedule state
        start_slot: Starting time slot index
        block_size: Size of the lab block (must be LAB_BLOCK_SIZE)
        event_semesters: Set of semesters attending this lab
        
    Returns:
        Tuple of (can_place, reason_string)
    """
    # Check each slot in the block for same-semester lab conflicts
    for slot in range(start_slot, start_slot + block_size):
        for sem in event_semesters:
            # Get all assignments already in this slot for this semester
            if slot in state.by_semester.get(sem, {}):
                assns = state.by_semester.get(sem, {}).get(slot, [])
                # Check if any of them are labs (labs can't overlap with other labs same semester)
                for assn in assns:
                    if assn.item_type == ItemType.LAB:
                        d, p = slot_to_day_period(slot)
                        return False, f"same-semester lab overlap: {sem} already has lab '{assn.name}' at {DAYS[d]} {PERIODS[p]}"
    
    return True, ""


def can_place_core(
    state: ScheduleState,
    slot: int,
    event_name: str,
    event_semesters: Set[str],
) -> Tuple[bool, str]:
    """Check if a core subject can be placed following core-specific constraints.
    
    Args:
        state: Current schedule state
        slot: Time slot index to check
        event_name: Name of the event being placed
        event_semesters: Set of semesters for the event
        
    Returns:
        Tuple of (can_place, reason_string)
    """
    # Check student clashes: slot must be free for every attending semester
    for sem in event_semesters:
        if slot in state.by_semester.get(sem, {}):
            assns = state.by_semester.get(sem, {}).get(slot, [])
            if assns:
                occ = ", ".join(sorted({f"{a.name}({','.join(a.semesters)})" for a in assns}))
                return False, f"student clash in semester {sem}: occupied by {occ}"
    
    # Check subject repetition on same day
    day, _ = slot_to_day_period(slot)
    for sem in event_semesters:
        if event_name in state.subject_on_day[sem][day]:
            return False, f"subject repetition on the same day ({sem} {DAYS[day]})"
    
    return True, ""


def get_recourse_blocked_slots(
    state: ScheduleState,
    constraints: Constraints,
    included_semesters: List[str],
) -> Dict[str, Set[int]]:
    """Get all slots blocked by recourse constraints for each semester.
    
    Args:
        state: Current schedule state
        constraints: Constraint configuration
        included_semesters: List of semesters to check
        
    Returns:
        Dictionary mapping semester -> set of blocked slot indices
    """
    blocked: Dict[str, Set[int]] = {sem: set() for sem in included_semesters}
    
    # Use centralized recourse mapping
    recourse_targets = RECOURSE_TARGETS
    
    # For each source semester with recourse-enabled offerings
    for source_sem, target_sems in recourse_targets.items():
        if source_sem not in state.by_semester:
            continue
        
        # Find all slots in source_sem that have recourse-enabled assignments
        recourse_slots = set()
        for slot, assns in state.by_semester[source_sem].items():
            for a in assns:
                if source_sem in set(a.recourse_sources):
                    recourse_slots.add(slot)
        
        # Mark these slots as blocked for all target semesters
        for target_sem in target_sems:
            if target_sem in blocked:
                blocked[target_sem].update(recourse_slots)
    
    return blocked


def validate_lab_constraints(
    state: ScheduleState,
    included_semesters: List[str],
) -> List[str]:
    """Validate all lab constraints across the schedule.
    
    Args:
        state: Current schedule state
        included_semesters: List of semesters to validate
        
    Returns:
        List of validation error messages
    """
    errors: List[str] = []
    
    # Check global lab capacity
    for slot, count in state.lab_count_at_slot.items():
        if count > MAX_LABS_PER_SLOT:
            d, p = slot_to_day_period(slot)
            errors.append(f"Lab overlap exceeded: {count} labs at {DAYS[d]} {PERIODS[p]} (max {MAX_LABS_PER_SLOT})")
    
    # Check individual lab placements
    for sem in included_semesters:
        for day in range(5):
            base = day * SLOTS_PER_DAY
            day_slots = range(base, base + SLOTS_PER_DAY)
            
            lab_marks = []
            for s in day_slots:
                assns = state.by_semester[sem].get(s, [])
                lab_assn = next((a for a in assns if a.item_type == ItemType.LAB), None)
                lab_marks.append(lab_assn)

            # Find lab segments
            idx = 0
            while idx < len(lab_marks):
                if not lab_marks[idx]:
                    idx += 1
                    continue
                name = lab_marks[idx].name
                start = idx
                while idx < len(lab_marks) and lab_marks[idx] and lab_marks[idx].name == name:
                    idx += 1
                end = idx  # exclusive
                length = end - start
                
                if length != LAB_BLOCK_SIZE:
                    errors.append(f"Invalid lab length: {sem} '{name}' on {DAYS[day]} spans {length} periods (must be {LAB_BLOCK_SIZE})")
                if start not in LAB_VALID_START_PERIODS:
                    errors.append(f"Invalid lab placement: {sem} '{name}' on {DAYS[day]} must start at P1, P2, P5, or P6")
    
    return errors


def validate_teacher_constraints(
    state: ScheduleState,
    constraints: Constraints,
    included_semesters: List[str],
) -> List[str]:
    """Validate teacher availability and clash constraints.
    
    Args:
        state: Current schedule state
        constraints: Constraint configuration
        included_semesters: List of semesters to validate
        
    Returns:
        List of validation error messages
    """
    errors: List[str] = []
    
    # Check teacher clashes
    teacher_to_slots: Dict[str, Dict[int, List[Tuple[str, Assignment]]]] = {}
    
    for sem in included_semesters:
        for slot, assns in state.by_semester[sem].items():
            for assn in assns:
                # Skip elective windows from teacher clash check
                if assn.item_type == ItemType.WINDOW:
                    continue
                    
                if assn.faculty not in teacher_to_slots:
                    teacher_to_slots[assn.faculty] = {}
                if slot not in teacher_to_slots[assn.faculty]:
                    teacher_to_slots[assn.faculty][slot] = []
                teacher_to_slots[assn.faculty][slot].append((sem, assn))

    for teacher, slots_map in teacher_to_slots.items():
        for slot, items in slots_map.items():
            # If same assignment shared across semesters, that's fine for combined electives
            unique_event_ids = {a.event_id for _, a in items}
            if len(unique_event_ids) <= 1:
                continue
            d, p = slot_to_day_period(slot)
            errors.append(
                f"Teacher clash: {teacher} has multiple classes at {DAYS[d]} {PERIODS[p]}: "
                + ", ".join(sorted({f"{sem}({a.name})" for sem, a in items}))
            )

    # Check teacher availability violations
    for sem in included_semesters:
        for slot, assns in state.by_semester[sem].items():
            for assn in assns:
                # Skip elective windows
                if assn.item_type == ItemType.WINDOW:
                    continue
                if not is_teacher_available(constraints, assn.faculty, slot):
                    d, p = slot_to_day_period(slot)
                    errors.append(f"Teacher availability violated: {assn.faculty} scheduled at {DAYS[d]} {PERIODS[p]} ({sem} {assn.name})")
    
    return errors


def validate_subject_repetition(
    state: ScheduleState,
    included_semesters: List[str],
) -> List[str]:
    """Validate that subjects don't repeat multiple times on the same day.
    
    Args:
        state: Current schedule state
        included_semesters: List of semesters to validate
        
    Returns:
        List of validation error messages
    """
    errors: List[str] = []
    
    for sem in included_semesters:
        for day in range(5):
            base = day * SLOTS_PER_DAY
            day_slots = range(base, base + SLOTS_PER_DAY)
            
            row = [state.by_semester[sem].get(slot, []) for slot in day_slots]
            
            # Count segments per subject
            segments: Dict[str, int] = {}
            prev_names = set()
            for assns in row:
                names = {a.name for a in assns if a.item_type != ItemType.WINDOW} if assns else set()
                # Skip elective windows from this check
                for name in names - prev_names:
                    segments[name] = segments.get(name, 0) + 1
                prev_names = names
                
            for subj, seg_count in segments.items():
                if seg_count > 1:
                    errors.append(f"Same-subject repetition: {sem} has '{subj}' multiple times on {DAYS[day]}")
    
    return errors
