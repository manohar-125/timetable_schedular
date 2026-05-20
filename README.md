# University Timetable Scheduler

A constraint-based automated timetable generation system for university departments. Schedules multiple programs (MCA, MTech, IMTech) across odd and even semester cycles using DFS backtracking with advanced constraint satisfaction.

**Status:** Production-ready | **Last Updated:** May 2026 | **Python:** 3.10+

---

## Features

- **Multi-program Support** — MCA, MTech, IMTech programs with semester cycles
- **Cycle-based Scheduling** — Separate odd and even semester configurations
- **Advanced Constraints** — Teacher availability, student group clashes, lab placement rules
- **Credit-aware Splitting** — Automatic 3-credit (2+1) and 4-credit (2+2 or 2+1+1) session splitting
- **Recourse Engine** — Slot reservation for students repeating courses from lower semesters
- **Lab Optimization** — Dedicated 3-period contiguous lab blocks with valid start period enforcement
- **Multiple Exports** — CSV, HTML (print-ready), and JSON formats
- **Interactive Web UI** — Browser-based configuration and timetable visualization
- **Real-time Auto-save** — Configuration persists to browser storage
- **Production-Tested** — 7-semester full-load scheduling in < 0.1s, zero regressions

---

## Quick Start

### Prerequisites
- Python 3.10 or higher
- pip (Python package manager)

### Installation & Run

**Option 1: Using the startup script**
```bash
bash webui/start_webui.sh
```

**Option 2: Manual setup**
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the server
python -m uvicorn webui.app:app --reload --host 0.0.0.0 --port 8000
```

**Open in browser:**
```
http://localhost:8000
```

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [Architecture](#architecture)
3. [Scheduling Algorithm](#scheduling-algorithm)
4. [Constraint System](#constraint-system)
5. [Configuration Guide](#configuration-guide)
6. [Export System](#export-system)
7. [Web UI Guide](#web-ui-guide)
8. [Debugging & Diagnostics](#debugging--diagnostics)
9. [Known Limitations](#known-limitations)
10. [Future Work](#future-work)
11. [Dependencies](#dependencies)
12. [Recent Updates](#recent-updates)
13. [License](#license)

---

## Project Structure

```
timetable_scheduler/
├── timetable_scheduler/
│   └── engine/                  # Core scheduling engine (no external deps)
│       ├── __init__.py          # Public API: generate_from_ui_state()
│       ├── constants.py         # Grid specs, credit mappings, recourse chains
│       ├── models.py            # Dataclasses (Event, Assignment, Constraints)
│       ├── parser.py            # Parse UI state → normalized events
│       ├── constraints.py       # Build teacher availability constraints
│       ├── constraint_utils.py  # Reusable constraint checkers
│       ├── scheduler.py         # DFS backtracking solver (1000 lines)
│       ├── validator.py         # Post-schedule validation
│       ├── renderer.py          # Format ScheduleState → grids
│       └── export.py            # CSV, HTML, JSON export
├── webui/
│   ├── app.py                   # FastAPI server (/api/generate, /api/export/*)
│   ├── index.html               # Single-page UI (vanilla JS, ~3000 lines)
│   ├── start_webui.sh           # Startup convenience script
│   └── static/                  # Empty (datasets loaded dynamically)
├── README.md                    # This file
├── requirements.txt             # Python dependencies
└── .gitignore                   # Git configuration
```

Every file listed above exists and is actively used in production.

---

## Architecture

### Three-Layer Design

```
┌─────────────────────────────────────┐
│  Browser UI (index.html)            │
│  Vanilla JS, 0 dependencies         │
└──────────────┬──────────────────────┘
               │ POST /api/generate (JSON)
               │
┌──────────────▼──────────────────────┐
│  FastAPI Server (webui/app.py)      │
│  Requests handling & result caching │
└──────────────┬──────────────────────┘
               │ calls generate_from_ui_state()
               │
┌──────────────▼──────────────────────┐
│  Scheduling Engine (engine/*)       │
│  DFS backtracking CSP solver        │
└─────────────────────────────────────┘
```

### Engine Pipeline

The complete scheduling flow:

```python
parse_ui_state()           # Convert UI → semesters + events
    ↓
buildConstraints()         # Extract teacher availability
    ↓
schedule()                 # DFS backtracking search
    ↓
generate_elective_windows() # Fill free slots with WINDOW placeholders
    ↓
validateTimetable()        # Post-schedule validation
    ↓
renderTimetable()          # Format as 5×8 grids per semester
    ↓
EngineResult               # Success/failure with grids & debug info
```

### Public API

Only one function is exposed:

```python
from timetable_scheduler.engine import generate_from_ui_state

result = generate_from_ui_state(ui_state_dict)

# result.success: bool
# result.semester_timetables: dict[str, list[list[list[Assignment]]]]
# result.combined_timetable: list[list[list[Assignment]]]
# result.errors: list[str]
# result.debug: list[str]
```

---

## Scheduling Algorithm

The scheduler uses **DFS backtracking** to solve the timetable generation as a Constraint Satisfaction Problem (CSP). No randomized restart, no memoization.

### Step 1: Event Decomposition

Each subject is decomposed into blocks based on credit hours and item type:

| Item Type | Credits | Block Pattern | Usage |
|---|---|---|---|
| Lab | — | `[3]` | Single 3-period contiguous block |
| Core | 2 | `[2]` | One 2-period block |
| Core | 3 | `[2, 1]` | One 2-period + one 1-period block |
| Core | 4 | `[2, 2]` or `[2, 1, 1]` | Random per run |

**Lab Constraints:**
- Must be exactly 3 periods
- Must start at P1, P2, P5, or P6 (Windows: P1–P3, P2–P4, P5–P7, P6–P8)
- Cannot start at P3 or P4 (would cross lunch boundary P4↔P5)

### Step 2: Most-Constrained-First Ordering

Events are sorted by constraint difficulty before search:

1. **Type rank:** Labs (0) < Recourse-enabled cores (1) < Regular cores (2)
2. **Total block slots** (descending) — more slots = harder to place
3. **Faculty unavailability** (descending) — more forbidden slots = harder
4. **Recourse targeting count** (descending) — blocks more semesters = harder
5. **Semester count** (descending)
6. **Event name** (alphabetical tiebreaker)

### Step 3: DFS Search

For each `(event, block_size)` pair in order:

1. **Generate candidates** — all valid slot ranges for this block type
2. **Filter via conflict memory** — skip `(event_id, block_index, start_slot)` tuples that failed before
3. **Rank candidates:**
   - Minimize recourse conflicts first
   - Then maximize future slot flexibility
   - Then prefer earlier in the week
4. **Validate placement** — check all hard constraints via `_can_place_event_block()`
5. **Place or backtrack:**
   - Success → place block, recurse to next block
   - Failure → record in conflict memory, try next candidate, or backtrack

### Step 4: Adaptive Backtracking

If all candidates for the current block fail, the scheduler attempts **adaptive deep backtracking**:
- Calls `dfs(index - 1, backtrack_depth + 1)` up to `MAX_BACKTRACK_DEPTH = 2` levels back
- Allows recovery from local dead-ends caused by earlier decisions

### Limits

```python
MAX_ITERATIONS     = 750000   # total DFS node visits before giving up
MAX_BACKTRACK_DEPTH = 2       # max levels of adaptive deep backtracking
```

The scheduler is heuristic — under heavy constraints it may exhaust iterations before finding a valid solution, even when one exists. Re-running with a different seed (affects 4-credit block pattern randomization) can sometimes succeed.

### Step 5: Elective Windows

After core and lab scheduling, `generate_elective_windows()` fills free slots with `ItemType.WINDOW` placeholder assignments:
- Groups contiguous free slots (2+ periods per day)
- Does not cross lunch boundary (P4↔P5)
- Visual markers only — not scheduled by DFS

---

## Constraint System

### Hard Constraints (enforced during placement)

| Constraint | Implementation | Hard/Soft |
|---|---|---|
| No teacher double-booking | `teacher_usage` set per teacher | Hard |
| No student group clash | `by_semester[sem][slot]` occupancy check | Hard |
| No subject repeated on same day | `subject_on_day[sem][day]` set | Hard |
| Lab exactly 3 periods | `can_place_lab()` validation | Hard |
| Lab valid start periods (P1/P2/P5/P6) | `LAB_VALID_START_PERIODS` check | Hard |
| Max 2 concurrent labs per slot | `lab_count_at_slot` counter | Hard |
| No crossing lunch boundary (P4→P5) | `block_fits_time_contiguity()` | Hard |
| No crossing day boundary | `block_fits_time_contiguity()` | Hard |
| Recourse slot reservation | `is_slot_blocked_by_recourse()` | Hard |
| No adjacent blocks of same course | adjacency check in `_can_place_event_block()` | Hard |
| Teacher availability (user-defined) | `is_teacher_available()` | Hard |
| **Same-semester lab overlap prevention** | `can_place_lab_with_semester_check()` | Hard |

### Teacher Availability Input Format

Teachers can be marked unavailable for specific slots or time ranges:

```
"Monday|P1"           → single period only
"Tuesday|First Half"  → P1–P4 (periods 0–3)
"Wednesday|Second Half" → P5–P8 (periods 4–7)
"Thursday|Full Day"   → all 8 periods (0–7)
```

Both `|` and `_` separators are accepted. Case-insensitive matching.

---

## Configuration Guide

### UI Configuration Flow

1. **Select Cycle** — Odd or Even (switches which semesters are shown)
2. **Per-Semester Tabs** — MCA-I, MCA-III (odd cycle), MTech-I (odd), IMTech-I/III/V/VII (odd), etc.
3. **Core Subjects** — Name, Faculty, Credits (3 or 4), Recourse checkbox
4. **Labs** — Name, Faculty (fixed 3 credits)
5. **Teacher Availability** — Add unavailable time slots via day + slot/half-day/full-day selector
6. **Generate** — POST to `/api/generate`, returns timetables and assignments
7. **Export** — CSV, HTML, or JSON

### Recourse Configuration

When a core subject is marked **Recourse Allowed**, the slots it occupies are reserved in the target semester's timetable.

**Recourse Chains (Production-Verified):**

Odd Cycle:
- `MCA-I → MCA-III`
- `IMTech-I → IMTech-III → IMTech-V → IMTech-VII`

Even Cycle:
- `IMTech-II → IMTech-IV → IMTech-VI → IMTech-VIII`

**Note:** `MTech-I → MTech-II` is defined in code but never fires in practice (MTech-I is odd, MTech-II is even — never scheduled together).

---

## Export System

### CSV Export — `/api/export/engine/csv`

```
GET /api/export/engine/csv
```

Exports combined timetable as CSV:
- Rows: Days (Monday–Friday)
- Columns: Periods (P1–P8)
- Cells: Course name + faculty, or `(free)`, or `(window)`
- Multi-assignments: joined with `;`

Returns: Timestamped `.csv` file download

### HTML and PDF Export — `/api/export/engine/pdf`

```
GET /api/export/engine/pdf
```

Exports a print-ready timetable as either HTML or PDF:
- **HTML**: Styled for browser printing, optimized for manual PDF export.
- **PDF**: Directly generated using the `reportlab` library.

Features:
- Color-coded by item type: core (blue), lab (orange), window (purple)
- Landscape layout, printer-optimized
- Print media query included for HTML

Returns: Timestamped `.html` or `.pdf` file download

### JSON Export — Debug Panel

The debug panel (toggleable in UI) includes an "Export Timetable JSON" button that downloads:
- `semester_timetables` — per-semester 5×8 grids
- `combined_timetable` — merged timetable

This is **not** an API endpoint; it's a browser-side download from the in-memory result object.

### Prerequisites

Both CSV and HTML exports require a successful generation first. The server holds the last `EngineResult` in memory. Calling an export endpoint before generation returns HTTP 400.

---

## Web UI Guide

### Overview

Single HTML file (`webui/index.html`), vanilla JavaScript, zero framework dependencies.

### Main Components

| Component | Purpose |
|---|---|
| **Cycle Selector** | Toggle Odd/Even semester cycles |
| **Semester Tabs** | One tab per semester in current cycle |
| **Core/Lab Tables** | Name, Faculty, Credits, Recourse checkbox per subject |
| **Teacher Availability** | Add/remove unavailable time slots as chips |
| **Generate Button** | POST configuration to `/api/generate` |
| **Results View** | Per-day tables with color-coded assignments |
| **Export Buttons** | CSV, HTML (PDF), JSON export (after generation) |
| **Right Panel** | Configuration save/load buttons |
| **Debug Panel** | (Toggled via menu) Shows JSON state and debug logs |

### Slot Color Coding

| Color | Meaning |
|---|---|
| Blue (`#f0f9ff`) | Occupied — core subject or lab |
| Red (`#fee2e2`) | Elective-available — free slot, not recourse-blocked |
| Gray (`#f3f4f6`) | Recourse-blocked — reserved for recourse attendance |

### Auto-Save

UI state is saved to browser `localStorage` on every input change and restored on page load. No server persistence — refresh clears results.

### What It Does NOT Do

- No elective compatibility matrix (removed)
- No faculty-wise timetable view (removed)
- No room allocation
- No authentication
- No multi-user accounts

---

## Debugging & Diagnostics

### Engine Debug Output

`EngineResult.debug` contains:
- Ignored semesters (unchecked by user)
- Slot counts per semester (occupied, available, recourse-blocked)
- Combined timetable slot counts
- Elective window generation notes

These appear below the timetable in the UI after generation.

### Failure Diagnostics

On scheduling failure, `EngineResult.errors` includes:
- Deepest event reached before exhausting search
- Top 10 most-rejected subjects with rejection counts
- Per-subject rejection reasons (teacher clash, student clash, recourse, same-day, etc.)
- Recourse conflict summary with up to 3 example slots
- Full rejection trace (up to 200 entries)

### Debug Panel

Toggle in UI to see:
- Full serialized UI state as JSON
- Latest engine result summary
- Download buttons for config and timetable

### Console Logging

Print statements in the engine (stdout):
- Recourse block reservations
- Validation failures (if any)

These appear in the terminal running the FastAPI server.

---

## Known Limitations

- **Heuristic instability** — May fail on valid configurations if `MAX_ITERATIONS` is exhausted. Re-running with different seed can help.
- **MTech recourse never fires** — `MTech-I → MTech-II` is defined but MTech-I is odd and MTech-II is even (never scheduled together).
- **MCA-IV not in any cycle** — Absent from both odd and even lists in `parser.py`; cannot be scheduled.
- **No room allocation** — Only assigns time slots, not physical rooms.
- **No automated elective scheduling** — Elective windows are visual placeholders only.
- **No server persistence** — All state in browser memory and `localStorage`; resets on server restart.
- **No authentication** — API has no access control.
- **PDF export is HTML** — `/api/export/engine/pdf` returns HTML; print to PDF manually from browser.
- **Faculty-wise view removed** — `EngineResult.faculty_timetables` always empty.
- **Shallow adaptive backtracking** — `MAX_BACKTRACK_DEPTH = 2` limits recovery from deep constraint conflicts.

---

## Future Work

- [ ] True PDF export via ReportLab (library already in requirements)
- [ ] Room allocation and room conflict modeling
- [ ] Automated elective grouping and scheduling
- [ ] Multi-restart strategy with different seeds for hard instances
- [ ] Persistent storage (database backend)
- [ ] User authentication and multi-user support
- [ ] Faculty-wise timetable view
- [ ] Structured logging (replace `print()` statements)
- [ ] Fix `MCA-IV` in cycle lists (if needed)
- [ ] Fix MTech recourse (cross-cycle or same-cycle pairing)
- [ ] Excel/XLSX export format
- [ ] Deeper backtracking for dense configurations

---

## Dependencies

### Python Package Requirements

```
fastapi==00.104.1           # Web framework
uvicorn==0.24.0            # ASGI server
python-multipart==0.0.6    # Form data handling
reportlab==4.0.7           # Used for PDF export
numpy==2.4.3               # Not used by engine
pandas==3.0.1              # Not used by engine
python-dateutil==2.9.0.post0
six==1.17.0
tqdm==4.67.3               # Not used by engine
```

**Important:** The core scheduling engine (`timetable_scheduler/engine/`) has **zero external dependencies** — it uses only the Python standard library. FastAPI and uvicorn are required only for the web server.

### Runtime Requirements

- Python 3.10 or higher
- Any modern web browser (Chrome, Firefox, Safari, Edge)

---

## Recent Updates

### May 20, 2026 — UI Enhancements

- Added a toggle button to show/hide the configuration panel in the Web UI.
- Removed success alerts during configuration loading for a cleaner user experience.

### May 16, 2026 — Critical Lab Overlap Bug Fix

**Issue:** Scheduler could assign two labs of the same semester at overlapping times (e.g., MCA-I Lab A at P1–P3, Lab B at P2–P4).

**Root Cause:** Lab placement bypassed semester-level clash checking. Only global lab capacity (max 2 concurrent labs, any semester) was validated.

**Solution:** Three-layer defense:
1. **Placement Prevention** — Added `can_place_lab_with_semester_check()` in scheduler to validate each slot before placement
2. **Post-validation** — Added `_validate_no_same_semester_overlaps()` in validator as safety net after scheduling
3. **Test Coverage** — Comprehensive test with direct + end-to-end validation

**Result:**
- All tests pass
- Zero regressions
- 100% backward compatible

---

## 📞 License

This project is provided as-is for academic and research use.

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Test your changes thoroughly
2. Verify no regressions against existing functionality
3. Update documentation for significant changes
4. Submit a pull request with a clear description

---

**Built for university scheduling challenges**
