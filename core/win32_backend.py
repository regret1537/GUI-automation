"""Windows 背景視窗輸入與擷取。

這個 backend 不移動實體滑鼠，而是把 Windows 訊息直接送到指定視窗。
它適合「視窗仍開著，但可能被其他視窗遮住」的情境。DirectX/Raw Input/
防作弊保護的程式可能忽略這些訊息；呼叫端必須把它視為相容模式，而不是保證。
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Optional


WIN32_AVAILABLE = os.name == "nt"

if WIN32_AVAILABLE:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.GetWindowDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.restype = wintypes.HANDLE

    WM_MOUSEMOVE = 0x0200
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONDOWN = 0x0204
    WM_RBUTTONUP = 0x0205
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_CHAR = 0x0102
    MK_LBUTTON = 0x0001
    MK_RBUTTON = 0x0002
    PW_RENDERFULLCONTENT = 0x00000002
    DIB_RGB_COLORS = 0
    SRCCOPY = 0x00CC0020


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG), ("top", wintypes.LONG),
        ("right", wintypes.LONG), ("bottom", wintypes.LONG),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _require_windows():
    if not WIN32_AVAILABLE:
        raise RuntimeError("Win32 背景模式只支援 Windows。")


def _make_lparam(x: int, y: int) -> int:
    return (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)


def _client_point(hwnd: int, screen_x: int, screen_y: int) -> tuple[int, int]:
    point = POINT(int(screen_x), int(screen_y))
    if not user32.ScreenToClient(hwnd, ctypes.byref(point)):
        raise RuntimeError("無法把螢幕座標換算成目標視窗座標。")
    return int(point.x), int(point.y)


def post_mouse(hwnd: int, screen_x: int, screen_y: int, action: str, button: str = "left"):
    """把滑鼠訊息送到 hwnd；輸入座標使用既有的螢幕絕對座標。"""
    _require_windows()
    if not hwnd or not user32.IsWindow(hwnd):
        raise RuntimeError("目標視窗不存在或已關閉。")
    x, y = _client_point(hwnd, screen_x, screen_y)
    lp = _make_lparam(x, y)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
    if action == "move":
        return
    if button == "right":
        down, up, flag = WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON
    else:
        down, up, flag = WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON
    count = 2 if action == "double_click" else 1
    for _ in range(count):
        user32.PostMessageW(hwnd, down, flag, lp)
        user32.PostMessageW(hwnd, up, 0, lp)
        if count == 2:
            time.sleep(0.05)


def post_text(hwnd: int, text: str, interval: float = 0.02):
    _require_windows()
    if not hwnd or not user32.IsWindow(hwnd):
        raise RuntimeError("目標視窗不存在或已關閉。")
    for char in text:
        user32.PostMessageW(hwnd, WM_CHAR, ord(char), 0)
        if interval:
            time.sleep(interval)


_VK_NAMES = {
    "enter": 0x0D, "return": 0x0D, "escape": 0x1B, "esc": 0x1B,
    "space": 0x20, "tab": 0x09, "backspace": 0x08, "delete": 0x2E,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
}


def post_key(hwnd: int, key_name: str):
    _require_windows()
    if not hwnd or not user32.IsWindow(hwnd):
        raise RuntimeError("目標視窗不存在或已關閉。")
    name = (key_name or "").lower()
    vk = _VK_NAMES.get(name)
    if vk is None and len(name) == 1:
        vk = user32.VkKeyScanW(name) & 0xFF
    if vk is None:
        raise RuntimeError(f"Win32 背景模式不支援按鍵: {key_name}")
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)


def capture_window(hwnd: int):
    """以 PrintWindow 擷取被遮住的視窗，回傳 OpenCV BGR ndarray 或 None。"""
    _require_windows()
    if not hwnd or not user32.IsWindow(hwnd):
        return None
    try:
        import numpy as np
    except Exception as exc:  # pragma: no cover - requirements 已包含 numpy
        raise RuntimeError("背景擷取需要 numpy。") from exc

    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old_obj = gdi32.SelectObject(memory_dc, bitmap)
    try:
        ok = user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT)
        if not ok:
            # 某些傳統視窗不支援 PW_RENDERFULLCONTENT，退回一般 PrintWindow。
            ok = user32.PrintWindow(hwnd, memory_dc, 0)
        if not ok:
            return None

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # top-down，避免額外翻轉
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        buf = ctypes.create_string_buffer(width * height * 4)
        lines = gdi32.GetDIBits(
            memory_dc, bitmap, 0, height, buf, ctypes.byref(info), DIB_RGB_COLORS
        )
        if lines != height:
            return None
        bgra = np.frombuffer(buf, dtype=np.uint8).reshape((height, width, 4))
        frame = bgra[:, :, :3].copy()
        # DirectX 獨佔／受保護畫面常讓 PrintWindow 回傳全黑影像。
        if float(frame.std()) < 0.5:
            return None
        return frame
    finally:
        gdi32.SelectObject(memory_dc, old_obj)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def compatibility_summary() -> str:
    if not WIN32_AVAILABLE:
        return "不可用：目前不是 Windows"
    return "可嘗試：視窗需保持開啟；DirectX/Raw Input/防作弊程式可能拒絕背景輸入或回傳黑畫面"
