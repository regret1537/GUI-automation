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
from core import brightness_detector
from core import win32_backend


class StateMachine:
    def __init__(self, profile: Dict[str, Any], logger=None, window_manager: Optional[WindowManager] = None):
        self.profile = profile
        self.logger = logger

        self.coords = CoordinateRegistry()
        for label, c in profile.get("coordinates", {}).items():
            self.coords.set(label, c["x"], c["y"], c.get("note", ""), c.get("relative", False))

        self.classifier = EventClassifier(logger=logger)

        # ---- 視窗鎖定設定（可選）----
        wl = profile.get("window_lock") or {}
        self.window_title_substring: Optional[str] = wl.get("title_substring") or None
        self.activate_before_action: bool = bool(wl.get("activate_before_action", False))
        self.window_manager = window_manager or (WindowManager(logger=logger) if self.window_title_substring else None)
        self.current_window_rect: Optional[tuple] = None  # 每個 loop iteration 更新

        execution = profile.get("execution") or {}
        self.execution_mode = execution.get("mode", "foreground")
        target_handle_fn = self._get_target_handle if self.execution_mode == "win32_background" else None
        self.detector = StateDetector(
            logger=logger, capture_mode=self.execution_mode, target_handle_fn=target_handle_fn
        )
        self.executor = ActionExecutor(
            logger=logger, backend=self.execution_mode, target_handle_fn=target_handle_fn
        )

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
        self._brightness_triggers = [
            trigger for trigger in profile.get("brightness_triggers", [])
            if trigger.get("enabled", True)
        ]
        started_at = time.monotonic()
        self._brightness_runtime = [
            {"last_run": started_at, "has_run": False, "last_bright": False}
            for _ in self._brightness_triggers
        ]

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self.on_state_change = None  # GUI 可掛上 callback(state_name)
        self.action_count = 0
        self.last_state = None

    def _get_target_handle(self):
        if not self.window_manager or not self.window_title_substring:
            return None
        return self.window_manager.get_handle(self.window_title_substring)

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

    def _sample_trigger_brightness(self, trigger: dict, background_frame=None):
        label = trigger.get("watch_coord_label", "")
        xy = self.coords.resolve(label, self.current_window_rect)
        if xy is None:
            if self.logger:
                self.logger.warn(f"亮度觸發器找不到偵測座標: {label}")
            return None
        radius = int(trigger.get("radius", 3))
        if background_frame is not None:
            return brightness_detector.sample_frame(
                background_frame, xy[0], xy[1], radius, self.current_window_rect
            )
        return brightness_detector.sample_screen(xy[0], xy[1], radius)

    def _run_brightness_triggers(self):
        if not self._brightness_triggers:
            return
        background_frame = None
        if self.execution_mode == "win32_background":
            hwnd = self._get_target_handle()
            background_frame = win32_backend.capture_window(hwnd) if hwnd else None
            if background_frame is None:
                if self.logger:
                    self.logger.warn("亮度觸發器無法取得背景畫面")
                return

        now = time.monotonic()
        for index, trigger in enumerate(self._brightness_triggers):
            value = self._sample_trigger_brightness(trigger, background_frame)
            if value is None:
                continue
            runtime = self._brightness_runtime[index]
            threshold = float(trigger.get("threshold", 180))
            bright = value >= threshold
            elapsed = now - runtime["last_run"]
            cooldown = max(0.05, float(trigger.get("cooldown_seconds", 1.0)))
            force_after = max(0.0, float(trigger.get("force_after_seconds", 0.0)))
            reason = None
            if bright and (not runtime["has_run"] or elapsed >= cooldown):
                reason = "偵測到發亮"
            elif not bright and force_after > 0 and elapsed >= force_after:
                reason = f"未發亮已超過 {force_after:g} 秒"

            runtime["last_bright"] = bright
            if not reason:
                continue
            actions = self._resolve_actions(trigger.get("actions", []))
            if not actions:
                continue
            self.executor.run_sequence(actions)
            runtime["last_run"] = time.monotonic()
            runtime["has_run"] = True
            self.action_count += len(actions)
            if self.logger:
                name = trigger.get("name") or f"觸發器 {index + 1}"
                self.logger.event(
                    f"亮度觸發「{name}」: {reason}（目前亮度 {value:.1f} / 門檻 {threshold:g}）"
                )

    # ---- 主迴圈 ----
    def _run_loop(self):
        if self.logger:
            mode_name = "Win32 背景模式" if self.execution_mode == "win32_background" else "前景模式"
            self.logger.info(f"State machine 開始執行（{mode_name}）")
        if self.execution_mode == "win32_background" and not self.window_title_substring:
            if self.logger:
                self.logger.error("Win32 背景模式必須先鎖定目標視窗。")
            self._running = False
            return
        if self.execution_mode == "win32_background" and not win32_backend.WIN32_AVAILABLE:
            if self.logger:
                self.logger.error("Win32 背景模式只支援 Windows。")
            self._running = False
            return
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
                if self.activate_before_action and self.execution_mode != "win32_background":
                    self.window_manager.activate(self.window_title_substring)

            try:
                self._run_brightness_triggers()
            except ActionAbort:
                break
            except Exception as e:
                if self.logger:
                    self.logger.error(f"亮度觸發器執行失敗: {e}")

            if not self._states:
                time.sleep(self._loop_interval)
                continue

            state_name = self.detector.detect_state(self._states, self._priority, self.current_window_rect)

            if state_name is None:
                consecutive_unknown += 1
                if self.logger:
                    self.logger.warn(f"目前畫面無法辨識任何已知狀態 (連續 {consecutive_unknown} 次)")
                if consecutive_unknown >= 5 and not self._brightness_triggers:
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
