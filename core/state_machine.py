"""
State Machine Orchestrator — 主迴圈

對應架構文件第 1 節的 Orchestrator 層：串接 CoordinateRegistry / StateDetector /
ActionExecutor / EventClassifier，跑「感知 → 決策 → 動作 → 驗證」迴圈。

設計為在背景 thread 執行，GUI 端只需要呼叫 start()/pause()/resume()/stop()，
並透過 logger 的 gui_callback 拿到即時 log。
"""
from __future__ import annotations
import threading
import time
from typing import Dict, Optional, Any

from core.coordinate_registry import CoordinateRegistry
from core.state_detector import StateDetector, StateDef, Anchor
from core.action_executor import ActionExecutor, ActionAbort
from core.event_classifier import EventClassifier
from core.window_manager import WindowManager


class StateMachine:
    def __init__(self, profile: Dict[str, Any], logger=None, window_manager: Optional[WindowManager] = None):
        self.profile = profile
        self.logger = logger

        self.coords = CoordinateRegistry()
        for label, c in profile.get("coordinates", {}).items():
            self.coords.set(label, c["x"], c["y"], c.get("note", ""), c.get("relative", False))

        self.detector = StateDetector(logger=logger)
        self.executor = ActionExecutor(logger=logger)
        self.classifier = EventClassifier(logger=logger)

        # ---- 視窗鎖定設定（可選）----
        wl = profile.get("window_lock") or {}
        self.window_title_substring: Optional[str] = wl.get("title_substring") or None
        self.activate_before_action: bool = bool(wl.get("activate_before_action", False))
        self.window_manager = window_manager or (WindowManager(logger=logger) if self.window_title_substring else None)
        self.current_window_rect: Optional[tuple] = None  # 每個 loop iteration 更新

        self._states: Dict[str, StateDef] = {}
        for name, s in profile.get("states", {}).items():
            anchors = [
                Anchor(
                    template_path=a["template_path"],
                    region=tuple(a["region"]) if a.get("region") else None,
                    confidence=a.get("confidence", 0.85),
                )
                for a in s.get("anchors", [])
            ]
            self._states[name] = StateDef(
                name=name, anchors=anchors, match_mode=s.get("match_mode", "any")
            )
        self._priority = profile.get("state_priority") or list(self._states.keys())
        self._loop_interval = profile.get("loop_interval_seconds", 1.0)

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self.on_state_change = None  # GUI 可掛上 callback(state_name)
        self.action_count = 0
        self.last_state = None

    # ---- 座標 -> 實際 action 展開（把 profile 裡的 coord_label 換成 x,y）----
    def _resolve_actions(self, actions: list) -> list:
        resolved = []
        for act in actions:
            act = dict(act)
            if "coord_label" in act:
                xy = self.coords.resolve(act["coord_label"], self.current_window_rect)
                if xy is None:
                    if self.logger:
                        label = act["coord_label"]
                        if self.window_title_substring and self.current_window_rect is None:
                            self.logger.error(f"座標 label '{label}' 需要視窗鎖定，但目前抓不到視窗位置，此動作略過")
                        else:
                            self.logger.error(f"座標 label '{label}' 不存在，此動作略過")
                    continue
                act["coord"] = list(xy)
            resolved.append(act)
        return resolved

    # ---- 主迴圈 ----
    def _run_loop(self):
        if self.logger:
            self.logger.info("State machine 開始執行")
        consecutive_unknown = 0
        consecutive_window_missing = 0
        while self._running:
            try:
                self.executor._check_abort()
            except ActionAbort:
                break

            # ---- 視窗鎖定：每個 iteration 重新抓一次視窗位置，別假設它沒動 ----
            if self.window_title_substring:
                rect = self.window_manager.get_rect(self.window_title_substring)
                if rect is None:
                    consecutive_window_missing += 1
                    if self.logger:
                        self.logger.warn(
                            f"找不到標題包含「{self.window_title_substring}」的視窗 "
                            f"(連續 {consecutive_window_missing} 次)"
                        )
                    self.current_window_rect = None
                    if consecutive_window_missing >= 3:
                        if self.logger:
                            self.logger.error("目標視窗持續消失（可能已關閉），暫停執行")
                        self.pause()
                        consecutive_window_missing = 0
                    time.sleep(self._loop_interval)
                    continue
                consecutive_window_missing = 0
                self.current_window_rect = rect
                if self.activate_before_action:
                    self.window_manager.activate(self.window_title_substring)

            state_name = self.detector.detect_state(self._states, self._priority, self.current_window_rect)

            if state_name is None:
                consecutive_unknown += 1
                if self.logger:
                    self.logger.warn(f"目前畫面無法辨識任何已知狀態 (連續 {consecutive_unknown} 次)")
                if consecutive_unknown >= 5:
                    if self.logger:
                        self.logger.error("連續多次無法辨識狀態，暫停執行，請人工檢查畫面")
                    self.pause()
                    consecutive_unknown = 0
                time.sleep(self._loop_interval)
                continue

            consecutive_unknown = 0
            if state_name != self.last_state:
                if self.logger:
                    self.logger.info(f"狀態切換: {self.last_state} -> {state_name}")
                self.last_state = state_name
                if self.on_state_change:
                    try:
                        self.on_state_change(state_name)
                    except Exception:
                        pass

            state_cfg = self.profile["states"].get(state_name, {})
            actions = self._resolve_actions(state_cfg.get("on_enter_actions", []))
            if actions:
                try:
                    self.executor.run_sequence(actions)
                    self.action_count += len(actions)
                except ActionAbort:
                    break
                except RuntimeError as e:
                    if self.logger:
                        self.logger.error(str(e))
                    self.pause()

            time.sleep(self._loop_interval)

        self._running = False
        if self.logger:
            self.logger.info("State machine 已停止")

    # ---- 生命週期控制 ----
    def start(self):
        if self._running:
            return
        self._running = True
        self.executor.reset_stop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def pause(self):
        self.executor.pause()

    def resume(self):
        self.executor.resume()

    def is_paused(self) -> bool:
        return self.executor.is_paused()

    def stop(self):
        self._running = False
        self.executor.stop()
