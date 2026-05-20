"""timetable_scheduler.engine.models

Internal data model for UI-driven timetable generation.

The engine uses a 5x8 grid (Mon-Fri, P1-P8). Lunch is implicit between P4 and P5,
so multi-period blocks are not allowed to cross that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .constants import (
    DAYS,
    PERIODS,
    SLOTS_PER_DAY,
    TOTAL_SLOTS,
    LUNCH_BOUNDARY_PERIOD_INDEX,
    RECOURSE_TARGETS,
)


class ItemType(str, Enum):
    CORE = "core"
    LAB = "lab"
    WINDOW = "window"


@dataclass(frozen=True)
class SemesterConfig:
    semester_id: str  # e.g. "MCA-I"
    include: bool
    core_rows: list["UiRow"] = field(default_factory=list)
    lab_rows: list["UiRow"] = field(default_factory=list)


@dataclass(frozen=True)
class UiRow:
    name: str
    faculty: str
    credits: int
    recourse_allowed: bool
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionRequest:
    """A single placement request.

    block_size is in periods (slots). For labs this is always 3.
    """

    event_id: str
    block_size: int
    item_type: ItemType


@dataclass
class Event:
    """A schedulable entity that can require multiple session blocks."""

    event_id: str
    item_type: ItemType
    name: str
    faculty: str
    credits: int
    semesters: set[str]
    # Recourse rules are applied per source semester.
    recourse_sources: set[str] = field(default_factory=set)
    # Blocks required for this event (sizes in periods)
    blocks: list[int] = field(default_factory=list)


@dataclass
class Constraints:
    """Derived constraints used during scheduling."""

    # teacher -> forbidden slot indices
    teacher_forbidden: dict[str, set[int]]

    # source semester -> target semesters that must not clash
    recourse_targets: dict[str, set[str]]
    


@dataclass
class Assignment:
    event_id: str
    item_type: ItemType
    name: str
    faculty: str
    semesters: tuple[str, ...]
    recourse_sources: tuple[str, ...] = ()
    credits: int = 3  # Default to 3 credits for validation of credit splitting


@dataclass
class EngineResult:
    success: bool
    # Each cell is a list of Assignment objects (one slot may contain multiple assignments)
    semester_timetables: dict[str, list[list[list[Assignment]]]]
    # Deprecated: faculty-wise generation removed. Keep for compatibility but may be empty.
    faculty_timetables: dict[str, list[list[list[Assignment]]]]
    # Combined timetable across included semesters (5 x SLOTS_PER_DAY grid)
    combined_timetable: list[list[list[Assignment]]] | None = None
    errors: list[str] = field(default_factory=list)
    # debugging messages to aid development/diagnostics
    debug: list[str] = field(default_factory=list)


def slot_to_day_period(slot: int) -> tuple[int, int]:
    if slot < 0 or slot >= TOTAL_SLOTS:
        raise ValueError(f"Invalid slot index: {slot}")
    return slot // SLOTS_PER_DAY, slot % SLOTS_PER_DAY


def day_period_to_slot(day_index: int, period_index: int) -> int:
    if day_index < 0 or day_index >= 5:
        raise ValueError(f"Invalid day index: {day_index}")
    if period_index < 0 or period_index >= SLOTS_PER_DAY:
        raise ValueError(f"Invalid period index: {period_index}")
    return day_index * SLOTS_PER_DAY + period_index


def normalize_label(value: Any) -> str:
    return str(value or "").strip().replace("\t", " ").replace("\n", " ").replace("\r", " ")


def normalize_key(value: Any) -> str:
    return " ".join(normalize_label(value).split()).lower()


def iter_slots_for_block(start_slot: int, block_size: int) -> Iterable[int]:
    for s in range(start_slot, start_slot + block_size):
        yield s


def block_fits_time_contiguity(start_slot: int, block_size: int) -> bool:
    """Disallow crossing day boundary and lunch boundary."""

    if block_size <= 0:
        return False

    if start_slot < 0 or start_slot >= TOTAL_SLOTS:
        return False

    end_slot = start_slot + block_size - 1
    if end_slot < 0 or end_slot >= TOTAL_SLOTS:
        return False

    start_day, start_period = slot_to_day_period(start_slot)
    end_day, end_period = slot_to_day_period(end_slot)

    if start_day != end_day:
        return False

    # lunch boundary is between P4 (index 3) and P5 (index 4)
    if block_size > 1:
        crosses_lunch = start_period < LUNCH_BOUNDARY_PERIOD_INDEX <= end_period
        if crosses_lunch:
            return False

    return True


def ensure_matrix_symmetric(matrix: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, bool]]:
    # Normalize keys: UI might send "PR||Avan", we need "pr||avan"
    norm_matrix: dict[str, dict[str, bool]] = {}
    for a, row in matrix.items():
        if "||" in a:
            n, f = a.split("||", 1)
            na = f"{normalize_label(n).lower()}||{normalize_label(f).lower()}"
        else:
            na = normalize_key(a)
        
        norm_matrix[na] = {}
        row_dict = row if isinstance(row, dict) else {}
        for b, val in row_dict.items():
            if "||" in b:
                n, f = b.split("||", 1)
                nb = f"{normalize_label(n).lower()}||{normalize_label(f).lower()}"
            else:
                nb = normalize_key(b)
            norm_matrix[na][nb] = bool(val)

    keys = list(norm_matrix.keys())
    out: dict[str, dict[str, bool]] = {k: {} for k in keys}

    for a in keys:
        for b in keys:
            if a == b:
                out[a][b] = False
                continue
            # If UI did not explicitly provide a value, assume permissive (compatible).
            row_a = norm_matrix.get(a, {})
            row_b = norm_matrix.get(b, {})
            va = row_a[b] if b in row_a else True
            vb = row_b[a] if a in row_b else True
            out[a][b] = bool(va) or bool(vb)

    return out


def uniq(seq: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out
