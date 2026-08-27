# 每日收盤後選股：KD打勾＋月線上＋籌碼轉強

依照你設定的 5 條件邏輯做的收盤後選股程式：

1. **股價站上 20日月線**（最好月線走平或向上；剛站回月線也列入觀察）
2. **KD 向上打勾**（K由下往上轉，最漂亮是 K上穿D；高檔鈍化已久的打勾會降權）
3. **法人籌碼轉強**（外資由賣轉買 / 投信連買 / 三大法人合計由賣轉買，任一即算）
4. **融資沒有暴增**（股價漲＋融資也暴增 -> 扣分警示；融資持平或下降 -> 加分）
5. **突破或轉強有量**（帶量突破前高/整理區，且收盤不是長上影線）

每檔股票會算出：① ~ ⑤ 是否過關（達成數 0~5，對應你原本的「5項全中→主力觀察名單／4項→值得研究／3項→等待確認／2項以下→跳過」），
以及一個 0~100 的**加權分數**，權重依你說的優先順序：**月線(35) ＞ 籌碼(30) ＞ 成交量(20) ＞ KD(15)**，融資暴增則直接扣分。
同一達成數的股票，會再用加權分數排序。

資料來源是 **台灣證交所(TWSE)/櫃買中心(TPEX)的公開 JSON API**，不用付費、不用 API key。

這支程式跟 Claude／AI 完全沒有關係，就是純 Python 直接打政府/交易所的公開資料，只要放在一個能連網路的地方排程執行，就會自己每天全自動抓資料、算分、存結果，不需要經過我、也不需要你手動操作。

- 目前**上市(TWSE)** 三個資料源（收盤價、三大法人、融資融券）**已實際測試成功**。
- **上櫃(TPEX)** 的端點是照官方一貫的路徑格式寫的，但開發環境網路受限沒辦法實際驗證欄位順序，
  預設是**關閉**的（`config.py` 裡 `MARKETS = ["TWSE"]`）。想加開上櫃，請看下面「啟用上櫃(TPEX)」。

---

## 🚀 用 GitHub Actions 全自動執行（推薦）

完全不需要自己的電腦開著、不需要付費，GitHub 會在雲端每天自動幫你跑，結果存回這個 repo。
以下全部用瀏覽器網頁操作，不需要用到任何指令。

### 1. 建立一個新的 repository

1. 登入 [github.com](https://github.com)。
2. 右上角點「+」→「New repository」。
3. 幫它取個名字，例如 `stock-screener`。
4. 建議選 **Private**（只有你看得到）。
5. 其他選項不用動，直接點「Create repository」。

### 2. 把這個資料夾的檔案上傳上去

1. 建立完成後，頁面上會有一個「uploading an existing file」的連結，點下去。
2. 把你電腦上解壓縮後 `stock_screener` 資料夾**裡面的所有檔案和資料夾**（包含看起來像隱藏檔的 `.github` 資料夾）一次拖曳到瀏覽器的上傳區塊。
   - 用 Chrome 或 Edge 瀏覽器，直接把整個資料夾從「檔案總管/Finder」拖進去，會保留資料夾結構，不用一個一個上傳。
   - 如果你的瀏覽器不支援拖資料夾，就把資料夾裡的東西全選再拖曳，或分批把子資料夾（`.github/workflows`、`cache`、`output`）個別拖上去。
3. 下方 commit 訊息欄位隨便打一行字（例如「first commit」），點「Commit changes」。

### 3. 開啟 Actions 排程

1. 上傳完後，點頁面上方的「Actions」分頁。
2. 如果看到「I understand my workflows, go ahead and enable them」之類的提示，點下去啟用。
3. 左邊應該會看到一個叫「每日收盤後選股」的 workflow，點進去。
4. 右邊會有「Run workflow」按鈕，先手動點一次測試（不用等到排程時間），確認能正常跑。
5. 等 1~2 分鐘（第一次要回補歷史資料會久一點，可能到 5~10 分鐘），跑完前面會出現綠色勾勾。
6. 回到 repo 首頁，打開 `output` 資料夾，就能看到今天的 `screen_YYYYMMDD.csv`。

之後它會照 `.github/workflows/daily_screen.yml` 裡設定的排程，**每個交易日晚上自動執行**（預設台灣時間晚上 7:30，這樣三大法人、融資融券資料當天都已公告齊全），把結果自動存回 `output` 資料夾，你只要有空就打開 repo 看就好。

如果想換時間，打開該檔案裡的 `cron: "30 11 * * 1-5"` 這一行調整（這是 UTC 時間，要換算：台灣時間 -8 小時）。

### 4. 開啟網頁報表（GitHub Pages）——像個小型App一樣，開固定網址就能看

程式每天執行完，除了 CSV，也會順便產生一份手機看起來比較舒服的網頁報表放在 `docs` 資料夾。要讓這份報表能用網址打開，需要手動開啟一次 GitHub Pages（只要設定一次）：

1. 在 repo 頁面點最上面「Settings」（設定）。
2. 左側選單點「Pages」。
3. 「Build and deployment」底下的「Source」選 **Deploy from a branch**。
4. Branch 選 **main**，右邊資料夾選 **/docs**，點「Save」。
5. 存檔後，GitHub 會顯示一個網址，格式大概是 `https://你的帳號.github.io/repo名稱/`，第一次通常要等 1~2 分鐘才會生效。

之後每次自動執行完，這個網址打開看到的內容就會自動更新成最新一天的報表，把這個網址加到手機瀏覽器的「加入主畫面」，就會很像一個App的圖示可以直接點開。

> 小提醒：因為你的 repo 名稱是中文「股票篩選器」，網址裡中文字會變成一串 `%E8%82%A1...` 這種編碼，能用但不好看也不好分享。如果想要網址乾淨一點，可以到 Settings 最上面把 repo 改名成英文，例如 `stock-screener`（改名不影響裡面任何檔案跟排程設定）。

### 之後想調整規則的門檻/權重？

直接在 GitHub 網頁上點開 `config.py`，按右上角鉛筆圖示編輯，改完按「Commit changes」存檔，下次自動執行就會套用新設定，完全不需要用到 git 指令或自己的電腦。

---

## 在自己的電腦上跑（測試或不想用 GitHub Actions 時）

## 安裝

需要 Python 3.8+。

```bash
cd stock_screener
pip install -r requirements.txt
```

## 第一次使用

```bash
# 先跑一次「內建測試」，確認邏輯正確（不需要網路，幾秒鐘跑完）
python test_parsers.py       # 驗證資料解析（用真實API格式的樣本資料）
python test_synthetic.py     # 驗證選股計分邏輯（合成一個理想型態、一個反例）

# 正式跑選股（第一次會自動回補約70個交易日的歷史資料，用來算月線/KD/前高，會花幾分鐘）
python main.py
```

看到類似這樣的結果：

```
共 12 檔符合條件：

代號     名稱      收盤    漲跌%   ①月線 ②KD  ③籌碼 ④融資 ⑤量   達成 分級        加權分  備註
2330    台積電   1150.00  +2.15%  ✅    ✅   ✅    ✅    ✅    5    🔥主力觀察名單  91.0   站穩月線且月線向上；K上穿D...
```

同時會輸出一份 CSV 到 `output/screen_YYYYMMDD.csv`，方便你開 Excel 複查；也會輸出網頁報表到 `docs/index.html`（在本機執行的話，直接用瀏覽器打開這個檔案就能看，不需要 GitHub Pages）。

## 之後每天怎麼跑

台股收盤後、法人與融資資料通常要到 **約下午 14:30 之後**官方才會公告完整，建議每天 **15:00 之後**再跑：

```bash
python main.py                    # 篩選今天
python main.py --date 2026-08-25  # 篩選指定日期
python main.py --min 4            # 只看達成4項以上的（預設3項）
```

因為歷史資料已經快取在 `cache/market_data.sqlite3`，之後每天只會抓「新的一天」，會比第一次快很多。

如果你的電腦/伺服器支援排程，可以設成每個交易日下午自動跑一次（Linux/Mac 用 `cron`，Windows 用「工作排程器」），
跟我說一聲要用哪個系統，我可以幫你寫對應的排程指令。

## 啟用上櫃 (TPEX)

1. `python main.py --test-tpex`，看印出來的原始資料欄位對不對。
2. 如果格式跟 `fetch_tpex.py` 檔頭註解假設的不一樣，對照 `fetch_twse.py` 的寫法調整欄位索引即可（架構完全一樣）。
3. 確認沒問題後，把 `config.py` 的 `MARKETS = ["TWSE"]` 改成 `MARKETS = ["TWSE", "TPEX"]`。

## 可以調整的地方（都在 `config.py`）

- `WEIGHT_MA20 / WEIGHT_CHIPS / WEIGHT_VOLUME / WEIGHT_KD`：加權分數的權重比例
- `MARGIN_SURGE_THRESHOLD`：融資「暴增」的門檻（預設漲超過3%算暴增）
- `VOLUME_SURGE_RATIO`：「放量」的倍數門檻（預設要大於近5日均量的1.5倍）
- `KD_HIGH_ZONE` / `KD_STAGNANT_DAYS`：判斷「高檔鈍化太久」的標準
- `BREAKOUT_LOOKBACK`：判斷「前高/整理區」回顧幾天

## 檔案結構

```
.github/workflows/daily_screen.yml   GitHub Actions 排程設定（每天自動執行、結果自動commit回repo）
config.py         所有可調參數
db.py             本地 SQLite 快取（避免每天重抓全部歷史）
fetch_common.py   共用的 HTTP 請求工具
tradedays.py       交易日期輔助
fetch_twse.py      上市資料抓取（已驗證）
fetch_tpex.py      上櫃資料抓取（實驗性，見檔頭說明）
indicators.py      MA20 / KD(9,3,3) / 均量 / 前高 計算
screener.py         5條件判斷 + 加權評分（核心邏輯都在這）
report.py           產生手機看的網頁報表（docs/index.html）
main.py             主程式 / CLI 入口
test_parsers.py     用真實API格式驗證資料解析
test_synthetic.py   用合成資料驗證選股計分邏輯
cache/             本地資料快取（GitHub Actions會自動commit回來，加速下次執行）
output/            每天的選股結果 CSV
docs/              網頁報表（搭配 GitHub Pages 用，見上面「開啟網頁報表」）
```

## ⚠️ 免責聲明

這支程式只是把你自己定義的技術面／籌碼面規則機械化地跑一遍，**幫你縮小觀察範圍**，
不是投資建議，出現在名單上不代表會漲、沒出現也不代表不會漲。所有交易決策與風險，仍需要你自己判斷。
