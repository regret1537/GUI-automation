"""
Window Manager — 視窗鎖定層

目的：讓座標與偵測「跟著視窗走」，而不是寫死在螢幕絕對座標上。
好處：
  1. 使用者不小心移動/切換視窗時，動作還是點在正確的相對位置上
  2. State Detector 的搜尋範圍可以限制在該視窗內，減少誤判、加快 template matching
  3. 執行前可以先把目標視窗帶到最上層 (activate)，避免點到別的視窗

實作策略：用「標題關鍵字重新搜尋」而不是保留一個固定的 window handle 物件。
背景執行緒長時間跑的情況下，直接持有 handle 物件容易遇到失效/跨平台不一致的問題；
每次都用 title substring 重新查詢一次雖然多一點開銷，但穩定得多。

⚠ 如果你的視窗標題不夠獨特（例如很多分頁都叫同名），會抓到第一個符合的視窗，
   建議 list_windows() 先確認一下，取一段夠獨特的關鍵字。

依賴 pywinctl（跨平台：Windows / macOS / Linux X11，不支援 Wayland）。
沒裝或在無視窗管理員環境會 import 失敗，同樣走 AVAILABLE flag 的降級模式，
不會讓整個框架掛掉，只是這個功能不可用。
"""
from __future__ import annotations
from typing import List, Optional, Tuple

try:
    import pywinctl
    WINDOW_MGMT_AVAILABLE = True
except Exception:
    pywinctl = None
    WINDOW_MGMT_AVAILABLE = False


class WindowManager:
    def __init__(self, logger=None):
        self.logger = logger
        if not WINDOW_MGMT_AVAILABLE and logger:
            logger.warn(
                "pywinctl 無法載入，視窗鎖定功能不可用（僅座標/狀態偵測仍可用全螢幕模式）。"
                "請確認已安裝 pywinctl 且目前環境有視窗管理員（Linux 需要 X11，不支援 Wayland）。"
            )

    def list_windows(self) -> List[str]:
        """回傳目前所有可見視窗的標題列表（可能包含空字串或重複，呼叫端自行過濾）。"""
        if not WINDOW_MGMT_AVAILABLE:
            return []
        try:
            wins = pywinctl.getAllWindows()
            titles = []
            for w in wins:
                try:
                    t = w.title
                    if t:
                        titles.append(t)
                except Exception:
                    continue
            return titles
        except Exception as e:
            if self.logger:
                self.logger.debug(f"list_windows 失敗: {e}")
            return []

    def _find(self, title_substring: str):
        if not WINDOW_MGMT_AVAILABLE or not title_substring:
            return None
        # 直接比對 getAllWindows() 的實際標題最穩定；遊戲標題常包含 []、
        # 括號或破折號，部分 pywinctl 版本的 getWindowsWithTitle 會把它們
        # 當成搜尋語法，導致「列表看得到、鎖定卻找不到」。
        try:
            needle = title_substring.strip().casefold()
            exact = []
            contains = []
            for win in pywinctl.getAllWindows():
                title = (getattr(win, "title", "") or "").strip()
                folded = title.casefold()
                if folded == needle:
                    exact.append(win)
                elif needle in folded:
                    contains.append(win)
            candidates = exact or contains
        except Exception as e:
            if self.logger:
                self.logger.debug(f"_find 失敗: {e}")
            candidates = []
        return candidates[0] if candidates else None

    def get_rect(self, title_substring: str) -> Optional[Tuple[int, int, int, int]]:
        """回傳 (x, y, width, height)，找不到視窗回傳 None。"""
        win = self._find(title_substring)
        if win is None:
            return None
        try:
            return (int(win.left), int(win.top), int(win.width), int(win.height))
        except Exception as e:
            if self.logger:
                self.logger.debug(f"get_rect 讀取屬性失敗: {e}")
            return None

    def get_handle(self, title_substring: str) -> Optional[int]:
        """回傳原生視窗 handle（Windows 的 HWND）；其他平台或找不到時回傳 None。"""
        win = self._find(title_substring)
        if win is None:
            return None
        for attr in ("getHandle", "_hWnd", "hWnd"):
            try:
                value = getattr(win, attr)
                value = value() if callable(value) else value
                if value:
                    return int(value)
            except Exception:
                continue
        return None

    def is_minimized(self, title_substring: str) -> bool:
        win = self._find(title_substring)
        if win is None:
            return False
        try:
            return bool(win.isMinimized)
        except Exception:
            return False

    def is_alive(self, title_substring: str) -> bool:
        return self.get_rect(title_substring) is not None

    def activate(self, title_substring: str) -> bool:
        """把視窗帶到最上層/取得焦點。失敗時回傳 False，不拋例外（不同平台行為差異大）。"""
        win = self._find(title_substring)
        if win is None:
            return False
        try:
            win.activate()
            return True
        except Exception as e:
            if self.logger:
                self.logger.debug(f"activate 失敗: {e}")
            return False
