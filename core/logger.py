"""
簡單的雙輸出 logger：同時寫檔案 + 呼叫 GUI callback。
GUI 不一定存在（例如未來有人想寫 headless CLI 版），所以 callback 是可選的。
"""
from __future__ import annotations
import datetime
import os
import threading
from typing import Callable, Optional

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR", "EVENT")


class Logger:
    def __init__(self, log_dir: str = "logs", gui_callback: Optional[Callable[[str, str], None]] = None):
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(log_dir, f"run_{ts}.log")
        self.gui_callback = gui_callback
        self._lock = threading.Lock()

    def set_gui_callback(self, cb: Optional[Callable[[str, str], None]]):
        self.gui_callback = cb

    def log(self, level: str, message: str):
        if level not in LEVELS:
            level = "INFO"
        now = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{now}] [{level}] {message}"
        with self._lock:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
        if self.gui_callback:
            try:
                self.gui_callback(level, line)
            except Exception:
                pass

    def debug(self, msg): self.log("DEBUG", msg)
    def info(self, msg): self.log("INFO", msg)
    def warn(self, msg): self.log("WARN", msg)
    def error(self, msg): self.log("ERROR", msg)
    def event(self, msg): self.log("EVENT", msg)
