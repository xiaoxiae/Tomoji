import os
import re
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
CAPTURES_DIR = DATA_DIR / "captures"
SETTINGS_FILE = DATA_DIR / "settings.yaml"
SESSIONS_DIR = DATA_DIR / "sessions"
EMOJI_TEST_FILE = Path(__file__).parent / "data" / "emoji-test.txt"

# Session configuration
SESSION_EXPIRY_DAYS = 7

# Ensure directories exist
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _parse_emoji_test_file() -> list[dict]:
    """Parse emoji-test.txt and extract face emoji categories."""
    # Subgroups to include (all face-related)
    FACE_SUBGROUPS = {
        "face-smiling", "face-affection", "face-tongue", "face-hand",
        "face-neutral-skeptical", "face-sleepy", "face-unwell", "face-hat",
        "face-glasses", "face-concerned", "face-negative", "face-costume",
    }

    # Human-readable names for subgroups
    SUBGROUP_NAMES = {
        "face-smiling": "Smiling Faces",
        "face-affection": "Affectionate Faces",
        "face-tongue": "Faces with Tongue",
        "face-hand": "Faces with Hand",
        "face-neutral-skeptical": "Neutral & Skeptical Faces",
        "face-sleepy": "Sleepy Faces",
        "face-unwell": "Unwell Faces",
        "face-hat": "Faces with Hat",
        "face-glasses": "Faces with Glasses",
        "face-concerned": "Concerned Faces",
        "face-negative": "Negative Faces",
        "face-costume": "Costume Faces",
    }

    categories = []
    current_subgroup = None
    current_emojis = []

    with open(EMOJI_TEST_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # Check for subgroup header
            if line.startswith("# subgroup:"):
                # Save previous subgroup if it was a face subgroup
                if current_subgroup in FACE_SUBGROUPS and current_emojis:
                    categories.append({
                        "id": current_subgroup,
                        "name": SUBGROUP_NAMES.get(current_subgroup, current_subgroup),
                        "emojis": current_emojis,
                    })

                current_subgroup = line.split(":", 1)[1].strip()
                current_emojis = []
                continue

            # Check for group header (reset subgroup tracking when leaving Smileys & Emotion)
            if line.startswith("# group:"):
                # Save any pending face subgroup
                if current_subgroup in FACE_SUBGROUPS and current_emojis:
                    categories.append({
                        "id": current_subgroup,
                        "name": SUBGROUP_NAMES.get(current_subgroup, current_subgroup),
                        "emojis": current_emojis,
                    })
                current_subgroup = None
                current_emojis = []
                continue

            # Skip if not in a face subgroup
            if current_subgroup not in FACE_SUBGROUPS:
                continue

            # Parse emoji line: "1F600 ; fully-qualified # 😀 E1.0 grinning face"
            if "; fully-qualified" in line and "#" in line:
                match = re.match(
                    r"^([A-F0-9 ]+)\s*;\s*fully-qualified\s*#\s*(\S+)\s+E[\d.]+\s+(.+)$",
                    line
                )
                if match:
                    codepoints_str, emoji_char, name = match.groups()
                    # Skip ZWJ sequences (multiple codepoints) - they don't render well
                    if " " in codepoints_str.strip():
                        continue
                    current_emojis.append({
                        "emoji": emoji_char,
                        "name": name.strip(),
                    })

    return categories


# Parse emoji categories from Unicode data file
EMOJI_CATEGORIES = _parse_emoji_test_file()

# Flat list for backwards compatibility (validation, font generation)
EMOJI_LIST = [e["emoji"] for cat in EMOJI_CATEGORIES for e in cat["emojis"]]

# Default capture parameters
DEFAULT_PADDING = 0
DEFAULT_OUTPUT_SIZE = 128
DEFAULT_KEEP_BACKGROUND = False
DEFAULT_KEEP_CLOTHES = False
DEFAULT_KEEP_ACCESSORIES = True

# Font settings
FONT_NAME = "Tomoji"

# Rate limits (requests per minute)
RATE_LIMIT_SESSION_CREATE = "50/minute"
RATE_LIMIT_SESSION_VALIDATE = "300/minute"
RATE_LIMIT_EMOJIS = "600/minute"
RATE_LIMIT_SETTINGS = "600/minute"
RATE_LIMIT_GALLERY = "600/minute"
RATE_LIMIT_PREVIEW = "300/minute"
RATE_LIMIT_CAPTURE = "600/minute"
RATE_LIMIT_CAPTURE_IMAGE = "1200/minute"
RATE_LIMIT_DELETE = "300/minute"
RATE_LIMIT_CLEAR_ALL = "10/minute"
RATE_LIMIT_EXPORT = "50/minute"
RATE_LIMIT_DOWNLOAD = "300/minute"
RATE_LIMIT_SESSION_DELETE = "50/minute"

# CORS origins (allow all in production behind reverse proxy)
CORS_ORIGINS = ["*"]
