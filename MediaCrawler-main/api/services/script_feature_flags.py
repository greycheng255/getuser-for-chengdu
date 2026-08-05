import os


def unified_script_library_enabled() -> bool:
    return os.getenv("UNIFIED_SCRIPT_LIBRARY_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
