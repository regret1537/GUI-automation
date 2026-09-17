"""
Profile IO — 讀寫「打哪裡、怎麼判斷狀態、狀態下要做什麼」的設定檔 (JSON)。

Profile 結構（範例見 profiles/example_calculator/profile.json）：

{
  "name": "profile 名稱",
  "execution": {"mode": "foreground" | "win32_background"},
  "window_lock": {                          // 選填。不設定就是全螢幕絕對座標模式（舊行為）
    "title_substring": "視窗標題的一部分",      // 用來搜尋目標視窗，需要夠獨特避免抓錯
    "activate_before_action": true            // 每輪動作前先把視窗帶到最上層
  },
  "coordinates": {
    "label": {"x": 100, "y": 200, "note": "...", "relative": false}
    // relative=true 時，x,y 是相對於視窗左上角的偏移量（由座標錄製器在鎖定視窗時自動算好），
    // 不是螢幕絕對座標；relative=false（預設）維持原本的全螢幕絕對座標行為。
  },
  "states": {
    "state_name": {
      "match_mode": "any" | "all",
      "anchors": [
        {"template_path": "templates/xxx.png", "region": [x,y,w,h] 或 null, "confidence": 0.85}
      ],
      "on_enter_actions": [
        {"type": "click", "coord_label": "label"},   // 也可以直接用 "coord": [x,y]
        {"type": "wait", "seconds": 0.5}
      ]
    }
  },
  "state_priority": ["state_a", "state_b", ...],   // 偵測時的檢查順序，可省略
  "brightness_triggers": [
    {
      "name": "技能 1",
      "watch_coord_label": "技能圖示中心",
      "threshold": 180,
      "radius": 3,
      "cooldown_seconds": 1.0,
      "force_after_seconds": 10.0,
      "actions": [{"type": "key", "key": "f1"}, {"type": "click", "coord_label": "目標", "button": "left"}]
    }
  ],
  "loop_interval_seconds": 1.0
}

此模組只負責讀寫 + 基本結構驗證，不做任何特定目標的預設值 —— 使用者要自己錄座標、
自己截 anchor 圖、自己定義狀態轉移，這是刻意的設計，框架保持 target-agnostic。
"""
from __future__ import annotations
import json
import os
from typing import Dict, Any

REQUIRED_TOP_KEYS = ("name", "coordinates", "states")


def new_empty_profile(name: str = "未命名 profile") -> Dict[str, Any]:
    return {
        "name": name,
        "coordinates": {},
        "states": {},
        "state_priority": [],
        "loop_interval_seconds": 1.0,
        "execution": {"mode": "foreground"},
        "brightness_triggers": [],
    }


def validate_profile(data: Dict[str, Any]) -> list:
    """回傳錯誤訊息列表，空列表代表通過驗證。"""
    errors = []
    for key in REQUIRED_TOP_KEYS:
        if key not in data:
            errors.append(f"缺少必要欄位: {key}")
    if "states" in data and not isinstance(data["states"], dict):
        errors.append("states 必須是物件 (dict)")
    if "coordinates" in data and not isinstance(data["coordinates"], dict):
        errors.append("coordinates 必須是物件 (dict)")
    execution = data.get("execution") or {}
    if not isinstance(execution, dict):
        errors.append("execution 必須是物件 (dict)")
        execution = {}
    mode = execution.get("mode", "foreground")
    if mode not in ("foreground", "win32_background"):
        errors.append("execution.mode 必須是 foreground 或 win32_background")
    window_lock = data.get("window_lock") or {}
    if window_lock and not isinstance(window_lock, dict):
        errors.append("window_lock 必須是物件 (dict)")
        window_lock = {}
    if mode == "win32_background" and not window_lock.get("title_substring"):
        errors.append("Win32 背景模式必須設定 window_lock.title_substring（請先鎖定目標視窗）")
    triggers = data.get("brightness_triggers", [])
    if not isinstance(triggers, list):
        errors.append("brightness_triggers 必須是陣列 (list)")
        triggers = []
    coordinates = data.get("coordinates") if isinstance(data.get("coordinates"), dict) else {}
    for index, trigger in enumerate(triggers, start=1):
        prefix = f"亮度觸發器 #{index}"
        if not isinstance(trigger, dict):
            errors.append(f"{prefix} 必須是物件")
            continue
        watch_label = trigger.get("watch_coord_label", "")
        if not watch_label:
            errors.append(f"{prefix} 缺少偵測座標")
        elif watch_label not in coordinates:
            errors.append(f"{prefix} 的偵測座標不存在: {watch_label}")
        try:
            threshold = float(trigger.get("threshold", 180))
            if not 0 <= threshold <= 255:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{prefix} 的亮度門檻必須是 0～255")
        try:
            if int(trigger.get("radius", 3)) < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{prefix} 的取樣半徑必須是 0 或正整數")
        try:
            if float(trigger.get("cooldown_seconds", 1.0)) <= 0:
                raise ValueError
            if float(trigger.get("force_after_seconds", 0.0)) < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{prefix} 的冷卻秒數須大於 0，強制執行秒數不可小於 0")
        actions = trigger.get("actions", [])
        if not isinstance(actions, list) or not actions:
            errors.append(f"{prefix} 至少要設定一個執行動作")
            continue
        for action_index, action in enumerate(actions, start=1):
            if not isinstance(action, dict):
                errors.append(f"{prefix} 動作 #{action_index} 必須是物件")
                continue
            action_type = action.get("type")
            if action_type == "key":
                key = str(action.get("key", "")).lower()
                allowed = {f"f{i}" for i in range(1, 13)}
                if key not in allowed:
                    errors.append(f"{prefix} 鍵盤動作只支援 F1～F12")
            elif action_type == "click":
                coord_label = action.get("coord_label", "")
                if coord_label not in coordinates:
                    errors.append(f"{prefix} 的點擊座標不存在: {coord_label}")
                if action.get("button", "left") not in ("left", "right"):
                    errors.append(f"{prefix} 的滑鼠按鍵必須是 left 或 right")
            else:
                errors.append(f"{prefix} 不支援動作類型: {action_type}")
    return errors


def load_profile(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    errors = validate_profile(data)
    if errors:
        raise ValueError("Profile 格式錯誤:\n" + "\n".join(errors))
    return data


def save_profile(path: str, data: Dict[str, Any]):
    errors = validate_profile(data)
    if errors:
        raise ValueError("Profile 格式錯誤，拒絕存檔:\n" + "\n".join(errors))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
