import json
from pathlib import Path

PROFILES_DIR = Path(__file__).resolve().parent


def load_profile(name: str) -> dict:
    path = PROFILES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")
    return json.loads(path.read_text())
