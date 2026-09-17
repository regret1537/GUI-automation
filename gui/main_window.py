"""
主視窗：把四個分頁組起來。
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
import os

from core.coordinate_registry import CoordinateRegistry
from core.logger import Logger
from core.window_manager import WindowManager
from gui.coord_tab import CoordTab
from gui.template_tab import TemplateTab
from gui.profile_tab import ProfileTab
from gui.run_tab import RunTab
from gui.window_lock_panel import WindowLockPanel


class MainWindow(tk.Tk):
    def __init__(self, base_dir: str):
        super().__init__()
        self.title("GUI Automation Framework — 通用桌面自動化框架")
        self.geometry("1180x820")
        self.minsize(980, 680)

        self.base_dir = base_dir
        self.templates_dir = os.path.join(base_dir, "templates")
        self.logs_dir = os.path.join(base_dir, "logs")

        self.logger = Logger(log_dir=self.logs_dir)
        self.coord_registry = CoordinateRegistry()
        self.window_manager = WindowManager(logger=self.logger)

        self._current_profile = {"coordinates": {}, "states": {}, "name": "未命名"}

        self.window_lock_panel = WindowLockPanel(self, self.window_manager, self.logger)
        self.window_lock_panel.pack(fill="x", padx=8, pady=(8, 0))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.coord_tab = CoordTab(notebook, self.coord_registry, self.logger, self.window_lock_panel)
        self.template_tab = TemplateTab(notebook, self, self.templates_dir, self.logger)
        self.profile_tab = ProfileTab(
            notebook, self.coord_registry, self.logger, self._on_profile_loaded, self.window_lock_panel
        )
        self.run_tab = RunTab(
            notebook, self._get_current_profile, self.logger, self.window_lock_panel, self.window_manager
        )

        notebook.add(self.coord_tab, text="① 座標錄製")
        notebook.add(self.template_tab, text="② 狀態錨點截圖")
        notebook.add(self.profile_tab, text="③ 圖形化流程設定")
        notebook.add(self.run_tab, text="④ 執行監控")

        # 切分頁時把座標錄製分頁的「目前鎖定狀態」提示刷新一下，避免顯示過期資訊
        notebook.bind("<<NotebookTabChanged>>", lambda e: self.coord_tab.refresh_table())

        self.logger.info(f"框架啟動。templates 目錄: {self.templates_dir}")
        self.logger.info("此為通用框架，未內建任何特定目標網站/程式的設定，請自行建立 profile。")

    def _on_profile_loaded(self, profile: dict, path: str):
        self._current_profile = profile

    def _get_current_profile(self) -> dict:
        # 一律以 Profile 分頁目前的文字內容為準（使用者可能編輯了還沒存檔）
        return self.profile_tab._current_dict()
