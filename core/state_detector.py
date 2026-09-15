"""
State Detector — 狀態偵測層

對應架構文件第 2 節：先分類「宏觀狀態」，用穩定的視覺錨點 (anchor template) 判斷，
而不是用會變動的內容（分數數字、角色位置）。

技術實作：用 pyautogui.locateOnScreen（底層是 OpenCV template matching）
在指定 region 內尋找 anchor 圖片，達到 confidence 門檻即視為命中。

每個 state 可以設定多個 anchors，match_mode="all" 代表全部命中才算此狀態，
"any" 代表任一命中即可（例如同一個畫面在不同解析度下可能有兩種可能的錨點圖）。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:  # pragma: no cover - 在無顯示器環境（例如本沙盒）會 import 失敗
    pyautogui = None
    PYAUTOGUI_AVAILABLE = False


@dataclass
class Anchor:
    template_path: str
    region: Optional[tuple] = None  # (x, y, w, h)；None = 全螢幕搜尋（較慢）
    confidence: float = 0.85


@dataclass
class StateDef:
    name: str
    anchors: List[Anchor] = field(default_factory=list)
    match_mode: str = "any"  # "any" | "all"


class StateDetector:
    def __init__(self, logger=None):
        self.logger = logger
        if not PYAUTOGUI_AVAILABLE:
            if logger:
                logger.warn("pyautogui 無法載入（通常是因為沒有可用的顯示器）。"
                             "StateDetector 會在呼叫時直接回傳 None，僅供架構展示/離線測試。")

    def _locate(self, anchor: Anchor, window_rect: Optional[tuple] = None) -> bool:
        if not PYAUTOGUI_AVAILABLE:
            return False
        # anchor 自己沒指定 region 時，優先用目前鎖定視窗的範圍當搜尋區域，
        # 而不是整個螢幕 —— 更準、更快，也不會被其他視窗上長得像的元素誤判命中。
        region = anchor.region if anchor.region is not None else window_rect
        try:
            box = pyautogui.locateOnScreen(
                anchor.template_path,
                region=region,
                confidence=anchor.confidence,
            )
            return box is not None
        except Exception as e:
            if self.logger:
                self.logger.debug(f"locateOnScreen 失敗 ({anchor.template_path}): {e}")
            return False

    def check_state(self, state: StateDef, window_rect: Optional[tuple] = None) -> bool:
        if not state.anchors:
            return False
        results = [self._locate(a, window_rect) for a in state.anchors]
        if state.match_mode == "all":
            return all(results)
        return any(results)

    def detect_state(
        self,
        states: Dict[str, StateDef],
        priority: Optional[List[str]] = None,
        window_rect: Optional[tuple] = None,
    ) -> Optional[str]:
        """
        依 priority 順序（沒指定就用 dict 原順序）逐一檢查，回傳第一個命中的 state 名稱。
        找不到任何命中時回傳 None（呼叫端應進入 UNKNOWN 處理流程，而不是盲目繼續）。
        window_rect: 目前鎖定視窗的 (x,y,w,h)，用來當作沒指定 region 的 anchor 的預設搜尋範圍。
        """
        order = priority or list(states.keys())
        for name in order:
            state = states.get(name)
            if state and self.check_state(state, window_rect):
                return name
        return None
