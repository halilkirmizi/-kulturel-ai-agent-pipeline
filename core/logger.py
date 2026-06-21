"""Structured logging for the pipeline.

Usage:
    from core.logger import get_logger
    log = get_logger(__name__)
    log.info("Processing clip %s", clip_id)
    log.warning("GPU unavailable, falling back to CPU")
    log.error("FFmpeg failed", exc_info=True)
"""

import logging
import sys
from pathlib import Path


def setup_logging(log_dir: str | Path = "logs", level: str = "INFO") -> None:
    """Configure root logger: console + file."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    # File handler (rotated per run)
    run_log = log_dir / f"pipeline_{__import__('datetime').datetime.now():%Y%m%d_%H%M%S}.log"
    fh = logging.FileHandler(run_log, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Get a module-level logger."""
    return logging.getLogger(name)


# Auto-setup on import if not already configured
if not logging.getLogger().hasHandlers():
    setup_logging()
