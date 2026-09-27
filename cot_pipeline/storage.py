"""Reading and writing files: atomic full writes, appends of new rows, and loading saved CSVs."""

import logging
import os
import tempfile
from pathlib import Path

import pandas as pd

import config
from cot_pipeline.transform import missing_columns

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


def ends_with_newline(path):
    with open(path, "rb") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            return True
        handle.seek(-1, os.SEEK_END)
        return handle.read(1) == b"\n"


def append_csv(dataframe, path):
    """Append rows (no header) to the end of an existing CSV; saved rows are left untouched."""
    needs_newline = not ends_with_newline(path)
    with open(path, "a", newline="") as handle:
        if needs_newline:
            handle.write("\n")
        dataframe.to_csv(handle, index=False, header=False)
        handle.flush()
        os.fsync(handle.fileno())


def read_saved_csv(path, required=config.SPECIAL_COLUMNS):
    """A saved CSV as-is, or None if missing/unreadable/missing columns (it is then written in full)."""
    if not path.exists():
        logger.warning("%s not found - it will be created", path)
        return None
    try:
        saved = pd.read_csv(path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as err:
        logger.error("Could not read %s (%s) - it will be rewritten in full", path, err)
        return None
    missing = missing_columns(saved, required)
    if missing:
        logger.error("%s is missing columns %s - it will be rewritten in full", path, missing)
        return None
    return saved
