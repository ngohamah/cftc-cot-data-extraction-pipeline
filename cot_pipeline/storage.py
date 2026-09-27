"""Reading and writing files: atomic writes and loading saved symbol data."""

import logging
import os
import tempfile
from pathlib import Path

import pandas as pd

from cot_pipeline.transform import clean_report, missing_columns

logger = logging.getLogger(__name__)


def write_atomically(path, write):
    """Write via a temp file in the same folder, then rename, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        write(tmp)
        os.chmod(tmp, 0o644)  # mkstemp creates owner-only files
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_csv(dataframe, path):
    write_atomically(path, lambda tmp: dataframe.to_csv(tmp, index=False))


def write_text(text, path):
    write_atomically(path, lambda tmp: Path(tmp).write_text(text))


def write_bytes(data, path):
    write_atomically(path, lambda tmp: Path(tmp).write_bytes(data))


def read_existing(path):
    """Saved data for a symbol, or None if missing/unreadable (it is then rebuilt)."""
    if not path.exists():
        logger.warning("%s not found - it will be created", path)
        return None
    try:
        existing = pd.read_csv(path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as err:
        logger.error("Could not read %s (%s) - it will be rebuilt", path, err)
        return None
    missing = missing_columns(existing)
    if missing:
        logger.error("%s is missing columns %s - it will be rebuilt", path, missing)
        return None
    return clean_report(existing)[0]
