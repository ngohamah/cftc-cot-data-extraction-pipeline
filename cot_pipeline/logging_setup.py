"""Logging to a file (full history) and to the console (progress)."""

import logging
import sys

import config

# every module logs through a child of this logger (logging.getLogger(__name__))
LOGGER_NAME = "cot_pipeline"


def configure_logging(log_file=config.LOG_FILE):
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(log_file)
    console_handler = logging.StreamHandler(sys.stdout)
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers = [file_handler, console_handler]
    logger.setLevel(logging.INFO)
