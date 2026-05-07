"""Central logging configuration for the SketchUp Link Blender addon."""

import logging
import logging.handlers
import os
import tempfile

LOG_FILE = os.path.join(tempfile.gettempdir(), "sketchup-link-blender.log")
MAX_BYTES = 2 * 1024 * 1024  # 2MB
BACKUP_COUNT = 3

_logger = None


def get_logger(name: str = "sketchup_link") -> logging.Logger:
    """Returns the addon-wide logger. Creates RotatingFileHandler on first call."""
    global _logger
    if _logger is not None:
        return _logger
    _logger = logging.getLogger(name)
    _logger.setLevel(logging.DEBUG)  # handler level controls actual output
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT
    )
    handler.setLevel(logging.INFO)  # default; override via prefs
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s %(message)s"
    ))
    _logger.addHandler(handler)
    # Also log to Blender console at WARNING+ for visibility
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter("[sketchup-link] %(levelname)s: %(message)s"))
    _logger.addHandler(console)
    return _logger


def set_level(level: str) -> None:
    """Set log level (DEBUG/INFO/WARNING/ERROR) on the file handler."""
    logger = get_logger()
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }
    mapped = level_map.get(level.upper())
    if mapped is not None:
        logger.handlers[0].setLevel(mapped)


def set_file_path(path: str) -> None:
    """Change the log file path (creates new handler). Only works before first get_logger call."""
    global _logger, LOG_FILE
    if _logger is not None:
        return  # already initialized, can't change
    LOG_FILE = path
