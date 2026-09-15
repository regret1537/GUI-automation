"""
Tab 1: 座標錄製器

用「倒數 3 秒後擷取滑鼠位置」的方式錄座標（不需要額外的系統權限，
比全域熱鍵更容易跨平台運作）：
  1. 使用者在下方輸入這個座標的 label
  2. 按「開始錄製」
  3. 3 秒內把滑鼠移到目標畫面上要點的位置
  4. 時間到自動擷取 pyautogui.position()，寫入表格
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    pyautogui = None
    PYAUTOGUI_AVAILABLE = False


class CoordTab(ttk.Frame):
    def __init__(self, parent, coord_registry, logger, window_lock_panel=None):
        super().__init__(parent)
        self.registry = coord_registry
        self.logger = logger
        self.window_lock_panel = window_lock_panel  # 有鎖定視窗時，錄製會自動存成相對座標
        self._build_ui()
        self.refresh_table()

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=8)

        ttk.Label(top, text="Label:").pack(side="left")
        self.label_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.label_var, width=20).pack(side="left", padx=4)

        ttk.Label(top, text="備註:").pack(side="left", padx=(12, 0))
        self.note_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.note_var, width=24).pack(side="left", padx=4)

        self.record_btn = ttk.Button(top, text="開始錄製 (3秒倒數)", command=self._start_record)
        self.record_btn.pack(side="left", padx=12)

        self.countdown_label = ttk.Label(top, text="", foreground="red")
        self.countdown_label.pack(side="left", padx=8)

        self.lock_hint_label = ttk.Label(self, text="", foreground="gray")
        self.lock_hint_label.pack(fill="x", padx=8)

        # 表格
        cols = ("label", "x", "y", "relative", "note")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=14)
        headers = {"label": "label", "x": "x", "y": "y", "relative": "相對座標?", "note": "note"}
        for c, w in zip(cols, (140, 60, 60, 80, 200)):
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=w)
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=8, pady=4)
        ttk.Button(btn_row, text="刪除選取", command=self._delete_selected).pack(side="left")
        ttk.Button(btn_row, text="重新整理", command=self.refresh_table).pack(side="left", padx=8)

        if not PYAUTOGUI_AVAILABLE:
            ttk.Label(
                self,
                text="⚠ 偵測不到可用的顯示器 / pyautogui 無法載入，此分頁只能瀏覽既有座標，無法實際錄製。",
                foreground="orange",
            ).pack(fill="x", padx=8, pady=4)

    def _start_record(self):
        label = self.label_var.get().strip()
        if not label:
            messagebox.showwarning("缺少 Label", "請先輸入這個座標的 label")
            return
        if not PYAUTOGUI_AVAILABLE:
            messagebox.showerror("無法錄製", "此環境沒有可用的顯示器，無法擷取滑鼠位置。")
            return
        self.record_btn.config(state="disabled")
        threading.Thread(target=self._countdown_and_capture, args=(label, self.note_var.get()), daemon=True).start()

    def _countdown_and_capture(self, label, note):
        locked = bool(self.window_lock_panel and self.window_lock_panel.is_locked())
        for remaining in (3, 2, 1):
            hint = "（將存成視窗相對座標）" if locked else "（將存成螢幕絕對座標）"
            self.countdown_label.config(text=f"請把滑鼠移到目標位置... {remaining} {hint}")
            time.sleep(1)
        x, y = pyautogui.position()

        if locked:
            rect = self.window_lock_panel.get_current_rect()
            if rect is None:
                self.countdown_label.config(text="錄製失敗：目前抓不到已鎖定視窗的位置")
                if self.logger:
                    self.logger.error(f"錄製座標 {label} 失敗：視窗鎖定中但抓不到視窗位置")
                self.record_btn.config(state="normal")
                return
            rel_x, rel_y = x - rect[0], y - rect[1]
            self.registry.set(label, rel_x, rel_y, note, relative=True)
            self.countdown_label.config(text=f"已錄製 {label} = 相對座標 ({rel_x},{rel_y})，視窗內")
            if self.logger:
                self.logger.info(f"錄製座標 {label} = 相對座標 ({rel_x},{rel_y})（視窗: {self.window_lock_panel.locked_title}）")
        else:
            self.registry.set(label, x, y, note, relative=False)
            self.countdown_label.config(text=f"已錄製 {label} = 絕對座標 ({x},{y})")
            if self.logger:
                self.logger.info(f"錄製座標 {label} = 絕對座標 ({x},{y})")

        self.record_btn.config(state="normal")
        self.label_var.set("")
        self.note_var.set("")
        self.refresh_table()

    def _delete_selected(self):
        for item in self.tree.selection():
            label = self.tree.item(item, "values")[0]
            self.registry.remove(label)
        self.refresh_table()

    def refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for label, entry in self.registry.all_entries().items():
            self.tree.insert("", "end", values=(label, entry.x, entry.y, "是" if entry.relative else "否", entry.note))

        if self.window_lock_panel and self.window_lock_panel.is_locked():
            self.lock_hint_label.config(
                text=f"視窗鎖定中：「{self.window_lock_panel.locked_title}」— 接下來錄製的座標會是相對於視窗左上角的偏移量。"
            )
        else:
            self.lock_hint_label.config(text="目前未鎖定視窗 — 錄製的座標會是螢幕絕對座標。")
