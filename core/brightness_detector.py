"""座標附近亮度取樣，供亮度觸發器使用。"""
from __future__ import annotations

from typing import Optional

import numpy as np

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    pyautogui = None
    PYAUTOGUI_AVAILABLE = False


def _brightness_from_bgr(patch: np.ndarray) -> Optional[float]:
    """以亮度最高的 25% 像素平均值判斷發亮，避免單一雜訊像素誤判。"""
    if patch is None or patch.size == 0:
        return None
    values = (
        patch[..., 0].astype(np.float32) * 0.114
        + patch[..., 1].astype(np.float32) * 0.587
        + patch[..., 2].astype(np.float32) * 0.299
    ).reshape(-1)
    cutoff = np.percentile(values, 75)
    bright_values = values[values >= cutoff]
    return float(bright_values.mean()) if bright_values.size else float(values.mean())


def sample_frame(
    frame_bgr: np.ndarray,
    screen_x: int,
    screen_y: int,
    radius: int = 3,
    window_rect: Optional[tuple] = None,
) -> Optional[float]:
    """從背景擷取畫面取樣；傳入座標仍是既有的螢幕絕對座標。"""
    x, y = int(screen_x), int(screen_y)
    if window_rect:
        x -= int(window_rect[0])
        y -= int(window_rect[1])
    radius = max(0, int(radius))
    height, width = frame_bgr.shape[:2]
    x0, x1 = max(0, x - radius), min(width, x + radius + 1)
    y0, y1 = max(0, y - radius), min(height, y + radius + 1)
    return _brightness_from_bgr(frame_bgr[y0:y1, x0:x1])


def sample_screen(screen_x: int, screen_y: int, radius: int = 3) -> Optional[float]:
    """從目前桌面畫面取樣，供前景模式使用。"""
    if not PYAUTOGUI_AVAILABLE:
        return None
    radius = max(0, int(radius))
    size = radius * 2 + 1
    try:
        image = pyautogui.screenshot(
            region=(int(screen_x) - radius, int(screen_y) - radius, size, size)
        )
        rgb = np.asarray(image.convert("RGB"))
        bgr = rgb[..., ::-1]
        return _brightness_from_bgr(bgr)
    except Exception:
        return None
