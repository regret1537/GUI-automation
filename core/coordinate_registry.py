"""
Coordinate Registry — 座標快取層

設計重點（對應架構文件第 3 節）：
- 座標不是永久有效的，用「連續失敗次數」(miss_streak) 而非單次失敗來判斷是否失效，
  避免把單純的時序問題誤判成座標錯誤。
- 提供 save/load，讓錄好的座標可以存成 profile 的一部分重複使用。
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional, Tuple


@dataclass
class CoordEntry:
    x: int
    y: int
    note: str = ""
    miss_streak: int = 0
    hit_count: int = 0
    relative: bool = False  # True = x,y 是相對於「已鎖定視窗」左上角的偏移量，不是螢幕絕對座標


class CoordinateRegistry:
    def __init__(self, miss_threshold: int = 3):
        self.miss_threshold = miss_threshold
        self._store: Dict[str, CoordEntry] = {}

    # ---- 基本存取 ----
    def set(self, label: str, x: int, y: int, note: str = "", relative: bool = False):
        self._store[label] = CoordEntry(x=x, y=y, note=note, relative=relative)

    def get(self, label: str) -> Optional[Tuple[int, int]]:
        """回傳原始儲存值。注意：如果該項是 relative=True，這裡回傳的是「偏移量」，
        不是螢幕絕對座標，要拿來點擊前請用 resolve()。"""
        entry = self._store.get(label)
        if entry is None:
            return None
        return (entry.x, entry.y)

    def resolve(self, label: str, window_rect: Optional[Tuple[int, int, int, int]] = None) -> Optional[Tuple[int, int]]:
        """
        換算成螢幕絕對座標：
          - relative=False 的項目：直接回傳儲存的 (x, y)
          - relative=True 的項目：回傳 (window_rect.left + x, window_rect.top + y)；
            如果沒有目前有效的 window_rect（視窗沒鎖定或已消失），回傳 None，
            呼叫端應視為「動作無法執行」而不是硬點到螢幕上錯誤的位置。
        """
        entry = self._store.get(label)
        if entry is None:
            return None
        if not entry.relative:
            return (entry.x, entry.y)
        if window_rect is None:
            return None
        wx, wy, _, _ = window_rect
        return (wx + entry.x, wy + entry.y)

    def remove(self, label: str):
        self._store.pop(label, None)

    def labels(self):
        return list(self._store.keys())

    def all_entries(self) -> Dict[str, CoordEntry]:
        return dict(self._store)

    # ---- 失效機制 ----
    def report_hit(self, label: str):
        entry = self._store.get(label)
        if entry:
            entry.miss_streak = 0
            entry.hit_count += 1

    def report_miss(self, label: str) -> bool:
        """回傳 True 代表已達失效門檻，呼叫端應該觸發重新掃描/標記座標。"""
        entry = self._store.get(label)
        if entry is None:
            return True
        entry.miss_streak += 1
        return entry.miss_streak >= self.miss_threshold

    def is_stale(self, label: str) -> bool:
        entry = self._store.get(label)
        if entry is None:
            return True
        return entry.miss_streak >= self.miss_threshold

    # ---- 持久化 ----
    def to_dict(self) -> dict:
        return {label: asdict(entry) for label, entry in self._store.items()}

    def load_dict(self, data: dict):
        self._store = {}
        for label, e in data.items():
            self._store[label] = CoordEntry(
                x=e["x"], y=e["y"], note=e.get("note", ""),
                relative=e.get("relative", False),
            )

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, path: str):
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            self.load_dict(json.load(f))
