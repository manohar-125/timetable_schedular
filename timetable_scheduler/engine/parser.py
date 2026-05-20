"""timetable_scheduler.engine.parser

Parses the Web UI state into normalized semester configs and schedulable events.

The UI sends objects shaped like the `appState` in webui/index.html.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .models import (
    Event,
    ItemType,
    SemesterConfig,
    UiRow,
    normalize_key,
    normalize_label,
    uniq,
)


SUPPORTED_PROGRAM_PREFIXES = ("MCA", "MTech", "IMTech")


def _parse_ui_row(row: Mapping[str, Any]) -> UiRow:
    name = normalize_label(row.get("name"))
    faculty = normalize_label(row.get("faculty"))
    credits_raw = row.get("credits", 3)
    try:
        credits = int(credits_raw)
    except Exception:
        credits = 3

    recourse_allowed = bool(row.get("recourse", False) or row.get("recourseAllowed", False))
    return UiRow(
        name=name,
        faculty=faculty,
        credits=credits,
        recourse_allowed=recourse_allowed,
        raw=row,
    )


def parseSemesterData(semesterData: Mapping[str, Any]) -> dict[str, SemesterConfig]:
    """Parse semesterData into a normalized mapping.

    semesterData example:
      {
        "MCA-I": { include: true, coreSubjects: [...], labs: [...], electives: [...] },
        ...
      }
    """

    out: dict[str, SemesterConfig] = {}

    for semester_id, cfg_any in (semesterData or {}).items():
        cfg = cfg_any or {}
        include = bool(cfg.get("include", True))

        core_rows = [_parse_ui_row(r) for r in (cfg.get("coreSubjects") or []) if isinstance(r, Mapping)]
        lab_rows = [_parse_ui_row(r) for r in (cfg.get("labs") or []) if isinstance(r, Mapping)]
        out[str(semester_id)] = SemesterConfig(
            semester_id=str(semester_id),
            include=include,
            core_rows=core_rows,
            lab_rows=lab_rows,
        )

    return out



@dataclass(frozen=True)
class ParsedInput:
    semesters: dict[str, SemesterConfig]
    included_semesters: list[str]
    events: dict[str, Event]


def build_events(
    semesters: Mapping[str, SemesterConfig],
    included_semesters: list[str],
    *,
    ignore_imtech: bool = True,
) -> dict[str, Event]:
    """Build events for labs/electives/cores.

    Combined electives are merged by (name, faculty) across included semesters.
    """

    events: dict[str, Event] = {}

    def new_id(prefix: str, sem: str, name: str, faculty: str) -> str:
        return f"{prefix}:{sem}:{normalize_key(name)}:{normalize_key(faculty)}"

    # ---- Labs: per semester, not combined ----
    for sem_id in included_semesters:
        if ignore_imtech and sem_id.startswith("IMTech"):
            continue
        sem_cfg = semesters[sem_id]
        for row in sem_cfg.lab_rows:
            if not row.name or not row.faculty:
                continue
            eid = new_id("lab", sem_id, row.name, row.faculty)
            events[eid] = Event(
                event_id=eid,
                item_type=ItemType.LAB,
                name=row.name,
                faculty=row.faculty,
                credits=3,
                semesters={sem_id},
                recourse_sources={sem_id} if row.recourse_allowed else set(),
                blocks=[3],
            )

    # ---- Cores: per semester ----
    for sem_id in included_semesters:
        if ignore_imtech and sem_id.startswith("IMTech"):
            continue
        sem_cfg = semesters[sem_id]
        for row in sem_cfg.core_rows:
            if not row.name or not row.faculty:
                continue
            eid = new_id("core", sem_id, row.name, row.faculty)
            events[eid] = Event(
                event_id=eid,
                item_type=ItemType.CORE,
                name=row.name,
                faculty=row.faculty,
                credits=row.credits,
                semesters={sem_id},
                recourse_sources={sem_id} if row.recourse_allowed else set(),
                blocks=[],
            )

    # No electives are parsed in the simplified architecture.

    return events


def select_included_semesters(
    semesters: Mapping[str, SemesterConfig],
    *,
    cycle: str,
    allow_programs: tuple[str, ...] = ("MCA", "MTech", "IMTech"),
) -> list[str]:
    """Return included semester ids.

    Backend intentionally keeps this extensible: selection is driven by cycle +
    the UI's include flag.
    """

    cycle = (cycle or "odd").strip().lower()

    # Default cycle mapping for now (requested scope: MCA + MTech only).
    odd = ["MCA-I", "MCA-III", "MTech-I", "IMTech-I", "IMTech-III", "IMTech-V", "IMTech-VII"]
    even = ["MCA-II", "MTech-II", "IMTech-II", "IMTech-IV", "IMTech-VI", "IMTech-VIII"]

    cycle_semesters = odd if cycle == "odd" else even

    included: list[str] = []
    for sem_id in cycle_semesters:
        cfg = semesters.get(sem_id)
        if not cfg:
            continue
        if not cfg.include:
            continue
        # allow programs gate
        if not any(sem_id.startswith(prefix) for prefix in allow_programs):
            continue
        included.append(sem_id)

    return uniq(included)


def parse_ui_state(
    ui_state: Mapping[str, Any],
    *,
    ignore_imtech: bool = True,
) -> ParsedInput:
    cycle = ui_state.get("cycle", "odd")
    semesters = parseSemesterData(ui_state.get("semesterData") or {})
    included = select_included_semesters(semesters, cycle=str(cycle))

    if ignore_imtech:
        included_for_events = [s for s in included if not s.startswith("IMTech")]
    else:
        included_for_events = included

    events = build_events(semesters, included_for_events, ignore_imtech=ignore_imtech)

    return ParsedInput(
        semesters=semesters,
        included_semesters=included,
        events=events,
    )
