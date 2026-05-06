"""
tests/observability/ — Structured observability for E2E tests.

Provides:
  EventLogger     — JSON-lines event log writer (context manager)
  ScreenshotDiffer — Pixel-based image comparison (Pillow)
  ModelDiffer      — Deep JSON model diff
  diagnose         — CLI tool for failure report generation
"""

from .event_logger import EventLogger
from .screenshot_diff import ScreenshotDiffer
from .model_diff import ModelDiffer

__all__ = [
    "EventLogger",
    "ScreenshotDiffer",
    "ModelDiffer",
]
