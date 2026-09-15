"""
Action Executor — 動作執行層

對應架構文件第 4、5 節：
- click_with_confirm 實作非同步 UI 的 retry pattern（區分「資源不足/時序/狀態已變」三種失敗，
  這裡先提供通用骨架，資源不足的判斷需要呼叫端傳入 confirm_fn 自行定義）
- run_sequence 做 batch 化執行，每個動作間可插入 wait
- 內建 emergency stop：呼叫端可以隨時呼叫 executor.stop() 或透過 stop_event 從 GUI 端中斷，
  下一個動作執行前會檢查並中止整個序列
- pyautogui.FAILSAFE 預設保持開啟：滑鼠移到螢幕角落可強制中斷，這是這類工具的標準安全閥，不要關掉
"""
from __future__ import annotations
import time
import threading
from typing import Callable, List, Dict, Optional, Any

try:
    import pyautogui
    pyautogui.FAILSAFE = True  # 安全閥：滑鼠甩到螢幕角落 = 立刻拋例外中止
    PYAUTOGUI_AVAILABLE = True
except Exception:
    pyautogui = None
    PYAUTOGUI_AVAILABLE = False


class ActionAbort(Exception):
    """使用者觸發緊急停止，或 FAILSAFE 觸發時拋出。"""


class ActionExecutor:
    def __init__(self, logger=None):
        self.logger = logger
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()  # set = 暫停中

    # ---- 生命週期控制（給 GUI 的 Start/Pause/Stop 按鈕呼叫）----
    def stop(self):
        self._stop_event.set()

    def reset_stop(self):
        self._stop_event.clear()

    def pause(self):
        self._pause_event.set()

    def resume(self):
        self._pause_event.clear()

    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def _check_abort(self):
        if self._stop_event.is_set():
            raise ActionAbort("使用者觸發停止")
        while self._pause_event.is_set():
            time.sleep(0.1)
            if self._stop_event.is_set():
                raise ActionAbort("使用者觸發停止")

    # ---- 基本動作 primitives ----
    def _require_pyautogui(self):
        if not PYAUTOGUI_AVAILABLE:
            raise RuntimeError("pyautogui 不可用（沒有偵測到可用的顯示器）。此環境僅能做架構/邏輯測試。")

    def click(self, x: int, y: int, button: str = "left"):
        self._check_abort()
        self._require_pyautogui()
        pyautogui.click(x=x, y=y, button=button)
        if self.logger:
            self.logger.debug(f"click ({x},{y})")

    def double_click(self, x: int, y: int):
        self._check_abort()
        self._require_pyautogui()
        pyautogui.doubleClick(x=x, y=y)
        if self.logger:
            self.logger.debug(f"double_click ({x},{y})")

    def move(self, x: int, y: int, duration: float = 0.0):
        self._check_abort()
        self._require_pyautogui()
        pyautogui.moveTo(x, y, duration=duration)

    def type_text(self, text: str, interval: float = 0.02):
        self._check_abort()
        self._require_pyautogui()
        pyautogui.typewrite(text, interval=interval)

    def key(self, key_name: str):
        self._check_abort()
        self._require_pyautogui()
        pyautogui.press(key_name)

    def wait(self, seconds: float):
        # wait 期間也要能被 abort 打斷，不要整段死睡
        end = time.time() + seconds
        while time.time() < end:
            self._check_abort()
            time.sleep(min(0.05, max(0.0, end - time.time())))

    # ---- 高階：batch 序列 ----
    def run_sequence(self, actions: List[Dict[str, Any]]):
        """
        actions 範例:
        [
          {"type": "click", "coord": [100, 200]},
          {"type": "wait", "seconds": 0.4},
          {"type": "double_click", "coord": [100, 200]},
        ]
        """
        for act in actions:
            self._check_abort()
            t = act.get("type")
            if t == "click":
                x, y = act["coord"]
                self.click(x, y, act.get("button", "left"))
            elif t == "double_click":
                x, y = act["coord"]
                self.double_click(x, y)
            elif t == "move":
                x, y = act["coord"]
                self.move(x, y, act.get("duration", 0.0))
            elif t == "wait":
                self.wait(act.get("seconds", 0.3))
            elif t == "type":
                self.type_text(act.get("text", ""))
            elif t == "key":
                self.key(act.get("key", ""))
            else:
                if self.logger:
                    self.logger.warn(f"未知動作類型: {t}，已略過")

    # ---- 高階：click-with-confirm retry pattern（架構文件第 4 節）----
    def click_with_confirm(
        self,
        coord: tuple,
        confirm_fn: Callable[[], bool],
        max_retries: int = 2,
        wait_between: float = 0.4,
        double: bool = True,
    ) -> bool:
        """
        confirm_fn: 呼叫端傳入的檢查函式，回傳 True 代表這次點擊已確認生效。
        通常會是「重新偵測目前 state / 讀取畫面上某個區域」之類的邏輯，
        由使用者依自己的目標畫面實作，這裡不假設任何特定 UI。
        """
        x, y = coord
        for attempt in range(max_retries):
            self._check_abort()
            if double:
                self.double_click(x, y)
            else:
                self.click(x, y)
            self.wait(wait_between)
            self.click(x, y)  # 二次點擊確認（例如彈窗的確認鈕通常跟原座標重疊）

            if confirm_fn():
                if self.logger:
                    self.logger.debug(f"click_with_confirm 成功 @ ({x},{y}), attempt={attempt+1}")
                return True
            if self.logger:
                self.logger.debug(f"click_with_confirm 第 {attempt+1} 次未確認，重試中...")
        if self.logger:
            self.logger.warn(f"click_with_confirm 在 ({x},{y}) 重試 {max_retries} 次後仍未確認")
        return False
