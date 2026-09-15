"""
Event Classifier — 事件分類/降噪上報層

對應架構文件第 7 節：不是每個狀態變化都值得打斷使用者，這裡用可設定的門檻過濾。
數值型事件（例如某個累積分數）超過歷史最大值的 multiplier 倍才算「破紀錄」；
其餘固定分類的關鍵事件（錯誤、斷線）一律直接通知。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Optional


@dataclass
class EventRule:
    event_type: str
    always_notify: bool = False
    record_multiplier: Optional[float] = None  # 例如 1.0 = 只要超過歷史最大值就算


class EventClassifier:
    def __init__(self, logger=None):
        self.logger = logger
        self._rules: Dict[str, EventRule] = {}
        self._history_max: Dict[str, float] = {}
        self._notify_callbacks: List[Callable[[str, dict], None]] = []

    def add_rule(self, rule: EventRule):
        self._rules[rule.event_type] = rule

    def on_notify(self, callback: Callable[[str, dict], None]):
        self._notify_callbacks.append(callback)

    def feed(self, event_type: str, payload: dict):
        """
        payload 至少包含 {"value": number} 或 {"message": str}。
        回傳 True 代表這次事件觸發了通知。
        """
        rule = self._rules.get(event_type)
        should_notify = False

        if rule is None:
            # 沒設規則的事件型別，預設不吵（保守起見寧可漏報，也不要每個小事都通知）
            should_notify = False
        elif rule.always_notify:
            should_notify = True
        elif rule.record_multiplier is not None and "value" in payload:
            value = payload["value"]
            prev_max = self._history_max.get(event_type, float("-inf"))
            if value > prev_max * rule.record_multiplier if prev_max > 0 else value > 0:
                should_notify = True
            self._history_max[event_type] = max(prev_max, value)

        if should_notify:
            if self.logger:
                self.logger.event(f"{event_type}: {payload}")
            for cb in self._notify_callbacks:
                try:
                    cb(event_type, payload)
                except Exception:
                    pass
        return should_notify
