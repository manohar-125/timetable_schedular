"""timetable_scheduler.engine.constraints

Build derived constraints from the UI input.
"""

from __future__ import annotations

from typing import Any, Mapping

from .models import (
    Constraints,
    DAYS,
    PERIODS,
    SLOTS_PER_DAY,
    TOTAL_SLOTS,
    day_period_to_slot,
    normalize_key,
)


def _slots_for_day(day_index: int) -> set[int]:
    start = day_index * SLOTS_PER_DAY
    return set(range(start, start + SLOTS_PER_DAY))


def _slots_for_first_half(day_index: int) -> set[int]:
    base = day_index * SLOTS_PER_DAY
    return set(range(base, base + 4))


def _slots_for_second_half(day_index: int) -> set[int]:
    base = day_index * SLOTS_PER_DAY
    return set(range(base + 4, base + 8))


def _parse_slot_token(token: str) -> tuple[str, str] | None:
    t = (token or "").strip()
    if not t:
        return None

    # Supported styles:
    # - "Monday|P1" (UI)
    # - "MONDAY_P1" (example)
    # - "Tuesday|Second Half"
    # - "WEDNESDAY_FULL_DAY"
    if "|" in t:
        parts = t.split("|", 1)
        if len(parts) != 2:
            return None
        return parts[0].strip(), parts[1].strip()

    if "_" in t:
        parts = t.split("_", 1)
        if len(parts) != 2:
            return None
        return parts[0].strip(), parts[1].strip()

    return None


def _day_index(day: str) -> int | None:
    d = normalize_key(day)
    for idx, name in enumerate(DAYS):
        if normalize_key(name) == d:
            return idx
    return None


def build_teacher_forbidden_slots(teacherAvailability: Mapping[str, Any]) -> dict[str, set[int]]:
    """Convert UI teacherAvailability into teacher->forbiddenSlots.

    UI shape:
      teacherAvailability: {
        teachers: {
          "dr. rao": { name: "Dr. Rao", slots: ["Monday|P1", "Tuesday|Second Half"] }
        }
      }

    Backend also accepts the simplified example form:
      { "Dr. Rao": ["MONDAY_P1", ...] }
    """

    out: dict[str, set[int]] = {}

    teachers_obj = teacherAvailability.get("teachers") if isinstance(teacherAvailability, Mapping) else None

    if isinstance(teachers_obj, Mapping):
        for _, v in teachers_obj.items():
            if not isinstance(v, Mapping):
                continue
            teacher_name = str(v.get("name") or "").strip()
            if not teacher_name:
                continue

            slots_any = v.get("slots") or []
            if isinstance(slots_any, set):
                slots = list(slots_any)
            elif isinstance(slots_any, list):
                slots = slots_any
            else:
                slots = []

            forbidden = out.setdefault(teacher_name, set())
            for token in slots:
                parsed = _parse_slot_token(str(token))
                if not parsed:
                    continue
                day_s, slot_s = parsed
                di = _day_index(day_s)
                if di is None:
                    continue

                slot_norm = normalize_key(slot_s)

                if slot_norm in {"full day", "full_day", "fullday"}:
                    forbidden |= _slots_for_day(di)
                elif slot_norm in {"first half", "first_half", "firsthalf"}:
                    forbidden |= _slots_for_first_half(di)
                elif slot_norm in {"second half", "second_half", "secondhalf"}:
                    forbidden |= _slots_for_second_half(di)
                elif slot_norm in {normalize_key(p) for p in PERIODS}:
                    # map P1..P8
                    p_idx = [normalize_key(p) for p in PERIODS].index(slot_norm)
                    forbidden.add(day_period_to_slot(di, p_idx))

        return out

    # simplified fallback
    if isinstance(teacherAvailability, Mapping):
        for teacher_name, tokens_any in teacherAvailability.items():
            teacher_name = str(teacher_name).strip()
            if not teacher_name:
                continue
            tokens = tokens_any if isinstance(tokens_any, list) else []
            forbidden = out.setdefault(teacher_name, set())
            for token in tokens:
                parsed = _parse_slot_token(str(token))
                if not parsed:
                    continue
                day_s, slot_s = parsed
                di = _day_index(day_s)
                if di is None:
                    continue

                slot_norm = normalize_key(slot_s)
                if slot_norm in {"full day", "full_day", "fullday"}:
                    forbidden |= _slots_for_day(di)
                elif slot_norm in {"first half", "first_half", "firsthalf"}:
                    forbidden |= _slots_for_first_half(di)
                elif slot_norm in {"second half", "second_half", "secondhalf"}:
                    forbidden |= _slots_for_second_half(di)
                elif slot_norm in {normalize_key(p) for p in PERIODS}:
                    p_idx = [normalize_key(p) for p in PERIODS].index(slot_norm)
                    forbidden.add(day_period_to_slot(di, p_idx))

    return out


def build_recourse_targets(*, cycle: str) -> dict[str, set[str]]:
    """Return a copy of the centralized RECOURSE_TARGETS for all programs (including IMTech)."""
    from .constants import RECOURSE_TARGETS
    # Defensive copy to avoid accidental mutation
    return {k: set(v) for k, v in RECOURSE_TARGETS.items()}


def buildConstraints(
    *,
    cycle: str,
    teacherAvailability: Mapping[str, Any] | None,
) -> Constraints:
    teacher_forbidden = build_teacher_forbidden_slots(teacherAvailability or {})

    return Constraints(
        teacher_forbidden=teacher_forbidden,
        recourse_targets=build_recourse_targets(cycle=str(cycle)),
    )


def clamp_to_known_slots(forbidden: dict[str, set[int]]) -> dict[str, set[int]]:
    """Safety: ensure forbidden slots are within 0..TOTAL_SLOTS-1."""
    out: dict[str, set[int]] = {}
    for teacher, slots in forbidden.items():
        out[teacher] = {s for s in slots if 0 <= s < TOTAL_SLOTS}
    return out
