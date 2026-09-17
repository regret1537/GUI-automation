# GUI Automation Framework

通用、target-agnostic 的桌面 GUI 自動化框架（Python + PyAutoGUI + OpenCV template matching + Tkinter）。

架構對應「感知 → 決策 → 動作 → 驗證」(perceive-decide-act-verify) 迴圈：

```
Coordinate Registry  座標快取層（錄哪裡、失效重掃機制）
State Detector       狀態偵測層（screenshot + template matching，判斷目前畫面是哪個狀態）
Action Executor      動作執行層（click/type/wait + retry-confirm pattern）
State Machine        Orchestrator，串起上面三層跑主迴圈
Event Classifier      事件分類層（決定什麼值得上報通知）
```

## ⚠️ 使用前必讀

這是一個**通用工具**，本身不包含任何指定網站、遊戲或程式的座標與設定。所有「打哪裡、怎麼判斷狀態」都要你自己用內建的錄製工具建立。

**請只用在你確定有權限自動化的目標**：你自己開發/擁有的軟體、你有明確授權的內部系統、或條款明確允許自動化測試的環境。很多線上服務（尤其是有帳號綁定、有虛擬獎勵/排行榜的服務）的使用條款明文禁止巨集/外掛/自動化程式，用在那類目標上可能導致帳號或資格被停權——這是你自己要評估的風險，工具本身不做這個判斷。

安全閥：`pyautogui.FAILSAFE = True` 預設開啟，**滑鼠移到螢幕任一角落會立即中止**，這是跑自動化時的緊急煞車，不要在程式碼裡把它關掉。

## 安裝

```bash
pip install -r requirements.txt
```

Linux 另外需要系統套件（不是 pip 裝）：

```bash
sudo apt-get install python3-tk      # Debian/Ubuntu
```

## 執行

```bash
python3 main.py
```

需要一個真實的顯示器/桌面環境——這個工具操作的是你自己螢幕上的畫面，無法在沒有螢幕的伺服器上做實際自動化（GUI 本身在無顯示器環境也開不起來）。

## 使用流程

### ① 座標錄製
輸入 label（例如 `btn_start`），按「開始錄製」，3 秒內把滑鼠移到畫面上要點擊的位置，時間到自動擷取座標。

### ② 狀態錨點截圖
框選畫面上一小塊「這個狀態獨有、穩定不變」的區域（例如某個按鈕、標題文字），存成 PNG，之後 State Detector 會拿這張圖去畫面上做 template matching。

**錨點截圖的挑選原則**（很重要，直接影響辨識準確度）：
- 選**不會變動**的元素（固定文字、圖示外框），不要選會變的內容（動態數字、跑動的角色）
- 範圍不要太大（背景雜訊多，matching 較不穩定），也不要太小（容易跟其他元素混淆）
- 同一個狀態如果在不同解析度/縮放下長得不一樣，可以設定多個 anchor 並用 `match_mode: "any"`

### ③ 圖形化流程設定
不需要手寫 JSON。表單與按鈕可以直接設定：
- Profile 名稱、檢查間隔與執行模式
- 新增、刪除及調整狀態判斷順序
- 選擇辨識圖片、設定準確度與搜尋範圍
- 新增、編輯、刪除及排序 click / double_click / move / wait / type / key 動作
- 從①匯入座標、同步目前鎖定視窗

「進階 JSON」分頁仍然保留，方便需要手動微調或貼入既有設定的使用者。

Profile 儲存的 JSON 定義：
- `coordinates`：座標表（可以從①一鍵匯入）
- `states`：每個狀態要比對哪些 anchor、命中後要執行哪串動作 (`on_enter_actions`)
- `state_priority`：偵測時的檢查順序
- `loop_interval_seconds`：主迴圈間隔

完整格式說明在 `core/profile_io.py` 檔頭註解。`profiles/example_calculator/profile.json` 是一個範例骨架（計算機 1+2=3 的示意），**座標是佔位值 (0,0)、錨點圖檔不存在**，你需要用①②實際錄製後才能真的跑起來——這是刻意的，框架不預先附上任何可以直接執行的目標設定。

### ④ 執行監控
Start / Pause / Resume / Stop，即時 log 面板會顯示狀態切換、每次動作、以及 WARN/ERROR。

`Pause` 是軟暫停（迴圈跑到下個檢查點就停住，可以隨時 Resume）；真的要立刻斷開用 `Stop`，或直接把滑鼠甩到螢幕角落觸發 FAILSAFE。

## 前景與 Win32 背景模式

在③的「執行模式」可以選：

- **前景模式**：使用 PyAutoGUI，控制實體滑鼠與鍵盤；相容性最高。
- **Win32 背景模式（實驗性）**：Windows 專用，以 `PostMessage` 把輸入送到鎖定視窗，並用 `PrintWindow` 擷取被遮住的視窗；不會移動實體滑鼠。

背景模式必須先鎖定目標視窗，視窗可被其他視窗遮住，但請勿最小化。DirectX、Raw Input、獨佔全螢幕或有防作弊保護的程式可能忽略背景輸入，或讓 `PrintWindow` 只取得黑畫面；這是目標程式的輸入／擷取限制，無法保證所有遊戲都相容。遇到不相容時請改回前景模式，或把目標放到獨立的虛擬機／另一台電腦執行。

## 視窗鎖定 (Window Lock)

主視窗最上方常駐一個「視窗鎖定」面板，橫跨所有分頁，用來把座標與偵測範圍「釘」在特定視窗上，而不是寫死在螢幕絕對座標。

**解決什麼問題**：沒有鎖定視窗時，所有座標都是螢幕絕對位置——目標視窗只要移動、被使用者拖到別的地方，錄好的座標就全部失準。鎖定之後，座標改成存「相對於視窗左上角的偏移量」，視窗移動了，執行時會自動用當下的視窗位置重新換算，不用重錄。

**操作方式**：
1. 開啟你要自動化的目標視窗
2. 按「重新整理視窗列表」，從下拉選單選一個標題（或直接打關鍵字），按「鎖定」
3. 勾選「執行前自動置頂視窗」的話，State Machine 每輪動作前會自動把該視窗帶到最上層，避免不小心點到別的視窗
4. 回到①分頁錄座標——面板上會提示「視窗鎖定中」，這時錄的座標會自動換算成相對於視窗的偏移量（表格的「相對座標?」欄位會顯示「是」）
5. 到③分頁按「同步視窗鎖定設定」，把目前鎖定的視窗標題寫進 profile 的 `window_lock` 欄位，之後存檔就會記住這個設定

**沒鎖定視窗也完全能用**——這是選填功能，維持原本的全螢幕絕對座標模式（`relative: false`，也是預設值）。

**技術限制**：
- 依賴 `pywinctl`，支援 Windows / macOS / Linux(X11)，**不支援 Wayland**（Linux 桌面環境用 Wayland 的話，這個功能會不可用，錄座標退回全螢幕絕對模式）
- 用「標題關鍵字重新搜尋」而不是保留固定的 window handle，所以標題要夠獨特，不然可能抓到同名的別的視窗
- State Detector 的 anchor 如果自己有指定 `region`，會優先用那個 region，不會被視窗鎖定覆蓋；只有 `region: null` 的 anchor 才會自動用鎖定視窗的範圍當搜尋區域

## 目錄結構

```
gui-automation-framework/
├── main.py                    入口點
├── core/                      核心邏輯（無 GUI 依賴，理論上可以拿去接 CLI 版本）
│   ├── coordinate_registry.py
│   ├── state_detector.py
│   ├── action_executor.py
│   ├── state_machine.py
│   ├── event_classifier.py
│   ├── profile_io.py
│   ├── window_manager.py      視窗鎖定（跨平台視窗查找/取得位置/置頂）
│   ├── win32_backend.py       Windows 背景擷取與輸入（實驗性）
│   └── logger.py
├── gui/                       Tkinter 介面
│   ├── main_window.py
│   ├── window_lock_panel.py   視窗鎖定面板（常駐主視窗上方）
│   ├── coord_tab.py
│   ├── template_tab.py
│   ├── profile_tab.py
│   └── run_tab.py
├── templates/                 你截的 anchor PNG 都存這裡
├── profiles/                  你存的 profile JSON
└── logs/                      每次執行的 log 檔
```

## 已知限制 / 之後可以擴充的方向

- State Detector 只做 template matching，沒有 OCR；如果你的判斷條件是「畫面上某個數字」而不是固定圖案，需要自己接 OCR（例如 `pytesseract`）或用像素顏色比對取代
- `click_with_confirm` 的 `confirm_fn` 需要呼叫端自己實作判斷邏輯（框架不假設任何特定 UI 回饋方式）
- 沒有內建排程/多目標視窗管理，同一時間設計上只跑一個 profile
- 全域熱鍵（例如跑起來後用鍵盤快速鍵 Pause）目前沒做，只能用 GUI 按鈕；如果需要，可以加 `keyboard` 套件實作，但 Linux 上通常需要額外權限
