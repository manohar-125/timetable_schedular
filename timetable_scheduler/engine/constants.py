"""timetable_scheduler.engine.constants

Centralized constants for the timetable scheduling system.
"""

from __future__ import annotations

# Time structure
DAYS: tuple[str, ...] = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
PERIODS: tuple[str, ...] = ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8")

# Grid dimensions
SLOTS_PER_DAY = 8
TOTAL_SLOTS = 5 * SLOTS_PER_DAY
LUNCH_BOUNDARY_PERIOD_INDEX = 4  # between P4 (3) and P5 (4)

# Lab constraints
LAB_BLOCK_SIZE = 3  # Labs must be 3 consecutive periods
# Labs may start at P1 (0), P2 (1), P5 (4), or P6 (5).
# Valid 3-period windows: P1-P3, P2-P4, P5-P7, P6-P8.
# P3-P5 and P4-P6 are invalid because they cross the lunch boundary.
LAB_VALID_START_PERIODS = (0, 1, 4, 5)
MAX_LABS_PER_SLOT = 2  # Maximum concurrent labs per time slot

# Credit to block mapping
# 3-credit: MUST be [2, 1] (one continuous 2-period block + one 1-period)
# 4-credit: randomly choose between [2, 2] or [2, 1, 1]
# 2-credit: single 2-period block
CREDIT_BLOCK_MAPPING = {
    2: [2],  # 2-credit courses: single 2-hour block
    3: [2, 1],  # 3-credit courses: one 2-period block + one 1-period
    4: [2, 2],  # 4-credit courses: default is two 2-period blocks (randomized at runtime)
}

# Alternative patterns for 4-credit courses (randomized selection)
CREDIT_4_ALTERNATIVES = [
    [2, 2],    # Two 2-period blocks
    [2, 1, 1], # One 2-period + two 1-period
]

# Default block pattern for unknown credits
DEFAULT_BLOCK_PATTERN = [1, 1, 1]


# Recourse mappings (source_semester -> target_semesters)
# One-hop recourse propagation for all programs, including IMTech
RECOURSE_TARGETS = {
    "MCA-I": {"MCA-III"},
    "MCA-II": {"MCA-IV"},
    "MTech-I": {"MTech-II"},
    "MTech-II": set(),

    # IMTech odd cycle
    "IMTech-I": {"IMTech-III"},
    "IMTech-III": {"IMTech-V"},
    "IMTech-V": {"IMTech-VII"},
    "IMTech-VII": set(),

    # IMTech even cycle
    "IMTech-II": {"IMTech-IV"},
    "IMTech-IV": {"IMTech-VI"},
    "IMTech-VI": {"IMTech-VIII"},
    "IMTech-VIII": set(),
}

# Supported programs
# IMTech-IX and IMTech-X are excluded (no regular classes)
SUPPORTED_PROGRAMS = {
    "MCA": ["MCA-I", "MCA-II", "MCA-III", "MCA-IV"],
    "MTech": ["MTech-I", "MTech-II"],
    "IMTech": [
        "IMTech-I", "IMTech-II", "IMTech-III", "IMTech-IV",
        "IMTech-V", "IMTech-VI", "IMTech-VII", "IMTech-VIII"
    ],
}

# Scheduling limits
MAX_SCHEDULING_ATTEMPTS = 200
MAX_ITERATIONS = 750000
MAX_BACKTRACK_DEPTH = 2

# Export settings
CSV_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

# Debug settings
DEBUG_MODE = False
MAX_DEBUG_TRACES = 200
