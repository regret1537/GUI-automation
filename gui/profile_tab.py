"""
Tab 3: Profile 編輯器

Profile 就是「打哪裡、怎麼判斷狀態、狀態下要做什麼」的 JSON 設定檔。
這裡提供陽春但實用的 JSON 文字編輯器 + Load/Save/Validate，
以及把目前「座標錄製器」錄好的座標一鍵匯入 profile["coordinates"] 的按鈕
（座標跟 profile 是分開管理的，需要手動同步，避免誤蓋掉已存檔的內容）。
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json

from core import profile_io


STATE_SNIPPET = """    "新狀態名稱": {
      "match_mode": "any",
      "anchors": [
        {"template_path": "templates/xxx.png", "region": null, "confidence": 0.85}
      ],
      "on_enter_actions": [
        {"type": "click", "coord_label": "某個座標label"},
        {"type": "wait", "seconds": 0.5}
      ]
    },
"""


class ProfileTab(ttk.Frame):
    def __init__(self, parent, coord_registry, logger, on_profile_loaded, window_lock_panel=None):
        super().__init__(parent)
        self.registry = coord_registry
        self.logger = logger
        self.on_profile_loaded = on_profile_loaded  # callback(profile_dict, path)
        self.window_lock_panel = window_lock_panel
        self.current_path = None
        self._build_ui()
        self._load_dict(profile_io.new_empty_profile())

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=4)
        ttk.Button(top, text="新增空白 Profile", command=self._new_profile).pack(side="left")
        ttk.Button(top, text="開啟...", command=self._open_profile).pack(side="left", padx=4)
        ttk.Button(top, text="儲存", command=self._save_profile).pack(side="left", padx=4)
        ttk.Button(top, text="另存新檔...", command=self._save_as_profile).pack(side="left", padx=4)
        ttk.Button(top, text="驗證格式", command=self._validate).pack(side="left", padx=12)
        ttk.Button(top, text="匯入已錄座標", command=self._import_coords).pack(side="left", padx=4)
        ttk.Button(top, text="同步視窗鎖定設定", command=self._sync_window_lock).pack(side="left", padx=4)
        ttk.Button(top, text="插入狀態範本", command=self._insert_state_snippet).pack(side="left", padx=4)

        self.path_label = ttk.Label(self, text="(尚未儲存)")
        self.path_label.pack(fill="x", padx=8)

        self.text = tk.Text(self, wrap="none", undo=True, font=("Menlo", 11))
        self.text.pack(fill="both", expand=True, padx=8, pady=4)

        yscroll = ttk.Scrollbar(self.text, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=yscroll.set)

    def _load_dict(self, data: dict, path: str = None):
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))
        self.current_path = path
        self.path_label.config(text=path or "(尚未儲存)")

    def _current_dict(self) -> dict:
        raw = self.text.get("1.0", tk.END)
        return json.loads(raw)

    def _new_profile(self):
        self._load_dict(profile_io.new_empty_profile("新 profile"))

    def _open_profile(self):
        path = filedialog.askopenfilename(filetypes=[("JSON profile", "*.json")])
        if not path:
            return
        try:
            data = profile_io.load_profile(path)
        except Exception as e:
            messagebox.showerror("讀取失敗", str(e))
            return
        self._load_dict(data, path)
        if self.on_profile_loaded:
            self.on_profile_loaded(data, path)
        if self.logger:
            self.logger.info(f"已載入 profile: {path}")

    def _save_profile(self):
        if not self.current_path:
            self._save_as_profile()
            return
        self._write_to(self.current_path)

    def _save_as_profile(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON profile", "*.json")])
        if not path:
            return
        self._write_to(path)

    def _write_to(self, path):
        try:
            data = self._current_dict()
            profile_io.save_profile(path, data)
        except Exception as e:
            messagebox.showerror("儲存失敗", str(e))
            return
        self.current_path = path
        self.path_label.config(text=path)
        if self.logger:
            self.logger.info(f"已儲存 profile: {path}")
        if self.on_profile_loaded:
            self.on_profile_loaded(data, path)

    def _validate(self):
        try:
            data = self._current_dict()
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON 語法錯誤", str(e))
            return
        errors = profile_io.validate_profile(data)
        if errors:
            messagebox.showerror("Profile 格式錯誤", "\n".join(errors))
        else:
            messagebox.showinfo("驗證通過", "Profile 結構正確。")

    def _import_coords(self):
        try:
            data = self._current_dict()
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON 語法錯誤", "請先修正 JSON 語法錯誤再匯入。\n" + str(e))
            return
        data["coordinates"] = data.get("coordinates", {})
        for label, entry in self.registry.all_entries().items():
            data["coordinates"][label] = {
                "x": entry.x, "y": entry.y, "note": entry.note, "relative": entry.relative,
            }
        self._load_dict(data, self.current_path)
        messagebox.showinfo("完成", f"已匯入 {len(self.registry.all_entries())} 個座標。")

    def _sync_window_lock(self):
        if not self.window_lock_panel:
            return
        try:
            data = self._current_dict()
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON 語法錯誤", "請先修正 JSON 語法錯誤再同步。\n" + str(e))
            return
        if not self.window_lock_panel.is_locked():
            data.pop("window_lock", None)
            messagebox.showinfo("完成", "目前面板未鎖定視窗，已移除 profile 裡的 window_lock 設定。")
        else:
            data["window_lock"] = self.window_lock_panel.get_lock_config()
            messagebox.showinfo("完成", f"已寫入 window_lock: {data['window_lock']}")
        self._load_dict(data, self.current_path)

    def _insert_state_snippet(self):
        self.text.insert(tk.INSERT, STATE_SNIPPET)
