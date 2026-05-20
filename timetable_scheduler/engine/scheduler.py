"""timetable_scheduler.engine.scheduler

DFS Backtracking timetable scheduling with constraint diagnostics.

Strategy:
1) Sort events: Labs first, Recourse-enabled cores, Regular cores, Elective windows.
2) Use DFS to explore placements.
3) Backtrack on failures.
4) Collect detailed diagnostics on why placements fail.

This module focuses on placement; validation lives in validator.py.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Iterable

from copy import deepcopy

from .constants import (
    DAYS,
    PERIODS,
    SLOTS_PER_DAY,
    TOTAL_SLOTS,
    LAB_BLOCK_SIZE,
    LAB_VALID_START_PERIODS,
    MAX_LABS_PER_SLOT,
    CREDIT_BLOCK_MAPPING,
    CREDIT_4_ALTERNATIVES,
    DEFAULT_BLOCK_PATTERN,
    RECOURSE_TARGETS,
    MAX_ITERATIONS,
    MAX_BACKTRACK_DEPTH,
)
from .models import (
    Assignment,
    Constraints,
    Event,
    ItemType,
    block_fits_time_contiguity,
    iter_slots_for_block,
    slot_to_day_period,
)
from .constraint_utils import is_teacher_available


@dataclass
class ScheduleState:
    # semester -> slot -> list of assignments (for parallel electives)
    by_semester: dict[str, dict[int, list[Assignment]]]

    # teacher -> occupied slots
    teacher_usage: dict[str, set[int]]

    # semester -> dayIndex -> set(subjects already scheduled that day)
    subject_on_day: dict[str, dict[int, set[str]]]

    # global: slot -> number of labs scheduled in this slot
    lab_count_at_slot: dict[int, int]

    # event_id -> number of blocks placed (for backtracking cleanup)
    event_block_count: dict[str, int]
    
    # event_id -> set of slots already placed for this event (to prevent adjacent blocks)
    event_placed_slots: dict[str, set[int]]



@dataclass
class DiagnosticTracker:
    # event_name -> slot -> reason
    rejections: dict[str, dict[int, str]] = field(default_factory=dict)
    
    # event_name -> total rejections count (for sorting)
    rejection_counts: dict[str, int] = field(default_factory=dict)

    deepest_depth: int = 0
    deepest_event_id: str | None = None
    # optional detailed traces for specific events
    traces: list[str] = field(default_factory=list)

    def add_rejection(self, event_name: str, slot: int, reason: str):
        if event_name not in self.rejections:
            self.rejections[event_name] = {}
        self.rejections[event_name][slot] = reason
        self.rejection_counts[event_name] = self.rejection_counts.get(event_name, 0) + 1

    def add_trace(self, msg: str):
        self.traces.append(msg)

    # recourse conflict aggregation: event_name -> target_sem -> count
    recourse_conflicts: dict[str, dict[str, int]] = field(default_factory=dict)
    # short examples per event
    recourse_examples: dict[str, list[str]] = field(default_factory=dict)

    def generate_report(self) -> list[str]:
        report = []
        report.append("--- Constraint Diagnostics Report ---")
        
        if self.deepest_event_id:
            report.append(f"Deepest search reached event: {self.deepest_event_id} before backtracking failed completely.")
            
        report.append("\nTop blocked subjects:")
        sorted_counts = sorted(self.rejection_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        for name, count in sorted_counts:
            report.append(f" - {name}: Rejected {count} times")
            
            # Show a sample of reasons for this subject
            reasons = {}
            for slot, reason in self.rejections.get(name, {}).items():
                reasons[reason] = reasons.get(reason, 0) + 1
            for reason, rcount in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
                report.append(f"     -> {reason} ({rcount} slots)")
        if self.traces:
            report.append('\nDetailed traces:')
            report.extend(self.traces[:200])
        # Recourse conflict aggregation (soft diagnostic)
        if self.recourse_conflicts:
            report.append('\nRecourse conflict summary:')
            # sort by total conflicts desc
            items = sorted(self.recourse_conflicts.items(), key=lambda kv: -sum(kv[1].values()))
            for event_name, targets in items:
                total = sum(targets.values())
                report.append(f" - {event_name}: {total} recourse overlaps recorded")
                for tgt, cnt in sorted(targets.items(), key=lambda x: -x[1]):
                    report.append(f"     -> {tgt}: {cnt}")
                exs = self.recourse_examples.get(event_name, [])
                for ex in exs[:3]:
                    report.append(f"       example: {ex}")
                
        return report


def _empty_state(included_semesters: Iterable[str]) -> ScheduleState:
    return ScheduleState(
        by_semester={s: {} for s in included_semesters},
        teacher_usage={},
        subject_on_day={s: {d: set() for d in range(5)} for s in included_semesters},
        lab_count_at_slot={s: 0 for s in range(TOTAL_SLOTS)},
        event_block_count={},
        event_placed_slots={},
    )


def can_place_core_self_aware(
    state: ScheduleState,
    slot: int,
    event_name: str,
    event_semesters: set[str],
    already_placed_slots: set[int],
) -> tuple[bool, str]:
    """Check if a core subject can be placed, ignoring self-clash with already placed slots of same event."""
    # Check student clashes: slot must be free for every attending semester
    # BUT ignore if the slot is already occupied by this same event (self-clash allowance)
    for sem in event_semesters:
        if slot in state.by_semester.get(sem, {}):
            assns = state.by_semester.get(sem, {}).get(slot, [])
            # Filter out assignments from this same event
            other_assns = [a for a in assns if a.event_id != event_name and a.name != event_name]
            if other_assns:
                occ = ", ".join(sorted({f"{a.name}({','.join(a.semesters)})" for a in other_assns}))
                return False, f"student clash in semester {sem}: occupied by {occ}"

    # Check subject repetition on same day (still applies)
    day, _ = slot_to_day_period(slot)
    for sem in event_semesters:
        # Only check if this specific slot hasn't been placed by this event already
        if slot not in already_placed_slots:
            if event_name in state.subject_on_day[sem][day]:
                return False, f"subject repetition on the same day ({sem} {DAYS[day]})"

    return True, ""


def _can_place_event_block(
    *,
    state: ScheduleState,
    constraints: Constraints,
    event: Event,
    start_slot: int,
    block_size: int,
    is_first_block: bool = False,
) -> tuple[bool, str]:
    if not block_fits_time_contiguity(start_slot, block_size):
        return False, "does not fit time contiguity (crosses lunch or day)"

    # Check lab-specific constraints
    if event.item_type == ItemType.LAB:
        can_lab, lab_reason = can_place_lab(state, start_slot, block_size)
        if not can_lab:
            return False, lab_reason
        
        # CRITICAL FIX: Check for same-semester lab overlaps (prevents two labs same semester at overlapping times)
        can_lab_sem, lab_sem_reason = can_place_lab_with_semester_check(
            state, start_slot, block_size, event.semesters
        )
        if not can_lab_sem:
            return False, lab_sem_reason

    # Check each slot in the block
    for slot in iter_slots_for_block(start_slot, block_size):
        # Check recourse constraints
        recourse_blocked, recourse_reason = is_slot_blocked_by_recourse(
            state, constraints, slot, event.semesters, event.recourse_sources
        )
        if recourse_blocked:
            return False, recourse_reason

        # Check core constraints for non-lab events
        if event.item_type != ItemType.LAB:
            # For multi-block events, ignore self-clash with already placed slots of same event
            already_placed = state.event_placed_slots.get(event.event_id, set())
            can_core, core_reason = can_place_core_self_aware(
                state, slot, event.name, event.semesters, already_placed
            )
            if not can_core:
                return False, core_reason

        # Teacher availability and clash
        if not is_teacher_available(constraints, event.faculty, slot):
            return False, f"teacher {event.faculty} unavailable (user constraint)"
        if slot in state.teacher_usage.get(event.faculty, set()):
            return False, f"teacher {event.faculty} already occupied with another class"

        # Lab concurrency constraint (already checked in can_place_lab, but keep for safety)
        if event.item_type == ItemType.LAB:
            if state.lab_count_at_slot.get(slot, 0) >= MAX_LABS_PER_SLOT:
                return False, f"global lab capacity exceeded (max {MAX_LABS_PER_SLOT})"

    # For non-first blocks of the same event: prevent adjacency to already placed blocks
    # This prevents [2,1] from becoming [3] when placed adjacent
    if not is_first_block and event.item_type != ItemType.LAB:
        already_placed = state.event_placed_slots.get(event.event_id, set())
        if already_placed:
            for slot in iter_slots_for_block(start_slot, block_size):
                # Check if any slot is adjacent to already placed slots (would merge blocks)
                for placed_slot in already_placed:
                    placed_day = placed_slot // SLOTS_PER_DAY
                    slot_day = slot // SLOTS_PER_DAY
                    if placed_day == slot_day and abs(placed_slot - slot) == 1:
                        return False, "would become adjacent to already placed block of same course"

    return True, ""


def can_place_lab(
    state: ScheduleState,
    start_slot: int,
    block_size: int,
) -> tuple[bool, str]:
    """Check if a lab can be placed following all lab-specific constraints.

    Valid lab start periods (0-indexed): 0 (P1), 1 (P2), 4 (P5), 5 (P6).
    This gives windows P1-P3, P2-P4, P5-P7, P6-P8.
    P3-P5 and P4-P6 are invalid because they cross the lunch boundary.
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
    event_semesters: set[str],
) -> tuple[bool, str]:
    """Check if a lab can be placed without causing same-semester overlaps.
    
    CRITICAL: Prevents the bug where two labs of the SAME semester are allocated
    at overlapping time slots. A semester can NEVER have two labs simultaneously.
    
    Args:
        state: Current schedule state
        start_slot: Starting time slot index
        block_size: Size of the lab block
        event_semesters: Set of semesters attending this lab
        
    Returns:
        Tuple of (can_place, reason_string)
    """
    # Check each slot in the lab block for same-semester lab conflicts
    for slot in range(start_slot, start_slot + block_size):
        for sem in event_semesters:
            # Get all assignments already in this slot for this semester
            if slot in state.by_semester.get(sem, {}):
                assns = state.by_semester.get(sem, {}).get(slot, [])
                # Check if any are labs - labs cannot overlap with other labs of same semester
                for assn in assns:
                    if assn.item_type == ItemType.LAB:
                        d, p = slot_to_day_period(slot)
                        return False, f"same-semester lab overlap: {sem} already has lab '{assn.name}' at {DAYS[d]} {PERIODS[p]}"
    
    return True, ""


def can_place_core(
    state: ScheduleState,
    slot: int,
    event_name: str,
    event_semesters: set[str],
) -> tuple[bool, str]:
    """Check if a core subject can be placed following core-specific constraints."""
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


def is_slot_blocked_by_recourse(
    state: ScheduleState,
    constraints: Constraints,
    slot: int,
    event_semesters: set[str],
    event_recourse_sources: set[str],
) -> tuple[bool, str]:
    """Check if a slot is blocked due to recourse constraints."""
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


def _place_event_block(
    *,
    state: ScheduleState,
    event: Event,
    start_slot: int,
    block_size: int,
) -> None:
    sems_sorted = tuple(sorted(event.semesters))
    recourse_sources = tuple(sorted(event.recourse_sources))

    for slot in iter_slots_for_block(start_slot, block_size):
        assn = Assignment(
            event_id=event.event_id,
            item_type=event.item_type,
            name=event.name,
            faculty=event.faculty,
            semesters=sems_sorted,
            recourse_sources=recourse_sources,
            credits=int(event.credits),
        )

        for sem in event.semesters:
            if slot not in state.by_semester[sem]:
                state.by_semester[sem][slot] = []
            state.by_semester[sem][slot].append(assn)

        state.teacher_usage.setdefault(event.faculty, set()).add(slot)

        if event.item_type == ItemType.LAB:
            state.lab_count_at_slot[slot] = state.lab_count_at_slot.get(slot, 0) + 1

    # Track blocks placed for this event
    state.event_block_count[event.event_id] = state.event_block_count.get(event.event_id, 0) + 1
    
    # Track individual slots placed for this event (to prevent adjacent block placement)
    if event.event_id not in state.event_placed_slots:
        state.event_placed_slots[event.event_id] = set()
    for slot in iter_slots_for_block(start_slot, block_size):
        state.event_placed_slots[event.event_id].add(slot)

    # No bucket tracking in simplified architecture

    # Update subject-on-day once per semester
    day, _ = slot_to_day_period(start_slot)
    for sem in event.semesters:
        state.subject_on_day[sem][day].add(event.name)


def _remove_event_block(
    *,
    state: ScheduleState,
    event: Event,
    start_slot: int,
    block_size: int,
) -> None:
    # Backtracking helper
    for slot in iter_slots_for_block(start_slot, block_size):
        for sem in event.semesters:
            if slot in state.by_semester[sem]:
                # find and remove the exact assignment
                state.by_semester[sem][slot] = [a for a in state.by_semester[sem][slot] if a.event_id != event.event_id]
                if not state.by_semester[sem][slot]:
                    state.by_semester[sem].pop(slot, None)

        teacher_slots = state.teacher_usage.get(event.faculty)
        if teacher_slots and slot in teacher_slots:
            teacher_slots.remove(slot)

        if event.item_type == ItemType.LAB:
            state.lab_count_at_slot[slot] = max(0, state.lab_count_at_slot.get(slot, 0) - 1)

    day, _ = slot_to_day_period(start_slot)
    for sem in event.semesters:
        # Recompute subject_on_day for this semester/day
        # since we might have multiple blocks of the same subject on this day (though disallowed).
        # Actually, simpler: rebuild the set from scratch for this day based on current by_semester state
        state.subject_on_day[sem][day].clear()
        base = day * SLOTS_PER_DAY
        for s in range(base, base + SLOTS_PER_DAY):
            assns = state.by_semester[sem].get(s, [])
            for a in assns:
                state.subject_on_day[sem][day].add(a.name)

    # Track placed-block counts and clear bucket commitments when last block of an event removed
    if event.event_id in state.event_block_count:
        state.event_block_count[event.event_id] = max(0, state.event_block_count.get(event.event_id, 1) - 1)
        if state.event_block_count[event.event_id] == 0:
            state.event_block_count.pop(event.event_id, None)
    
    # Remove slots from event_placed_slots tracking
    if event.event_id in state.event_placed_slots:
        for slot in iter_slots_for_block(start_slot, block_size):
            state.event_placed_slots[event.event_id].discard(slot)
        if not state.event_placed_slots[event.event_id]:
            state.event_placed_slots.pop(event.event_id, None)


def _candidate_starts_for_block(item_type: ItemType, block_size: int) -> list[int]:
    starts: list[int] = []
    for day in range(5):
        base = day * SLOTS_PER_DAY

        if item_type == ItemType.LAB:
            # Valid lab start periods: P1 (0), P2 (1), P5 (4), P6 (5)
            # Gives windows: P1-P3, P2-P4, P5-P7, P6-P8
            for p in LAB_VALID_START_PERIODS:
                starts.append(base + p)
            continue

        # Non-labs: allow any start that doesn't cross lunch/day
        for period in range(0, SLOTS_PER_DAY):
            start_slot = base + period
            if block_fits_time_contiguity(start_slot, block_size):
                starts.append(start_slot)

    return starts


def _compute_recourse_conflicts(
    *,
    state: ScheduleState,
    constraints: Constraints,
    event: Event,
    start_slot: int,
    block_size: int,
) -> tuple[dict[str, list[Assignment]], list[tuple[str, int, Assignment]]]:
    """Return mapping target_sem -> list of conflicting assignments and examples.

    Also return a short list of example tuples (target_sem, slot, assignment).
    """
    conflicts: dict[str, list[Assignment]] = {}
    examples: list[tuple[str, int, Assignment]] = []

    for slot in iter_slots_for_block(start_slot, block_size):
        # forward: this event offers recourse for its source semesters -> avoid targets
        for source_sem in event.recourse_sources:
            targets = constraints.recourse_targets.get(source_sem, set())
            for target in targets:
                if target not in state.by_semester:
                    continue
                assns = state.by_semester.get(target, {}).get(slot, [])
                if assns:
                    conflicts.setdefault(target, []).extend(assns)
                    if len(examples) < 5:
                        examples.append((target, slot, assns[0]))

        # reverse: existing recourse-enabled assignments may target this event's semesters
        for other_sem, slots_map in state.by_semester.items():
            assns = slots_map.get(slot, [])
            if not assns:
                continue
            for a in assns:
                # for every source_sem that this existing assignment is recourse-enabled for
                for src in a.recourse_sources:
                    targets = constraints.recourse_targets.get(src, set())
                    # if any of the event's semesters are targets, count the conflict
                    if any(ts in targets for ts in event.semesters):
                        conflicts.setdefault(other_sem, []).append(a)
                        if len(examples) < 5:
                            examples.append((other_sem, slot, a))

    return conflicts, examples


def _estimate_candidate_count(event: Event, constraints: Constraints, included_semesters: list[str]) -> int:
    # rough static estimate: consider teacher forbidden slots only
    count = 0
    for bs in event.blocks:
        for start in _candidate_starts_for_block(event.item_type, bs):
            ok = True
            for slot in iter_slots_for_block(start, bs):
                if not is_teacher_available(constraints, event.faculty, slot):
                    ok = False
                    break
            if ok:
                count += 1
    return max(count, 1)


def _generate_blocks_for_event(event: Event, rng: random.Random) -> list[int]:
    if event.item_type == ItemType.LAB:
        return [LAB_BLOCK_SIZE]

    credits = int(event.credits)
    
    # For 4-credit courses, randomly choose between [2,2] and [2,1,1]
    if credits == 4:
        return rng.choice(CREDIT_4_ALTERNATIVES)
    
    # Use centralized credit-to-block mapping for others
    return CREDIT_BLOCK_MAPPING.get(credits, DEFAULT_BLOCK_PATTERN)


def _compute_faculty_unavailable_score(constraints: Constraints, faculty: str) -> int:
    """Count how many forbidden slots this faculty has. Higher = more constrained."""
    return len(constraints.teacher_forbidden.get(faculty, set()))


def _compute_recourse_targeting_score(constraints: Constraints, event: Event) -> int:
    """Count how many constraints this event targets as recourse source.
    
    If MCA-I is recourse for MCA-III, this score is high because placing MCA-I
    blocks many MCA-III slots.
    """
    count = 0
    for src_sem in event.recourse_sources:
        targets = constraints.recourse_targets.get(src_sem, set())
        count += len(targets)
    return count


def _compute_slot_flexibility(
    *,
    state: ScheduleState,
    constraints: Constraints,
    event: Event,
    start_slot: int,
    block_size: int,
) -> tuple[int, int]:
    """Compute flexibility score for a slot.
    
    Returns (neg_conflicts, neg_blocked_future_slots).
    
    Lower scores = more flexible, so we prefer lower values.
    We return negative values so sorting works naturally (lower = better).
    """
    # Count recourse conflicts at this slot
    recourse_conflicts = 0
    for slot in iter_slots_for_block(start_slot, block_size):
        for src_sem in event.recourse_sources:
            targets = constraints.recourse_targets.get(src_sem, set())
            for tgt_sem in targets:
                if tgt_sem in state.by_semester:
                    assns = state.by_semester.get(tgt_sem, {}).get(slot, [])
                    recourse_conflicts += len(assns)
    
    # Count how many future slots this placement would block
    # (slots on same day that can't have same subject)
    day, _ = slot_to_day_period(start_slot)
    blocked_count = 0
    base = day * SLOTS_PER_DAY
    for s in range(base, base + SLOTS_PER_DAY):
        if s not in state.by_semester.get(next(iter(event.semesters)), {}):
            blocked_count += 1
    
    return (-recourse_conflicts, -blocked_count)


def schedule(
    *,
    included_semesters: list[str],
    events: dict[str, Event],
    constraints: Constraints,
    max_restarts: int = 1,
    per_restart_shuffle_seed: int | None = None,
) -> tuple[ScheduleState | None, list[str]]:
    """Attempt to schedule all events using deterministic CSP-style backtracking.
    
    Key improvements:
    1. Deterministic heuristics (no randomness)
    2. Most-constrained-first event ordering
    3. Least-flexible-slot-first slot selection
    4. Conflict memory to avoid retrying failed combinations
    5. Adaptive backtracking with partial repair
    
    Returns (state, errors).
    """

    @dataclass
    class BlockToSchedule:
        event: Event
        block_size: int
        candidates: list[int]
        constraint_score: int  # for ordering
        is_first_block: bool = False

    # Use seed if provided for reproducible behavior, but don't randomize placement.
    # Seed only affects which multi-block choices we make (e.g., 2+2 vs 2+1+1 for 4-credit).
    rng = random.Random(per_restart_shuffle_seed)
    state = _empty_state(included_semesters)

    # Generate blocks deterministically with deep copy for immutability
    for ev in events.values():
        generated_blocks = _generate_blocks_for_event(ev, rng)
        ev.blocks = deepcopy(generated_blocks)  # Deep copy to prevent mutation
    
    # Pre-validate all block structures before scheduling
    for ev in events.values():
        if ev.item_type == ItemType.LAB:
            if ev.blocks != [LAB_BLOCK_SIZE]:
                errors.append(f"Invalid lab block structure for {ev.name}: {ev.blocks}, expected [3]")
                continue
        else:
            credits = ev.credits
            if credits == 3:
                if ev.blocks != [2, 1]:
                    errors.append(f"Invalid 3-credit block structure for {ev.name}: {ev.blocks}, expected [2,1]")
                    continue
            elif credits == 4:
                if ev.blocks not in [[2, 2], [2, 1, 1]]:
                    errors.append(f"Invalid 4-credit block structure for {ev.name}: {ev.blocks}, expected [2,2] or [2,1,1]")
                    continue

    # === MOST-CONSTRAINED-FIRST EVENT ORDERING ===
    # Priority: Labs > Recourse-enabled > High-credit > Multi-semester > Faculty-constrained > Named order
    def compute_constraint_score(ev: Event) -> tuple[int, int, int, int, int, str]:
        faculty_unavailable = _compute_faculty_unavailable_score(constraints, ev.faculty)
        recourse_targeting = _compute_recourse_targeting_score(constraints, ev)
        semester_count = len(ev.semesters)
        block_count = len(ev.blocks)
        total_block_slots = sum(ev.blocks)
        
        # Ranking (lower values first):
        # 0: Labs (most constrained in practice)
        # 1: Recourse-enabled cores (block many slots for other semesters)
        # 2: Regular cores
        # 3: Electives
        if ev.item_type == ItemType.LAB:
            type_rank = 0
        elif ev.item_type == ItemType.CORE and ev.recourse_sources:
            type_rank = 1
        elif ev.item_type == ItemType.CORE:
            type_rank = 2
        else:
            type_rank = 3
        
        # For same type, prioritize:
        # - more blocks (more placements needed = more constrained)
        # - higher faculty unavailability (fewer slots available)
        # - recourse targeting (blocks more other semesters)
        # - more semesters (fewer individual slots per semester)
        # - alphabetical tiebreaker
        
        return (
            type_rank,
            -total_block_slots,  # more blocks = higher priority
            -faculty_unavailable,  # more unavailable = higher priority
            -recourse_targeting,  # more targeting = higher priority
            -semester_count,  # more semesters = higher priority
            ev.name,  # alphabetical tiebreaker
        )

    ordered_events = sorted(events.values(), key=compute_constraint_score)

    # === FLATTEN EVENTS INTO BLOCKS ===
    # For each block in each event, prepare candidates and compute constraint score
    blocks_to_schedule: list[BlockToSchedule] = []
    for event in ordered_events:
        for idx, bs in enumerate(event.blocks):
            cands = _candidate_starts_for_block(event.item_type, bs)
            
            # Compute the constraint score for this event (used for block ordering)
            # All blocks of the same event have the same constraint score.
            constraint_score = compute_constraint_score(event)
            
            blocks_to_schedule.append(BlockToSchedule(
                event=event,
                block_size=bs,
                candidates=cands,
                constraint_score=constraint_score,
                is_first_block=(idx == 0),
            ))

    tracker = DiagnosticTracker()
    iterations_count = [0]
    # MAX_ITERATIONS imported from constants
    
    # Conflict memory: track (event_id, block_idx, start_slot) combinations that failed
    failed_combinations: set[tuple[str, int, int]] = set()

    def dfs(index: int, backtrack_depth: int = 0) -> bool:
        """Deterministic DFS with improved backtracking.
        
        Args:
            index: Current block index to schedule
            backtrack_depth: How many blocks to rollback if stuck (for adaptive retry)
        """
        iterations_count[0] += 1
        if iterations_count[0] > MAX_ITERATIONS:
            return False

        if index > tracker.deepest_depth:
            tracker.deepest_depth = index
            if index < len(blocks_to_schedule):
                tracker.deepest_event_id = blocks_to_schedule[index].event.name
            else:
                tracker.deepest_event_id = "All Finished"

        if index == len(blocks_to_schedule):
            return True  # All placed!

        block_req = blocks_to_schedule[index]
        event = block_req.event
        bs = block_req.block_size
        block_ordinal = index + 1

        # === CANDIDATE RANKING ===
        # For labs: shuffle valid starts within each half (morning/afternoon) before
        # scoring so that P2/P6 get a fair chance alongside P1/P5.  The shuffle uses
        # the run-level rng so results are reproducible given the same seed.
        # For non-labs: use the existing deterministic heuristic ordering.
        def rank_candidates(candidates: list[int]) -> list[tuple[tuple, int]]:
            """Rank candidates. Lower tuples are better."""
            ranked = []

            if event.item_type == ItemType.LAB:
                # Group candidates by (day, half) so we can shuffle within each group.
                # half 0 = morning (P1/P2, period indices 0-1)
                # half 1 = afternoon (P5/P6, period indices 4-5)
                # This prevents the fixed [0,1,4,5] order from always favouring P1/P5.
                from collections import defaultdict
                groups: dict[tuple[int, int], list[int]] = defaultdict(list)
                for start in candidates:
                    if (event.event_id, index, start) in failed_combinations:
                        continue
                    day, period = slot_to_day_period(start)
                    half = 0 if period < SLOTS_PER_DAY // 2 else 1
                    groups[(day, half)].append(start)

                # Shuffle within each group to break P1-first / P5-first bias
                for key in sorted(groups):
                    group = groups[key]
                    rng.shuffle(group)
                    for start in group:
                        # Compute recourse conflicts (lower is better)
                        rec_conf, _ = _compute_recourse_conflicts(
                            state=state,
                            constraints=constraints,
                            event=event,
                            start_slot=start,
                            block_size=bs,
                        )
                        recourse_conflict_count = sum(len(v) for v in rec_conf.values())
                        day_idx, _ = slot_to_day_period(start)
                        # Rank: recourse conflicts first, then day, then shuffled position
                        rank = (recourse_conflict_count, day_idx)
                        ranked.append((rank, start))

                # Sort by rank tuple; within equal rank the shuffle order is preserved
                # because Python's sort is stable.
                ranked.sort(key=lambda x: x[0])
                return ranked

            # --- Non-lab path: original heuristic ---
            for start in candidates:
                # Skip combinations we know failed before (conflict memory)
                if (event.event_id, index, start) in failed_combinations:
                    continue
                
                # Compute flexibility metrics
                flex_score = _compute_slot_flexibility(
                    state=state,
                    constraints=constraints,
                    event=event,
                    start_slot=start,
                    block_size=bs,
                )
                
                # Compute recourse conflicts (lower is better)
                rec_conf, _ = _compute_recourse_conflicts(
                    state=state,
                    constraints=constraints,
                    event=event,
                    start_slot=start,
                    block_size=bs,
                )
                recourse_conflict_count = sum(len(v) for v in rec_conf.values())
                
                # Compute slot position (prefer earlier in week for stability)
                day, _ = slot_to_day_period(start)
                
                # Final ranking tuple (all components ascending)
                rank = (
                    recourse_conflict_count,  # Minimize recourse conflicts first
                    flex_score[0],  # Then maximize recourse flexibility
                    flex_score[1],  # Then maximize future flexibility
                    day,  # Prefer earlier in week (tiebreaker)
                    start,  # Finally by slot number
                )
                
                ranked.append((rank, start))
            
            # Sort by rank
            ranked.sort(key=lambda x: x[0])
            return ranked

        # Get and rank candidates
        candidates_ranked = rank_candidates(block_req.candidates)
        candidates = [start for (_rank, start) in candidates_ranked]

        if not candidates:
            # All candidates already failed before - mark for deeper backtracking
            if block_req.is_first_block:
                tracker.add_trace(f"No valid candidates for {event.name} (first block)")
            return False

        # === DETERMINISTIC CANDIDATE EXPLORATION ===
        for attempt_num, start in enumerate(candidates):
            can_place, reason = _can_place_event_block(
                state=state,
                constraints=constraints,
                event=event,
                start_slot=start,
                block_size=bs,
                is_first_block=block_req.is_first_block,
            )

            if can_place:
                # Place the block
                _place_event_block(state=state, event=event, start_slot=start, block_size=bs)
                
                # Recursively schedule next block
                if dfs(index + 1, backtrack_depth=0):
                    return True
                
                # Backtrack: remove this block
                _remove_event_block(state=state, event=event, start_slot=start, block_size=bs)
                
                # Record failed combination for faster future rejection
                failed_combinations.add((event.event_id, index, start))
            else:
                tracker.add_rejection(event.name, start, reason)

        # === ADAPTIVE DEEP BACKTRACKING ===
        # If all candidates for this block failed and we haven't tried deep backtracking yet,
        # attempt to unschedule and reshuffle some previously-placed blocks.
        if backtrack_depth < MAX_BACKTRACK_DEPTH and index > 3:  # Only after at least 3 blocks are placed
            # Try undoing the previous block and retrying with different combination
            if dfs(index - 1, backtrack_depth + 1):
                # The recursive call will trigger reordering, then come back here
                # and naturally try different paths
                return True

        return False

    success = dfs(0)

    if success:
        return state, []

    # === FAILURE ANALYSIS ===
    # Generate detailed diagnostics
    errors = [
        "Unable to generate a valid timetable with the current constraints.",
        f"Explored up to: {tracker.deepest_event_id} (block depth: {tracker.deepest_depth}/{len(blocks_to_schedule)})",
        f"Iterations: {iterations_count[0]}/{MAX_ITERATIONS}",
    ]
    
    diag_report = tracker.generate_report()
    errors.extend(diag_report)

    return None, errors


def _compute_recourse_blocked_slots(
    *,
    state: ScheduleState,
    constraints: Constraints,
    included_semesters: list[str],
) -> dict[str, set[int]]:
    """Compute which slots are blocked by recourse for each target semester.
    
    Returns mapping: target_semester -> set of blocked slot indices
    
    A slot is blocked if:
    - It contains a recourse-enabled assignment from a source semester
    - The target semester is listed as a recourse target
    """
    blocked: dict[str, set[int]] = {s: set() for s in included_semesters}
    
    # Iterate through all assignments
    for source_sem, slots_map in state.by_semester.items():
        for slot, assns in slots_map.items():
            for assn in assns:
                # If this assignment is recourse-enabled
                if assn.recourse_sources:
                    for src_sem in assn.recourse_sources:
                        targets = constraints.recourse_targets.get(src_sem, set())
                        for target_sem in targets:
                            if target_sem in blocked:
                                blocked[target_sem].add(slot)
    
    return blocked


def generate_elective_windows(
    *,
    state: ScheduleState,
    constraints: Constraints,
    included_semesters: list[str],
) -> None:
    """Generate elective windows in free slots after core scheduling.
    
    Strategy:
    - Find largest contiguous free blocks for each semester
    - Create elective window assignments in those blocks
    - Skip slots blocked by recourse constraints
    - Prioritize creating windows that span multiple periods for flexibility
    
    Modifies state in-place to add elective windows.
    """
    # Compute which slots are blocked by recourse for each semester
    recourse_blocked = _compute_recourse_blocked_slots(
        state=state,
        constraints=constraints,
        included_semesters=included_semesters,
    )
    
    for semester in included_semesters:
        # Find all free slots for this semester
        used_slots = set(state.by_semester.get(semester, {}).keys())
        blocked_slots = recourse_blocked.get(semester, set())
        all_slots = set(range(TOTAL_SLOTS))
        # Free = not used AND not blocked by recourse
        free_slots = sorted(all_slots - used_slots - blocked_slots)
        
        if not free_slots:
            continue  # No free slots for this semester
        
        # Group free slots into contiguous blocks per day
        windows_to_create: list[tuple[int, int]] = []  # (start_slot, size)
        
        for day in range(5):
            day_base = day * SLOTS_PER_DAY
            day_free = sorted([s for s in free_slots if day_base <= s < day_base + SLOTS_PER_DAY])
            
            if not day_free:
                continue
            
            # Find contiguous blocks in this day
            current_block_start = day_free[0]
            prev_slot = day_free[0]
            
            for slot in day_free[1:]:
                # Check if contiguous and doesn't cross lunch boundary
                if slot != prev_slot + 1:
                    # Block ended
                    block_size = prev_slot - current_block_start + 1
                    if block_size >= 2:  # Only create windows of 2+ periods
                        windows_to_create.append((current_block_start, block_size))
                    current_block_start = slot
                
                # Check lunch boundary (between P4 and P5, i.e., between period indices 3 and 4)
                if prev_slot % SLOTS_PER_DAY == 3 and slot % SLOTS_PER_DAY == 5:
                    # Crossed lunch, break the block
                    block_size = prev_slot - current_block_start + 1
                    if block_size >= 2:
                        windows_to_create.append((current_block_start, block_size))
                    current_block_start = slot
                
                prev_slot = slot
            
            # Don't forget the last block
            block_size = prev_slot - current_block_start + 1
            if block_size >= 2:
                windows_to_create.append((current_block_start, block_size))
        
        # Create elective window assignments
        for start_slot, size in windows_to_create:
            # Create a synthetic "elective window" event that spans these slots
            window_name = f"Elective Window {semester}"
            window_id = f"elective-{semester}-{start_slot}"
            
            for slot_idx, slot in enumerate(iter_slots_for_block(start_slot, size)):
                # Avoid duplicate windows - only create if this slot isn't already occupied
                if slot not in state.by_semester.get(semester, {}):
                    assn = Assignment(
                        event_id=window_id,
                        item_type=ItemType.WINDOW,
                        name=window_name,
                        faculty="(free)",
                        semesters=(semester,),
                        recourse_sources=(),
                    )
                    
                    if slot not in state.by_semester.get(semester, {}):
                        state.by_semester[semester][slot] = []
                    state.by_semester[semester][slot].append(assn)
