"""Tab 3：按鈕／表單式 Profile 編輯器。"""
from __future__ import annotations

import copy
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from core import profile_io
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
        visual, advanced = ttk.Frame(self.editor_notebook), ttk.Frame(self.editor_notebook)
        self.editor_notebook.add(visual, text="表單設定（建議）")
        self.editor_notebook.add(advanced, text="進階 JSON")
        self.editor_notebook.bind("<<NotebookTabChanged>>", self._on_editor_tab_changed)
        self._build_visual_editor(visual)
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
        for label, entry in self.registry.all_entries().items():
            self.data["coordinates"][label] = {"x": entry.x, "y": entry.y, "note": entry.note, "relative": entry.relative}
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
            return f"座標：{action.get('coord_label', action.get('coord', '未設定'))}"
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

    def _on_editor_tab_changed(self, _event=None):
        if self.editor_notebook.index(self.editor_notebook.select()) == 1:
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
        hint = ttk.Label(win, foreground="#666", wraplength=380)
        hint.grid(row=2, column=0, columnspan=2, padx=8, sticky="w")

        def refresh(*_):
            if kind.get() in ("click", "double_click", "move"):
                prompt.config(text="座標名稱")
                value_box.config(values=self.coord_labels)
                hint.config(text="請先在①座標錄製後，按『匯入已錄座標』。")
            elif kind.get() == "wait":
                prompt.config(text="等待秒數")
                value_box.config(values=())
                hint.config(text="例如 0.5")
            elif kind.get() == "type":
                prompt.config(text="輸入文字")
                value_box.config(values=())
                hint.config(text="背景模式會以 WM_CHAR 傳送文字。")
            else:
                prompt.config(text="按鍵名稱")
                value_box.config(values=("enter", "escape", "space", "tab", "left", "right", "up", "down"))
                hint.config(text="背景模式支援常用按鍵及單一英數字元。")

        type_box.bind("<<ComboboxSelected>>", refresh)
        refresh()

        def ok():
            raw = value.get()
            if kind.get() in ("click", "double_click", "move"):
                if not raw:
                    messagebox.showerror("設定錯誤", "請選擇座標名稱。", parent=win)
                    return
                self.result = {"type": kind.get(), "coord_label": raw}
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
        buttons.grid(row=3, column=0, columnspan=2, pady=10)
        ttk.Button(buttons, text="確定", command=ok).pack(side="left", padx=4)
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="left", padx=4)
        win.wait_window()
        return self.result
