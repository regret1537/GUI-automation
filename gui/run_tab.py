"""
Tab 4: 執行監控台

Start / Pause / Resume / Stop 四個生命週期按鈕 + 即時 log 面板 + 目前狀態顯示。
StateMachine 是在按下 Start 的當下才用「目前 Profile 編輯器裡的內容」重新建立，
這樣使用者調整 profile 後不需要重開程式，按 Start 就會套用最新設定。
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
import json

from core.state_machine import StateMachine
from core import profile_io


class RunTab(ttk.Frame):
    def __init__(self, parent, get_current_profile_fn, logger, window_lock_panel=None, window_manager=None):
        super().__init__(parent)
        self.get_current_profile_fn = get_current_profile_fn
        self.logger = logger
        self.window_lock_panel = window_lock_panel
        self.window_manager = window_manager
        self.machine: StateMachine | None = None
        self._build_ui()
        self.logger.set_gui_callback(self._append_log)

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=8)

        self.start_btn = ttk.Button(top, text="▶ Start", command=self._on_start)
        self.start_btn.pack(side="left")
        self.pause_btn = ttk.Button(top, text="⏸ Pause", command=self._on_pause, state="disabled")
        self.pause_btn.pack(side="left", padx=4)
        self.resume_btn = ttk.Button(top, text="⏵ Resume", command=self._on_resume, state="disabled")
        self.resume_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(top, text="⏹ Stop", command=self._on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)

        status = ttk.Frame(self)
        status.pack(fill="x", padx=8, pady=4)
        ttk.Label(status, text="目前狀態:").pack(side="left")
        self.state_label = ttk.Label(status, text="-", font=("Menlo", 11, "bold"))
        self.state_label.pack(side="left", padx=6)
        ttk.Label(status, text="已執行動作數:").pack(side="left", padx=(20, 0))
        self.count_label = ttk.Label(status, text="0")
        self.count_label.pack(side="left", padx=6)
        ttk.Label(status, text="執行模式:").pack(side="left", padx=(20, 0))
        self.mode_label = ttk.Label(status, text="-")
        self.mode_label.pack(side="left", padx=6)

        ttk.Label(
            self,
            text="安全閥提醒：滑鼠移到螢幕任一角落 = 立即中止 (pyautogui FAILSAFE)。",
            foreground="gray",
        ).pack(fill="x", padx=8)

        self.log_text = tk.Text(self, height=24, state="disabled", bg="#111", fg="#ddd", font=("Menlo", 10))
        self.log_text.pack(fill="both", expand=True, padx=8, pady=6)
        self.log_text.tag_config("ERROR", foreground="#ff6b6b")
        self.log_text.tag_config("WARN", foreground="#feca57")
        self.log_text.tag_config("EVENT", foreground="#1dd1a1")
        self.log_text.tag_config("INFO", foreground="#c8d6e5")
        self.log_text.tag_config("DEBUG", foreground="#576574")

    def _append_log(self, level, line):
        # 這個 callback 可能從背景 thread 呼叫，Tk 的 UI 操作要丟回主 thread
        self.after(0, self._append_log_main_thread, level, line)

    def _append_log_main_thread(self, level, line):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, line + "\n", level)
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def _poll_status(self):
        if self.machine and self.machine._running:
            self.state_label.config(text=self.machine.last_state or "-")
            self.count_label.config(text=str(self.machine.action_count))
            self.after(500, self._poll_status)

    def _on_start(self):
        try:
            profile = self.get_current_profile_fn()
        except json.JSONDecodeError as e:
            messagebox.showerror("Profile JSON 錯誤", str(e))
            return
        if not profile.get("states") and not profile.get("brightness_triggers"):
            if not messagebox.askyesno("沒有定義任何流程", "目前 profile 沒有狀態或亮度觸發器，執行也不會做任何事。仍要啟動嗎？"):
                return

        # 就算使用者沒按「同步視窗鎖定設定」把它寫進 JSON，Start 當下也一律套用面板目前的鎖定狀態，
        # 這樣鎖定面板的操作結果不會因為忘記同步而被忽略。
        if self.window_lock_panel and self.window_lock_panel.is_locked():
            profile = dict(profile)
            profile["window_lock"] = self.window_lock_panel.get_lock_config()

        errors = profile_io.validate_profile(profile)
        if errors:
            messagebox.showerror("設定尚未完成", "\n".join(errors))
            return

        mode = (profile.get("execution") or {}).get("mode", "foreground")
        self.mode_label.config(text="Win32 背景" if mode == "win32_background" else "前景滑鼠")

        self.machine = StateMachine(profile, logger=self.logger, window_manager=self.window_manager)
        self.machine.on_state_change = lambda s: self.after(0, lambda: self.state_label.config(text=s))
        self.machine.start()

        self.start_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.resume_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._poll_status()

    def _on_pause(self):
        if self.machine:
            self.machine.pause()
            self.pause_btn.config(state="disabled")
            self.resume_btn.config(state="normal")

    def _on_resume(self):
        if self.machine:
            self.machine.resume()
            self.pause_btn.config(state="normal")
            self.resume_btn.config(state="disabled")

    def _on_stop(self):
        if self.machine:
            self.machine.stop()
        self.start_btn.config(state="normal")
        self.pause_btn.config(state="disabled")
        self.resume_btn.config(state="disabled")
        self.stop_btn.config(state="disabled")
        self.state_label.config(text="-")
        self.mode_label.config(text="-")
