"""
視窗鎖定面板 — 顯示在主視窗最上方，橫跨所有分頁。

放在這裡（而不是塞進某一個分頁）是因為「鎖定哪個視窗」是跨分頁的共用狀態：
座標錄製要知道現在鎖定哪個視窗才能算相對座標，執行監控要用它來解析座標、限制偵測範圍。
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox

from core.window_manager import WindowManager, WINDOW_MGMT_AVAILABLE
from core import win32_backend


class WindowLockPanel(ttk.LabelFrame):
    def __init__(self, parent, window_manager: WindowManager, logger):
        super().__init__(parent, text="視窗鎖定 (選填 — 不鎖定就是全螢幕絕對座標模式)")
        self.wm = window_manager
        self.logger = logger
        self.locked_title: str | None = None
        self.activate_var = tk.BooleanVar(value=True)
        self._build_ui()
        self.refresh_window_list()

    def _build_ui(self):
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=4)

        ttk.Label(row, text="目標視窗標題關鍵字:").pack(side="left")
        self.title_var = tk.StringVar()
        self.combo = ttk.Combobox(row, textvariable=self.title_var, width=40)
        self.combo.pack(side="left", padx=4)

        ttk.Button(row, text="重新整理視窗列表", command=self.refresh_window_list).pack(side="left", padx=4)
        self.lock_btn = ttk.Button(row, text="鎖定", command=self._lock)
        self.lock_btn.pack(side="left", padx=4)
        self.unlock_btn = ttk.Button(row, text="解除鎖定", command=self._unlock, state="disabled")
        self.unlock_btn.pack(side="left", padx=4)

        self.capture_test_btn = ttk.Button(row, text="測試背景擷取", command=self._test_background_capture, state="disabled")
        self.capture_test_btn.pack(side="left", padx=4)

        ttk.Checkbutton(row, text="執行前自動置頂視窗", variable=self.activate_var).pack(side="left", padx=12)

        self.status_label = ttk.Label(self, text=self._status_text(), foreground="gray")
        self.status_label.pack(fill="x", padx=6, pady=(0, 4))

        if not WINDOW_MGMT_AVAILABLE:
            ttk.Label(
                self,
                text="⚠ pywinctl 無法載入，視窗鎖定功能不可用（見 requirements.txt）。座標仍可用全螢幕絕對模式。",
                foreground="orange",
            ).pack(fill="x", padx=6, pady=(0, 4))
            self.combo.config(state="disabled")
            self.lock_btn.config(state="disabled")

    def _status_text(self) -> str:
        if not self.locked_title:
            return "目前狀態: 未鎖定（座標錄製 = 螢幕絕對座標）"
        rect = self.wm.get_rect(self.locked_title)
        if rect is None:
            return f"目前狀態: 已鎖定「{self.locked_title}」，但目前找不到這個視窗（可能被關閉或最小化）"
        return f"目前狀態: 已鎖定「{self.locked_title}」 @ (x={rect[0]}, y={rect[1]}, w={rect[2]}, h={rect[3]})"

    def refresh_window_list(self):
        titles = sorted(set(t for t in self.wm.list_windows() if t.strip()))
        self.combo["values"] = titles

    def _lock(self):
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("未輸入標題", "請先從下拉選單選擇，或輸入視窗標題的一部分。")
            return
        rect = self.wm.get_rect(title)
        if rect is None:
            if not messagebox.askyesno(
                "目前找不到這個視窗",
                f"目前抓不到標題包含「{title}」的視窗，仍要鎖定嗎？（可以先鎖定，等視窗開啟後執行時會自動抓）",
            ):
                return
        self.locked_title = title
        self.lock_btn.config(state="disabled")
        self.unlock_btn.config(state="normal")
        self.combo.config(state="disabled")
        self.capture_test_btn.config(state="normal" if win32_backend.WIN32_AVAILABLE else "disabled")
        self.status_label.config(text=self._status_text())
        if self.logger:
            self.logger.info(f"視窗鎖定 -> 「{title}」")

    def _unlock(self):
        self.locked_title = None
        self.lock_btn.config(state="normal")
        self.unlock_btn.config(state="disabled")
        self.combo.config(state="normal")
        self.capture_test_btn.config(state="disabled")
        self.status_label.config(text=self._status_text())
        if self.logger:
            self.logger.info("視窗鎖定已解除")

    def is_locked(self) -> bool:
        return self.locked_title is not None

    def get_current_rect(self):
        if not self.locked_title:
            return None
        return self.wm.get_rect(self.locked_title)

    def get_lock_config(self) -> dict:
        return {
            "title_substring": self.locked_title,
            "activate_before_action": bool(self.activate_var.get()),
        }

    def _test_background_capture(self):
        if not self.locked_title:
            messagebox.showwarning("尚未鎖定", "請先鎖定目標視窗。")
            return
        hwnd = self.wm.get_handle(self.locked_title)
        try:
            frame = win32_backend.capture_window(hwnd) if hwnd else None
        except Exception as exc:
            messagebox.showerror("背景擷取失敗", str(exc))
            return
        if frame is None:
            messagebox.showerror(
                "背景擷取不相容",
                "沒有取得有效畫面。這個程式可能使用 DirectX 獨佔畫面或受保護渲染；請改用前景模式。",
            )
            return
        height, width = frame.shape[:2]
        messagebox.showinfo("背景擷取成功", f"成功取得 {width} × {height} 畫面。\n仍需實際測試遊戲是否接受背景輸入。")

    def refresh_status(self):
        self.status_label.config(text=self._status_text())
