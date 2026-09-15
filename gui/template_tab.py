"""
Tab 2: 狀態錨點 (anchor template) 截圖工具

用途：State Detector 用 template matching 判斷畫面狀態，需要先把「這個狀態獨有、
穩定不變的一小塊區域」（例如某個按鈕、標題文字）截圖存成 PNG，之後偵測時拿來比對。

操作：按「開始框選」後，主視窗會暫時隱藏，全螢幕出現一個半透明遮罩，
拖曳滑鼠框選要截的區域，放開滑鼠後自動擷取並詢問檔名存檔。
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import os
import glob

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    pyautogui = None
    PYAUTOGUI_AVAILABLE = False


class TemplateTab(ttk.Frame):
    def __init__(self, parent, root_window, templates_dir, logger):
        super().__init__(parent)
        self.root_window = root_window
        self.templates_dir = templates_dir
        self.logger = logger
        os.makedirs(templates_dir, exist_ok=True)
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=8)
        ttk.Button(top, text="開始框選截圖", command=self._start_capture).pack(side="left")
        if not PYAUTOGUI_AVAILABLE:
            ttk.Label(
                self, text="⚠ 此環境沒有可用的顯示器，無法框選截圖。",
                foreground="orange",
            ).pack(fill="x", padx=8)

        self.listbox = tk.Listbox(self, height=16)
        self.listbox.pack(fill="both", expand=True, padx=8, pady=4)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=8, pady=4)
        ttk.Button(btn_row, text="重新整理", command=self.refresh_list).pack(side="left")
        ttk.Button(btn_row, text="刪除選取", command=self._delete_selected).pack(side="left", padx=8)

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for path in sorted(glob.glob(os.path.join(self.templates_dir, "*.png"))):
            self.listbox.insert(tk.END, os.path.basename(path))

    def _delete_selected(self):
        sel = self.listbox.curselection()
        for idx in sel:
            name = self.listbox.get(idx)
            path = os.path.join(self.templates_dir, name)
            if os.path.exists(path):
                os.remove(path)
        self.refresh_list()

    def _start_capture(self):
        if not PYAUTOGUI_AVAILABLE:
            messagebox.showerror("無法截圖", "此環境沒有可用的顯示器。")
            return
        self.root_window.withdraw()
        overlay = tk.Toplevel(self.root_window)
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-alpha", 0.3)
        overlay.configure(bg="black")
        overlay.attributes("-topmost", True)

        canvas = tk.Canvas(overlay, cursor="cross", bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        state = {"start": None, "rect": None}

        def on_press(event):
            state["start"] = (event.x_root, event.y_root)
            state["rect"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="red", width=2)

        def on_drag(event):
            if state["rect"] is not None:
                sx, sy = state["start"]
                # canvas 座標是 overlay 內的相對座標，跟 event.x/y 一致（overlay 是全螢幕且無邊框）
                canvas.coords(state["rect"], sx, sy, event.x_root, event.y_root)

        def on_release(event):
            sx, sy = state["start"]
            ex, ey = event.x_root, event.y_root
            x0, x1 = sorted((sx, ex))
            y0, y1 = sorted((sy, ey))
            w, h = x1 - x0, y1 - y0
            overlay.destroy()
            self.root_window.deiconify()
            if w < 4 or h < 4:
                messagebox.showwarning("框選太小", "框選區域太小，請重新框選一次。")
                return
            name = simpledialog.askstring("儲存檔名", "這個錨點的檔名 (不含副檔名):", parent=self.root_window)
            if not name:
                return
            try:
                img = pyautogui.screenshot(region=(x0, y0, w, h))
            except Exception as e:
                messagebox.showerror("截圖失敗", str(e))
                return
            path = os.path.join(self.templates_dir, f"{name}.png")
            img.save(path)
            if self.logger:
                self.logger.info(f"已儲存錨點截圖: {path} region=({x0},{y0},{w},{h})")
            self.refresh_list()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", lambda e: (overlay.destroy(), self.root_window.deiconify()))
