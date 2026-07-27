import logging
import sys

logger = logging.getLogger("blacapi")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    # Flush every record immediately. Combined with PYTHONUNBUFFERED=1 in the
    # Dockerfile, this guarantees log lines show up in platform log viewers
    # (Railway/Render/etc.) right away instead of sitting in a buffer.
    handler.flush = lambda: sys.stdout.flush()
    logger.addHandler(handler)
    logger.propagate = False

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass
