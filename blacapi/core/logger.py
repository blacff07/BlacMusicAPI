import logging
import os
import sys

os.makedirs("logs", exist_ok=True)

_fmt = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)

_fh = logging.FileHandler("logs/blacapi.log", encoding="utf-8")
_fh.setFormatter(_fmt)

logger = logging.getLogger("BlacAPI")
logger.setLevel(logging.INFO)
logger.addHandler(_sh)
logger.addHandler(_fh)
logger.propagate = False
