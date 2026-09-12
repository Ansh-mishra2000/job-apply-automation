"""
Custom logger with Rich console styling and file logging support.
"""

import logging
from pathlib import Path
import sys
from rich.console import Console
from rich.theme import Theme

custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "step": "bold magenta",
    "highlight": "bold yellow",
})

console = Console(theme=custom_theme)

class AppLogger:
    def __init__(self, log_file: str = "data/logs/apply.log"):
        base_dir = Path(__file__).parent.parent.resolve()
        self.log_path = base_dir / log_file
        self.log_path.parent.mkdir(exist_ok=True, parents=True)

        self._file_logger = logging.getLogger("JobApplyAutomation")
        self._file_logger.setLevel(logging.DEBUG)

        if not self._file_logger.handlers:
            fh = logging.FileHandler(str(self.log_path), encoding="utf-8")
            formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
            fh.setFormatter(formatter)
            self._file_logger.addHandler(fh)

    def info(self, msg: str):
        console.print(f"[info]ℹ [INFO][/info] {msg}")
        self._file_logger.info(msg)

    def success(self, msg: str):
        console.print(f"[success]✔ [SUCCESS][/success] {msg}")
        self._file_logger.info(f"[SUCCESS] {msg}")

    def warning(self, msg: str):
        console.print(f"[warning]⚠ [WARNING][/warning] {msg}")
        self._file_logger.warning(msg)

    def error(self, msg: str):
        console.print(f"[error]✖ [ERROR][/error] {msg}")
        self._file_logger.error(msg)

    def step(self, msg: str):
        console.print(f"[step]➔ [STEP][/step] {msg}")
        self._file_logger.info(f"[STEP] {msg}")


logger = AppLogger()
