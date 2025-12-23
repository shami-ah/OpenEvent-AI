"""
Shared constants for the Q&A module.

CANONICAL LOCATION: backend/workflows/common/qna/constants.py
EXTRACTED FROM: backend/workflows/common/general_qna.py
"""

CLIENT_AVAILABILITY_HEADER = "Availability overview"

ROOM_IDS = ["Room A", "Room B", "Room C"]

LAYOUT_KEYWORDS = {
    "u-shape": "U-shape",
    "u shape": "U-shape",
    "boardroom": "Boardroom",
    "board-room": "Boardroom",
}

FEATURE_KEYWORDS = {
    "projector": "Projector",
    "projectors": "Projector",
    "flipchart": "Flip chart",
    "flipcharts": "Flip chart",
    "flip chart": "Flip chart",
    "screen": "Screen",
    "hdmi": "HDMI",
    "sound system": "Sound system",
    "sound": "Sound system",
}

CATERING_KEYWORDS = {
    "lunch": "Light lunch",
    "coffee": "Coffee break service",
    "tea": "Coffee break service",
    "break": "Coffee break service",
}

STATUS_PRIORITY = {
    "available": 0,
    "option": 1,
    "hold": 2,
    "waitlist": 3,
    "unavailable": 4,
}

MONTH_INDEX_TO_NAME = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

_MENU_ONLY_SUBTYPES = {
    "product_catalog",
    "product_truth",
    "product_recommendation_for_us",
    "repertoire_check",
}

_ROOM_MENU_SUBTYPES = {
    "room_catalog_with_products",
    "room_product_truth",
}

_DATE_PARSE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%a %d %b %Y",
    "%A %d %B %Y",
)

DEFAULT_NEXT_STEP_LINE = "- Confirm your preferred date (and any other must-haves) so I can fast-track the next workflow step for you."
DEFAULT_ROOM_NEXT_STEP_LINE = "- Confirm the room you like (and any final requirements) so I can move ahead with the offer preparation."

__all__ = [
    "CLIENT_AVAILABILITY_HEADER",
    "ROOM_IDS",
    "LAYOUT_KEYWORDS",
    "FEATURE_KEYWORDS",
    "CATERING_KEYWORDS",
    "STATUS_PRIORITY",
    "MONTH_INDEX_TO_NAME",
    "_MENU_ONLY_SUBTYPES",
    "_ROOM_MENU_SUBTYPES",
    "_DATE_PARSE_FORMATS",
    "DEFAULT_NEXT_STEP_LINE",
    "DEFAULT_ROOM_NEXT_STEP_LINE",
]
