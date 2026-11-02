"""Load the shared learner profile."""
from __future__ import annotations

import yaml

from . import config


def load_profile() -> dict:
    return yaml.safe_load(config.PROFILE_PATH.read_text(encoding="utf-8"))
