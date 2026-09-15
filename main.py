#!/usr/bin/env python3
"""
通用 GUI 自動化框架 — 入口點

用法:
    python3 main.py

需求:
    - Python 3.9+
    - 一個真實可用的顯示器（本框架操作的是「你自己的桌面畫面」，
      不能在沒有螢幕的伺服器/容器環境跑實際自動化，只有 UI 本身在無顯示器環境也無法開啟）
    - pip install -r requirements.txt

這是一個 target-agnostic 的框架：本身不包含任何指定網站/遊戲/程式的座標或設定，
所有「打哪裡、怎麼判斷狀態」都由你自己透過 GUI 錄製、存成 profile (JSON)。
使用前請確認你要自動化的目標允許這麼做（你自己的軟體、你有權限的內部系統、
或明確允許自動化測試的環境）。
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from gui.main_window import MainWindow  # noqa: E402


def main():
    app = MainWindow(BASE_DIR)
    app.mainloop()


if __name__ == "__main__":
    main()
