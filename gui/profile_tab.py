"""Tab 3：按鈕／表單式 Profile 編輯器。"""
from __future__ import annotations

import copy
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from core import profile_io
from core import brightness_detector, win32_backend
from core.win32_backend import compatibility_summary


MODE_LABELS = {
    "前景模式（使用實體滑鼠）": "foreground",
    "Win32 背景模式（實驗性，不移動滑鼠）": "win32_background",
}
MODE_NAMES = {value: key for key, value in MODE_LABELS.items()}


class ProfileTab(ttk.Frame):
    def __init__(self, parent, coord_registry, logger, on_profile_loaded, window_lock_panel=None):
        super().__init__(parent)
        self.registry, self.logger = coord_registry, logger
        self.on_profile_loaded, self.window_lock_panel = on_profile_loaded, window_lock_panel
        self.current_path = None
        self.data = profile_io.new_empty_profile()
        self._selected_state = None
        self._loading = False
        self._build_ui()
        self._load_dict(self.data)

    def _build_ui(self):
        files = ttk.Frame(self)
        files.pack(fill="x", padx=8, pady=(6, 2))
        for text, command in (
            ("＋ 新增", self._new_profile), ("開啟…", self._open_profile),
            ("儲存", self._save_profile), ("另存新檔…", self._save_as_profile),
            ("✓ 驗證設定", self._validate),
        ):
            ttk.Button(files, text=text, command=command).pack(side="left", padx=(0, 4))
        self.path_label = ttk.Label(files, text="(尚未儲存)", foreground="#666")
        self.path_label.pack(side="left", padx=10, fill="x", expand=True)

        self.editor_notebook = ttk.Notebook(self)
        self.editor_notebook.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        visual = ttk.Frame(self.editor_notebook)
        brightness = ttk.Frame(self.editor_notebook)
        advanced = ttk.Frame(self.editor_notebook)
        self.editor_notebook.add(visual, text="表單設定（建議）")
        self.editor_notebook.add(brightness, text="座標亮度觸發")
        self.editor_notebook.add(advanced, text="進階 JSON")
        self.editor_notebook.bind("<<NotebookTabChanged>>", self._on_editor_tab_changed)
        self._build_visual_editor(visual)
        self._build_brightness_editor(brightness)
        self._build_json_editor(advanced)

    def _build_visual_editor(self, parent):
        basic = ttk.LabelFrame(parent, text="1. 基本設定")
        basic.pack(fill="x", padx=4, pady=5)
        ttk.Label(basic, text="Profile 名稱").grid(row=0, column=0, padx=6, pady=5, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(basic, textvariable=self.name_var, width=24).grid(row=0, column=1, padx=4, pady=5, sticky="ew")
        ttk.Label(basic, text="檢查間隔（秒）").grid(row=0, column=2, padx=(16, 4), pady=5)
        self.interval_var = tk.StringVar(value="1.0")
        ttk.Spinbox(basic, from_=0.1, to=60, increment=0.1, textvariable=self.interval_var, width=8).grid(row=0, column=3)
        ttk.Label(basic, text="執行模式").grid(row=1, column=0, padx=6, pady=5, sticky="w")
        self.mode_var = tk.StringVar(value=MODE_NAMES["foreground"])
        mode = ttk.Combobox(basic, textvariable=self.mode_var, values=list(MODE_LABELS), state="readonly", width=38)
        mode.grid(row=1, column=1, columnspan=2, padx=4, pady=5, sticky="w")
        mode.bind("<<ComboboxSelected>>", lambda _e: self._update_mode_help())
        self.mode_help = ttk.Label(basic, foreground="#8a5a00", wraplength=760)
        self.mode_help.grid(row=2, column=0, columnspan=5, padx=6, pady=(0, 5), sticky="w")
        basic.columnconfigure(1, weight=1)

        tools = ttk.Frame(parent)
        tools.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(tools, text="匯入已錄座標", command=self._import_coords).pack(side="left")
        ttk.Button(tools, text="同步目前鎖定視窗", command=self._sync_window_lock).pack(side="left", padx=5)
        self.coord_count_label = ttk.Label(tools, foreground="#555")
        self.coord_count_label.pack(side="left", padx=8)

        states = ttk.LabelFrame(parent, text="2. 狀態、辨識圖片與執行動作")
        states.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        pane = ttk.Panedwindow(states, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=5, pady=5)
        left, right = ttk.Frame(pane, width=210), ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=4)
        ttk.Label(left, text="狀態（由上到下判斷）").pack(anchor="w")
        self.state_list = tk.Listbox(left, exportselection=False, height=15)
        self.state_list.pack(fill="both", expand=True, pady=4)
        self.state_list.bind("<<ListboxSelect>>", self._on_state_selected)
        state_buttons = ttk.Frame(left)
        state_buttons.pack(fill="x")
        for text, command in (("＋", self._add_state), ("刪除", self._delete_state), ("↑", lambda: self._move_state(-1)), ("↓", lambda: self._move_state(1))):
            ttk.Button(state_buttons, text=text, command=command, width=6).pack(side="left", padx=(0, 3))

        header = ttk.Frame(right)
        header.pack(fill="x")
        ttk.Label(header, text="狀態名稱").pack(side="left")
        self.state_name_var = tk.StringVar()
        ttk.Entry(header, textvariable=self.state_name_var, width=24).pack(side="left", padx=5)
        ttk.Label(header, text="圖片符合方式").pack(side="left", padx=(12, 3))
        self.match_mode_var = tk.StringVar(value="any")
        ttk.Combobox(header, textvariable=self.match_mode_var, values=("any", "all"), state="readonly", width=7).pack(side="left")
        ttk.Button(header, text="套用狀態設定", command=self._commit_state_form).pack(side="left", padx=8)

        anchor_box = ttk.LabelFrame(right, text="辨識圖片（Anchor）")
        anchor_box.pack(fill="both", expand=True, pady=(6, 3))
        self.anchor_tree = ttk.Treeview(anchor_box, columns=("file", "confidence", "region"), show="headings", height=5)
        for col, title, width in (("file", "圖片檔", 390), ("confidence", "準確度", 80), ("region", "搜尋範圍", 150)):
            self.anchor_tree.heading(col, text=title)
            self.anchor_tree.column(col, width=width, anchor="w")
        self.anchor_tree.pack(side="left", fill="both", expand=True)
        anchor_actions = ttk.Frame(anchor_box)
        anchor_actions.pack(side="right", fill="y", padx=4)
        ttk.Button(anchor_actions, text="＋ 選擇圖片", command=self._add_anchor).pack(fill="x", pady=2)
        ttk.Button(anchor_actions, text="編輯", command=self._edit_anchor).pack(fill="x", pady=2)
        ttk.Button(anchor_actions, text="刪除", command=self._delete_anchor).pack(fill="x", pady=2)

        action_box = ttk.LabelFrame(right, text="命中此狀態後依序執行")
        action_box.pack(fill="both", expand=True, pady=(3, 0))
        self.action_tree = ttk.Treeview(action_box, columns=("type", "detail"), show="headings", height=6)
        self.action_tree.heading("type", text="動作")
        self.action_tree.heading("detail", text="設定")
        self.action_tree.column("type", width=110)
        self.action_tree.column("detail", width=500)
        self.action_tree.pack(side="left", fill="both", expand=True)
        action_buttons = ttk.Frame(action_box)
        action_buttons.pack(side="right", fill="y", padx=4)
        for text, command in (("＋ 新增動作", self._add_action), ("編輯", self._edit_action), ("刪除", self._delete_action), ("↑ 上移", lambda: self._move_action(-1)), ("↓ 下移", lambda: self._move_action(1))):
            ttk.Button(action_buttons, text=text, command=command).pack(fill="x", pady=2)

    def _build_json_editor(self, parent):
        ttk.Label(parent, text="一般情況不必修改。手動修改後請按「套用 JSON 到表單」。", foreground="#666").pack(fill="x", padx=6, pady=4)
        self.text = tk.Text(parent, wrap="none", undo=True, font=("Consolas", 10))
        self.text.pack(fill="both", expand=True, padx=6, pady=3)
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=6, pady=5)
        ttk.Button(row, text="套用 JSON 到表單", command=self._apply_json).pack(side="left")
        ttk.Button(row, text="重新產生 JSON", command=self._refresh_json).pack(side="left", padx=5)

    def _build_brightness_editor(self, parent):
        ttk.Label(
            parent,
            text=("偵測指定座標附近是否發亮：達到亮度門檻就執行；若一直沒亮，超過設定秒數也會強制執行。"
                  " 可設定 F1～F12，再接滑鼠左鍵或右鍵。"),
            foreground="#555",
            wraplength=980,
        ).pack(fill="x", padx=8, pady=(10, 5))
        box = ttk.LabelFrame(parent, text="亮度觸發器")
        box.pack(fill="both", expand=True, padx=8, pady=5)
        columns = ("name", "watch", "threshold", "force", "actions")
        self.brightness_tree = ttk.Treeview(box, columns=columns, show="headings", height=15)
        for col, title, width in (
            ("name", "名稱", 150), ("watch", "偵測座標", 180),
            ("threshold", "亮度門檻", 90), ("force", "沒亮強制執行", 120),
            ("actions", "執行動作", 380),
        ):
            self.brightness_tree.heading(col, text=title)
            self.brightness_tree.column(col, width=width, anchor="w")
        self.brightness_tree.pack(fill="both", expand=True, padx=5, pady=5)
        buttons = ttk.Frame(box)
        buttons.pack(fill="x", padx=5, pady=(0, 6))
        ttk.Button(buttons, text="＋ 新增觸發器", command=self._add_brightness_trigger).pack(side="left")
        ttk.Button(buttons, text="編輯選取", command=self._edit_brightness_trigger).pack(side="left", padx=5)
        ttk.Button(buttons, text="刪除選取", command=self._delete_brightness_trigger).pack(side="left")
        ttk.Label(buttons, text="提示：請先在①錄製座標，再按『匯入已錄座標』。", foreground="#666").pack(side="left", padx=12)

    def _update_mode_help(self):
        if MODE_LABELS.get(self.mode_var.get()) == "win32_background":
            self.mode_help.config(text="背景模式不移動實體滑鼠，視窗可被遮住但不能最小化。" + compatibility_summary())
        else:
            self.mode_help.config(text="相容性最高，但執行時會控制實體滑鼠與鍵盤。")

    def _sync_basic_to_data(self):
        self.data["name"] = self.name_var.get().strip() or "未命名 profile"
        try:
            interval = float(self.interval_var.get())
            if interval <= 0:
                raise ValueError
        except ValueError:
            raise ValueError("檢查間隔必須是大於 0 的數字。")
        self.data["loop_interval_seconds"] = interval
        self.data["execution"] = {"mode": MODE_LABELS.get(self.mode_var.get(), "foreground")}
        self.data["state_priority"] = list(self.state_list.get(0, tk.END))

    def _load_dict(self, data: dict, path: str | None = None):
        self._loading = True
        self.data = copy.deepcopy(data)
        self.data.setdefault("coordinates", {})
        self.data.setdefault("states", {})
        self.data.setdefault("state_priority", list(self.data["states"]))
        self.data.setdefault("execution", {"mode": "foreground"})
        self.data.setdefault("brightness_triggers", [])
        self.registry.load_dict(self.data["coordinates"])
        self.name_var.set(self.data.get("name", "未命名 profile"))
        self.interval_var.set(str(self.data.get("loop_interval_seconds", 1.0)))
        mode = self.data.get("execution", {}).get("mode", "foreground")
        self.mode_var.set(MODE_NAMES.get(mode, MODE_NAMES["foreground"]))
        self.state_list.delete(0, tk.END)
        ordered = [s for s in self.data["state_priority"] if s in self.data["states"]]
        ordered.extend(s for s in self.data["states"] if s not in ordered)
        for name in ordered:
            self.state_list.insert(tk.END, name)
        self.current_path = path
        self.path_label.config(text=path or "(尚未儲存)")
        self.coord_count_label.config(text=f"Profile 內有 {len(self.data['coordinates'])} 個座標")
        self._fill_brightness_triggers()
        self._selected_state = None
        self._clear_state_form()
        if self.state_list.size():
            self.state_list.selection_set(0)
            self._show_state(self.state_list.get(0))
        self._update_mode_help()
        self._refresh_json()
        self._loading = False

    def _current_dict(self) -> dict:
        if not self._commit_state_form(silent=True):
            raise ValueError("目前狀態名稱不能空白或與其他狀態重複。")
        self._sync_basic_to_data()
        return copy.deepcopy(self.data)

    def _new_profile(self):
        self._load_dict(profile_io.new_empty_profile("新 profile"))

    def _open_profile(self):
        path = filedialog.askopenfilename(filetypes=[("JSON profile", "*.json")])
        if not path:
            return
        try:
            data = profile_io.load_profile(path)
        except Exception as exc:
            messagebox.showerror("讀取失敗", str(exc))
            return
        self._load_dict(data, path)
        self._notify_loaded(data, path)

    def _save_profile(self):
        self._write_to(self.current_path) if self.current_path else self._save_as_profile()

    def _save_as_profile(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON profile", "*.json")])
        if path:
            self._write_to(path)

    def _write_to(self, path):
        try:
            data = self._current_dict()
            profile_io.save_profile(path, data)
        except Exception as exc:
            messagebox.showerror("儲存失敗", str(exc))
            return
        self.current_path = path
        self.path_label.config(text=path)
        self._notify_loaded(data, path)
        messagebox.showinfo("已儲存", "Profile 已儲存。")

    def _notify_loaded(self, data, path):
        if self.on_profile_loaded:
            self.on_profile_loaded(data, path)
        if self.logger:
            self.logger.info(f"Profile 已更新: {path or '(尚未儲存)'}")

    def _validate(self):
        try:
            errors = profile_io.validate_profile(self._current_dict())
        except Exception as exc:
            messagebox.showerror("設定錯誤", str(exc))
            return
        messagebox.showerror("Profile 格式錯誤", "\n".join(errors)) if errors else messagebox.showinfo("驗證通過", "所有必要設定均正確。")

    def _import_coords(self):
        self.data["coordinates"] = {
            label: {"x": entry.x, "y": entry.y, "note": entry.note, "relative": entry.relative}
            for label, entry in self.registry.all_entries().items()
        }
        self.coord_count_label.config(text=f"Profile 內有 {len(self.data['coordinates'])} 個座標")
        messagebox.showinfo("完成", f"已匯入 {len(self.registry.all_entries())} 個座標。")

    def _sync_window_lock(self):
        if not self.window_lock_panel:
            return
        if self.window_lock_panel.is_locked():
            self.data["window_lock"] = self.window_lock_panel.get_lock_config()
            messagebox.showinfo("完成", "已把目前鎖定視窗寫入 Profile。")
        else:
            self.data.pop("window_lock", None)
            messagebox.showinfo("完成", "目前未鎖定視窗，已清除 Profile 的視窗設定。")

    def _on_state_selected(self, _event=None):
        if self._loading:
            return
        selected = self.state_list.curselection()
        if not selected:
            return
        if self._selected_state:
            self._commit_state_form(silent=True)
        self._show_state(self.state_list.get(selected[0]))

    def _show_state(self, name):
        self._selected_state = name
        state = self.data["states"].get(name, {})
        self.state_name_var.set(name)
        self.match_mode_var.set(state.get("match_mode", "any"))
        self._fill_anchors(state.get("anchors", []))
        self._fill_actions(state.get("on_enter_actions", []))

    def _clear_state_form(self):
        self.state_name_var.set("")
        self.match_mode_var.set("any")
        for tree in (getattr(self, "anchor_tree", None), getattr(self, "action_tree", None)):
            if tree:
                tree.delete(*tree.get_children())

    def _add_state(self):
        name = simpledialog.askstring("新增狀態", "狀態名稱：", parent=self)
        if not name:
            return
        name = name.strip()
        if name in self.data["states"]:
            messagebox.showerror("名稱重複", "這個狀態名稱已存在。")
            return
        self._commit_state_form(silent=True)
        self.data["states"][name] = {"match_mode": "any", "anchors": [], "on_enter_actions": []}
        self.state_list.insert(tk.END, name)
        self.state_list.selection_clear(0, tk.END)
        self.state_list.selection_set(tk.END)
        self.state_list.see(tk.END)
        self._show_state(name)

    def _delete_state(self):
        selected = self.state_list.curselection()
        if not selected:
            return
        index, name = selected[0], self.state_list.get(selected[0])
        if not messagebox.askyesno("刪除狀態", f"確定刪除「{name}」？"):
            return
        self.data["states"].pop(name, None)
        self.state_list.delete(index)
        self._selected_state = None
        self._clear_state_form()
        if self.state_list.size():
            index = min(index, self.state_list.size() - 1)
            self.state_list.selection_set(index)
            self._show_state(self.state_list.get(index))

    def _move_state(self, delta):
        selected = self.state_list.curselection()
        if not selected:
            return
        old, new = selected[0], selected[0] + delta
        if not 0 <= new < self.state_list.size():
            return
        name = self.state_list.get(old)
        self.state_list.delete(old)
        self.state_list.insert(new, name)
        self.state_list.selection_set(new)

    def _commit_state_form(self, silent=False):
        old = self._selected_state
        if not old or old not in self.data.get("states", {}):
            return True
        new = self.state_name_var.get().strip()
        if not new or (new != old and new in self.data["states"]):
            if not silent:
                messagebox.showerror("設定錯誤", "狀態名稱不能空白或重複。")
            return False
        state = self.data["states"].pop(old)
        state["match_mode"] = self.match_mode_var.get()
        self.data["states"][new] = state
        if new != old:
            names = self.state_list.get(0, tk.END)
            idx = names.index(old)
            self.state_list.delete(idx)
            self.state_list.insert(idx, new)
            self.state_list.selection_set(idx)
        self._selected_state = new
        if not silent:
            messagebox.showinfo("完成", "狀態設定已套用。")
        return True

    @staticmethod
    def _selected_item_index(tree):
        selected = tree.selection()
        return tree.index(selected[0]) if selected else None

    def _current_state_data(self):
        return self.data["states"].get(self._selected_state) if self._selected_state else None

    def _fill_anchors(self, anchors):
        self.anchor_tree.delete(*self.anchor_tree.get_children())
        for anchor in anchors:
            self.anchor_tree.insert("", tk.END, values=(anchor.get("template_path", ""), f"{float(anchor.get('confidence', .85)):.2f}", anchor.get("region") or "整個目標視窗"))

    def _add_anchor(self):
        state = self._current_state_data()
        if state is None:
            messagebox.showwarning("請先新增狀態", "請先新增或選擇一個狀態。")
            return
        result = AnchorDialog(self, title="新增辨識圖片").show()
        if result:
            state.setdefault("anchors", []).append(result)
            self._fill_anchors(state["anchors"])

    def _edit_anchor(self):
        state, index = self._current_state_data(), self._selected_item_index(self.anchor_tree)
        if state is not None and index is not None:
            result = AnchorDialog(self, state["anchors"][index], "編輯辨識圖片").show()
            if result:
                state["anchors"][index] = result
                self._fill_anchors(state["anchors"])

    def _delete_anchor(self):
        state, index = self._current_state_data(), self._selected_item_index(self.anchor_tree)
        if state is not None and index is not None:
            state["anchors"].pop(index)
            self._fill_anchors(state["anchors"])

    @staticmethod
    def _action_detail(action):
        kind = action.get("type")
        if kind in ("click", "double_click", "move"):
            button = ""
            if kind in ("click", "double_click"):
                button = "右鍵，" if action.get("button") == "right" else "左鍵，"
            return f"{button}座標：{action.get('coord_label', action.get('coord', '未設定'))}"
        if kind == "wait":
            return f"等待 {action.get('seconds', 0.3)} 秒"
        if kind == "type":
            return f"輸入：{action.get('text', '')}"
        if kind == "key":
            return f"按鍵：{action.get('key', '')}"
        return json.dumps(action, ensure_ascii=False)

    def _fill_actions(self, actions):
        self.action_tree.delete(*self.action_tree.get_children())
        for action in actions:
            self.action_tree.insert("", tk.END, values=(action.get("type", "?"), self._action_detail(action)))

    def _add_action(self):
        state = self._current_state_data()
        if state is None:
            messagebox.showwarning("請先新增狀態", "請先新增或選擇一個狀態。")
            return
        result = ActionDialog(self, list(self.data.get("coordinates", {}))).show()
        if result:
            state.setdefault("on_enter_actions", []).append(result)
            self._fill_actions(state["on_enter_actions"])

    def _edit_action(self):
        state, index = self._current_state_data(), self._selected_item_index(self.action_tree)
        if state is not None and index is not None:
            result = ActionDialog(self, list(self.data.get("coordinates", {})), state["on_enter_actions"][index]).show()
            if result:
                state["on_enter_actions"][index] = result
                self._fill_actions(state["on_enter_actions"])

    def _delete_action(self):
        state, index = self._current_state_data(), self._selected_item_index(self.action_tree)
        if state is not None and index is not None:
            state["on_enter_actions"].pop(index)
            self._fill_actions(state["on_enter_actions"])

    def _move_action(self, delta):
        state, index = self._current_state_data(), self._selected_item_index(self.action_tree)
        if state is None or index is None:
            return
        actions, new = state["on_enter_actions"], index + delta
        if not 0 <= new < len(actions):
            return
        actions[index], actions[new] = actions[new], actions[index]
        self._fill_actions(actions)
        self.action_tree.selection_set(self.action_tree.get_children()[new])

    @staticmethod
    def _trigger_action_summary(actions):
        parts = []
        for action in actions:
            if action.get("type") == "key":
                parts.append(str(action.get("key", "")).upper())
            elif action.get("type") == "click":
                button = "右鍵" if action.get("button") == "right" else "左鍵"
                parts.append(f"{button}@{action.get('coord_label', '?')}")
            else:
                parts.append(action.get("type", "?"))
        return " → ".join(parts)

    def _fill_brightness_triggers(self):
        if not hasattr(self, "brightness_tree"):
            return
        self.brightness_tree.delete(*self.brightness_tree.get_children())
        for trigger in self.data.get("brightness_triggers", []):
            enabled = "" if trigger.get("enabled", True) else "（停用）"
            force_after = float(trigger.get("force_after_seconds", 0))
            force_text = f"{force_after:g} 秒" if force_after > 0 else "停用"
            self.brightness_tree.insert(
                "", tk.END,
                values=(
                    f"{trigger.get('name', '未命名')}{enabled}",
                    trigger.get("watch_coord_label", ""),
                    trigger.get("threshold", 180),
                    force_text,
                    self._trigger_action_summary(trigger.get("actions", [])),
                ),
            )

    def _add_brightness_trigger(self):
        labels = list(self.data.get("coordinates", {}))
        if not labels:
            messagebox.showwarning("尚無座標", "請先在①錄製座標，再按『匯入已錄座標』。")
            return
        result = BrightnessTriggerDialog(self, labels).show()
        if result:
            self.data.setdefault("brightness_triggers", []).append(result)
            self._fill_brightness_triggers()

    def _edit_brightness_trigger(self):
        index = self._selected_item_index(self.brightness_tree)
        if index is None:
            return
        labels = list(self.data.get("coordinates", {}))
        current = self.data["brightness_triggers"][index]
        result = BrightnessTriggerDialog(self, labels, current).show()
        if result:
            self.data["brightness_triggers"][index] = result
            self._fill_brightness_triggers()

    def _delete_brightness_trigger(self):
        index = self._selected_item_index(self.brightness_tree)
        if index is None:
            return
        name = self.data["brightness_triggers"][index].get("name", "未命名")
        if not messagebox.askyesno("刪除觸發器", f"確定刪除「{name}」？"):
            return
        self.data["brightness_triggers"].pop(index)
        self._fill_brightness_triggers()

    def _on_editor_tab_changed(self, _event=None):
        if self.editor_notebook.index(self.editor_notebook.select()) == 2:
            self._refresh_json()

    def _refresh_json(self):
        try:
            data = self._current_dict() if not self._loading else self.data
        except Exception:
            data = self.data
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))

    def _apply_json(self):
        try:
            data = json.loads(self.text.get("1.0", tk.END))
            errors = profile_io.validate_profile(data)
            if errors:
                raise ValueError("\n".join(errors))
        except Exception as exc:
            messagebox.showerror("JSON 無法套用", str(exc))
            return
        self._load_dict(data, self.current_path)
        messagebox.showinfo("完成", "JSON 已套用到表單。")


class AnchorDialog:
    def __init__(self, parent, initial=None, title="辨識圖片"):
        self.parent, self.initial, self.title = parent, initial or {}, title
        self.result = None

    def show(self):
        win = tk.Toplevel(self.parent)
        win.title(self.title)
        win.transient(self.parent.winfo_toplevel())
        win.grab_set()
        path = tk.StringVar(value=self.initial.get("template_path", ""))
        confidence = tk.DoubleVar(value=float(self.initial.get("confidence", 0.85)))
        region = tk.StringVar(value=",".join(map(str, self.initial.get("region") or [])))
        ttk.Label(win, text="辨識圖片").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        ttk.Entry(win, textvariable=path, width=56).grid(row=0, column=1, padx=4)

        def browse():
            value = filedialog.askopenfilename(parent=win, filetypes=[("圖片", "*.png *.jpg *.jpeg *.bmp"), ("所有檔案", "*.*")])
            if value:
                path.set(os.path.relpath(value, os.getcwd()))

        ttk.Button(win, text="選擇…", command=browse).grid(row=0, column=2, padx=6)
        ttk.Label(win, text="準確度（0.1～1.0）").grid(row=1, column=0, padx=8, pady=6, sticky="w")
        ttk.Scale(win, from_=0.1, to=1.0, variable=confidence, orient="horizontal", length=260).grid(row=1, column=1, sticky="w")
        ttk.Entry(win, textvariable=confidence, width=7).grid(row=1, column=2)
        ttk.Label(win, text="搜尋範圍 x,y,w,h（留空＝整個目標視窗）").grid(row=2, column=0, padx=8, pady=6, sticky="w")
        ttk.Entry(win, textvariable=region, width=30).grid(row=2, column=1, sticky="w")

        def ok():
            try:
                conf = float(confidence.get())
                if not 0.1 <= conf <= 1.0 or not path.get().strip():
                    raise ValueError
                parts = [int(p.strip()) for p in region.get().split(",") if p.strip()]
                if parts and len(parts) != 4:
                    raise ValueError
            except ValueError:
                messagebox.showerror("設定錯誤", "請選擇圖片、輸入 0.1～1.0 的準確度；搜尋範圍必須留空或填四個整數。", parent=win)
                return
            self.result = {"template_path": path.get().strip(), "region": parts or None, "confidence": conf}
            win.destroy()

        row = ttk.Frame(win)
        row.grid(row=3, column=0, columnspan=3, pady=10)
        ttk.Button(row, text="確定", command=ok).pack(side="left", padx=4)
        ttk.Button(row, text="取消", command=win.destroy).pack(side="left", padx=4)
        win.wait_window()
        return self.result


class BrightnessTriggerDialog:
    def __init__(self, parent, coord_labels, initial=None):
        self.parent = parent
        self.coord_labels = coord_labels
        self.initial = initial or {}
        self.result = None

    def show(self):
        win = tk.Toplevel(self.parent)
        win.title("座標亮度觸發器")
        win.transient(self.parent.winfo_toplevel())
        win.grab_set()
        win.resizable(False, False)

        actions = self.initial.get("actions", [])
        initial_key = next((a.get("key", "").upper() for a in actions if a.get("type") == "key"), "不按鍵")
        click_action = next((a for a in actions if a.get("type") == "click"), {})
        initial_click = "右鍵" if click_action.get("button") == "right" else ("左鍵" if click_action else "不點擊")

        enabled = tk.BooleanVar(value=self.initial.get("enabled", True))
        name = tk.StringVar(value=self.initial.get("name", "新亮度觸發器"))
        watch = tk.StringVar(value=self.initial.get("watch_coord_label", self.coord_labels[0]))
        threshold = tk.StringVar(value=str(self.initial.get("threshold", 180)))
        radius = tk.StringVar(value=str(self.initial.get("radius", 3)))
        cooldown = tk.StringVar(value=str(self.initial.get("cooldown_seconds", 1.0)))
        force_after = tk.StringVar(value=str(self.initial.get("force_after_seconds", 5.0)))
        key = tk.StringVar(value=initial_key)
        click = tk.StringVar(value=initial_click)
        click_coord = tk.StringVar(value=click_action.get("coord_label", watch.get()))

        fields = ttk.Frame(win)
        fields.pack(fill="both", expand=True, padx=12, pady=10)
        ttk.Checkbutton(fields, text="啟用此觸發器", variable=enabled).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(fields, text="名稱").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(fields, textvariable=name, width=34).grid(row=1, column=1, sticky="ew")
        ttk.Label(fields, text="偵測發亮的座標").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Combobox(fields, textvariable=watch, values=self.coord_labels, state="readonly", width=31).grid(row=2, column=1, sticky="ew")
        ttk.Label(fields, text="亮度門檻（0～255）").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Spinbox(fields, from_=0, to=255, increment=1, textvariable=threshold, width=10).grid(row=3, column=1, sticky="w")
        ttk.Label(fields, text="取樣半徑（像素）").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Spinbox(fields, from_=0, to=30, increment=1, textvariable=radius, width=10).grid(row=4, column=1, sticky="w")
        ttk.Label(fields, text="發亮時最短重試間隔（秒）").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Spinbox(fields, from_=0.05, to=3600, increment=0.1, textvariable=cooldown, width=10).grid(row=5, column=1, sticky="w")
        ttk.Label(fields, text="沒發亮，超過幾秒仍強制執行").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Spinbox(fields, from_=0, to=86400, increment=0.5, textvariable=force_after, width=10).grid(row=6, column=1, sticky="w")
        ttk.Label(fields, text="鍵盤動作").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Combobox(fields, textvariable=key, values=["不按鍵"] + [f"F{i}" for i in range(1, 13)], state="readonly", width=12).grid(row=7, column=1, sticky="w")
        ttk.Label(fields, text="滑鼠動作").grid(row=8, column=0, sticky="w", pady=4)
        click_box = ttk.Combobox(fields, textvariable=click, values=("不點擊", "左鍵", "右鍵"), state="readonly", width=12)
        click_box.grid(row=8, column=1, sticky="w")
        ttk.Label(fields, text="滑鼠點擊座標").grid(row=9, column=0, sticky="w", pady=4)
        coord_box = ttk.Combobox(fields, textvariable=click_coord, values=self.coord_labels, state="readonly", width=31)
        coord_box.grid(row=9, column=1, sticky="ew")
        ttk.Label(
            fields,
            text="設為 0 秒可停用『沒發亮也強制執行』。亮度值會顯示在④執行監控的事件紀錄。",
            foreground="#666",
            wraplength=440,
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=(8, 2))

        def refresh_click(*_):
            coord_box.config(state="disabled" if click.get() == "不點擊" else "readonly")

        click_box.bind("<<ComboboxSelected>>", refresh_click)
        refresh_click()

        def ok():
            try:
                threshold_value = float(threshold.get())
                radius_value = int(radius.get())
                cooldown_value = float(cooldown.get())
                force_value = float(force_after.get())
                if not 0 <= threshold_value <= 255 or radius_value < 0 or cooldown_value <= 0 or force_value < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("設定錯誤", "請確認亮度、半徑與秒數都是有效數值。", parent=win)
                return
            if not name.get().strip() or not watch.get():
                messagebox.showerror("設定錯誤", "名稱與偵測座標不能空白。", parent=win)
                return
            result_actions = []
            if key.get() != "不按鍵":
                result_actions.append({"type": "key", "key": key.get().lower()})
            if click.get() != "不點擊":
                if not click_coord.get():
                    messagebox.showerror("設定錯誤", "請選擇滑鼠點擊座標。", parent=win)
                    return
                result_actions.append({
                    "type": "click",
                    "coord_label": click_coord.get(),
                    "button": "right" if click.get() == "右鍵" else "left",
                })
            if not result_actions:
                messagebox.showerror("設定錯誤", "至少選擇一個鍵盤或滑鼠動作。", parent=win)
                return
            self.result = {
                "name": name.get().strip(),
                "enabled": bool(enabled.get()),
                "watch_coord_label": watch.get(),
                "threshold": threshold_value,
                "radius": radius_value,
                "cooldown_seconds": cooldown_value,
                "force_after_seconds": force_value,
                "actions": result_actions,
            }
            win.destroy()

        def test_brightness():
            coord = self.parent.data.get("coordinates", {}).get(watch.get())
            if not coord:
                messagebox.showerror("無法測試", "找不到選取的偵測座標。", parent=win)
                return
            x, y = int(coord["x"]), int(coord["y"])
            rect = None
            panel = self.parent.window_lock_panel
            if coord.get("relative"):
                rect = panel.get_current_rect() if panel and panel.is_locked() else None
                if rect is None:
                    messagebox.showerror("無法測試", "這是相對座標，請先鎖定目標視窗。", parent=win)
                    return
                x, y = rect[0] + x, rect[1] + y
            try:
                if MODE_LABELS.get(self.parent.mode_var.get()) == "win32_background":
                    if not panel or not panel.is_locked():
                        raise RuntimeError("背景模式請先鎖定目標視窗。")
                    rect = panel.get_current_rect()
                    if rect is None:
                        raise RuntimeError("目前抓不到鎖定視窗的位置。")
                    hwnd = panel.wm.get_handle(panel.locked_title)
                    frame = win32_backend.capture_window(hwnd) if hwnd else None
                    if frame is None:
                        raise RuntimeError("無法取得背景畫面，可能是 DirectX 擷取限制。")
                    current = brightness_detector.sample_frame(frame, x, y, int(radius.get()), rect)
                else:
                    current = brightness_detector.sample_screen(x, y, int(radius.get()))
                if current is None:
                    raise RuntimeError("沒有取得亮度值。")
                target = float(threshold.get())
            except Exception as exc:
                messagebox.showerror("亮度測試失敗", str(exc), parent=win)
                return
            status = "會觸發（已發亮）" if current >= target else "不會觸發（尚未發亮）"
            messagebox.showinfo("目前亮度", f"目前亮度：{current:.1f}\n設定門檻：{target:g}\n結果：{status}", parent=win)

        buttons = ttk.Frame(win)
        buttons.pack(pady=(0, 10))
        ttk.Button(buttons, text="測試目前亮度", command=test_brightness).pack(side="left", padx=4)
        ttk.Button(buttons, text="確定", command=ok).pack(side="left", padx=4)
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="left", padx=4)
        win.wait_window()
        return self.result


class ActionDialog:
    TYPES = ("click", "double_click", "move", "wait", "type", "key")

    def __init__(self, parent, coord_labels, initial=None):
        self.parent, self.coord_labels, self.initial = parent, coord_labels, initial or {}
        self.result = None

    def show(self):
        win = tk.Toplevel(self.parent)
        win.title("動作設定")
        win.transient(self.parent.winfo_toplevel())
        win.grab_set()
        kind = tk.StringVar(value=self.initial.get("type", "click"))
        mouse_button = tk.StringVar(value="右鍵" if self.initial.get("button") == "right" else "左鍵")
        value = tk.StringVar()
        if kind.get() in ("click", "double_click", "move"):
            value.set(self.initial.get("coord_label", ""))
        elif kind.get() == "wait":
            value.set(str(self.initial.get("seconds", 0.5)))
        elif kind.get() == "type":
            value.set(self.initial.get("text", ""))
        else:
            value.set(self.initial.get("key", "enter"))
        ttk.Label(win, text="動作類型").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        type_box = ttk.Combobox(win, textvariable=kind, values=self.TYPES, state="readonly", width=22)
        type_box.grid(row=0, column=1, padx=6, sticky="w")
        prompt = ttk.Label(win, text="座標名稱")
        prompt.grid(row=1, column=0, padx=8, pady=8, sticky="w")
        value_box = ttk.Combobox(win, textvariable=value, values=self.coord_labels, width=35)
        value_box.grid(row=1, column=1, padx=6)
        button_label = ttk.Label(win, text="滑鼠按鍵")
        button_label.grid(row=2, column=0, padx=8, pady=4, sticky="w")
        button_box = ttk.Combobox(win, textvariable=mouse_button, values=("左鍵", "右鍵"), state="readonly", width=12)
        button_box.grid(row=2, column=1, padx=6, sticky="w")
        hint = ttk.Label(win, foreground="#666", wraplength=380)
        hint.grid(row=3, column=0, columnspan=2, padx=8, pady=4, sticky="w")

        def refresh(*_):
            if kind.get() in ("click", "double_click", "move"):
                prompt.config(text="座標名稱")
                value_box.config(values=self.coord_labels)
                hint.config(text="請先在①座標錄製後，按『匯入已錄座標』。")
                button_box.config(state="readonly" if kind.get() in ("click", "double_click") else "disabled")
            elif kind.get() == "wait":
                prompt.config(text="等待秒數")
                value_box.config(values=())
                hint.config(text="例如 0.5")
                button_box.config(state="disabled")
            elif kind.get() == "type":
                prompt.config(text="輸入文字")
                value_box.config(values=())
                hint.config(text="背景模式會以 WM_CHAR 傳送文字。")
                button_box.config(state="disabled")
            else:
                prompt.config(text="按鍵名稱")
                value_box.config(values=tuple([f"f{i}" for i in range(1, 13)] + ["enter", "escape", "space", "tab", "left", "right", "up", "down"]))
                hint.config(text="背景模式支援 F1～F12、常用按鍵及單一英數字元。")
                button_box.config(state="disabled")

        type_box.bind("<<ComboboxSelected>>", refresh)
        refresh()

        def ok():
            raw = value.get()
            if kind.get() in ("click", "double_click", "move"):
                if not raw:
                    messagebox.showerror("設定錯誤", "請選擇座標名稱。", parent=win)
                    return
                self.result = {"type": kind.get(), "coord_label": raw}
                if kind.get() in ("click", "double_click"):
                    self.result["button"] = "right" if mouse_button.get() == "右鍵" else "left"
            elif kind.get() == "wait":
                try:
                    seconds = float(raw)
                    if seconds < 0:
                        raise ValueError
                except ValueError:
                    messagebox.showerror("設定錯誤", "等待秒數必須是 0 或正數。", parent=win)
                    return
                self.result = {"type": "wait", "seconds": seconds}
            elif kind.get() == "type":
                self.result = {"type": "type", "text": raw}
            else:
                self.result = {"type": "key", "key": raw}
            win.destroy()

        buttons = ttk.Frame(win)
        buttons.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(buttons, text="確定", command=ok).pack(side="left", padx=4)
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="left", padx=4)
        win.wait_window()
        return self.result
