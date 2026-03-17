import os
from datetime import datetime
from typing import Tuple, List, Optional

import pandas as pd
import pandas_ta as ta
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title=“V12.3 Physical Audit Engine”)

# ✅ CORS：allow_methods 加入 OPTIONS，修正 Safari preflight 問題

app.add_middleware(
CORSMiddleware,
allow_origins=[”*”],  # 正式部署後請改為你的前端網址
allow_methods=[“GET”, “OPTIONS”],
allow_headers=[”*”],
)

# — 核心評分引擎 —

def get_v12_score(
info: dict,
rsi: Optional[float]  # ✅ 修正：明確接受 None，不假設 rsi 一定有值
) -> Tuple[int, List[str], List[str]]:
“””
5 大區塊評分系統（滿分 125）
所有 None 欄位顯式回報，拒絕靜默失敗。
“””
score = 0
details = []
warnings = []

```
# A. EPS 獲利面（0~20）
eps_raw = info.get('trailingEps')
if eps_raw is None:
    warnings.append("trailingEps 數據缺失，EPS 相關評分跳過")
    eps = None  # ✅ 修正：缺失就是 None，不用 0 代替，避免觸發假警報
else:
    eps = eps_raw
    if eps > 0:
        score += 20
        details.append(f"EPS 獲利中 ${eps:.2f} (+20)")
    else:
        details.append(f"EPS 虧損中 ${eps:.2f} (+0)")

# B. 估值面 P/B（0~20）
pb = info.get('priceToBook')
if pb is None:
    warnings.append("priceToBook 數據缺失，估值評分跳過")
elif 0 < pb < 2:
    score += 20
    details.append(f"P/B 位階安全 {pb:.2f}x (+20)")
else:
    details.append(f"P/B 偏高或異常 {pb:.2f}x (+0)")

# C. 營收成長面（0~25）
rev_growth = info.get('revenueGrowth')
if rev_growth is None:
    warnings.append("revenueGrowth 數據缺失（台股常見），營收評分跳過")
elif rev_growth > 0.15:
    score += 25
    details.append(f"營收擴張強勁 {rev_growth:.1%} (+25)")
elif rev_growth > 0:
    score += 10
    details.append(f"營收溫和成長 {rev_growth:.1%} (+10)")
else:
    details.append(f"營收衰退 {rev_growth:.1%} (+0)")

# D. 毛利率面（0~20）
margin = info.get('grossMargins')
if margin is None:
    warnings.append("grossMargins 數據缺失，毛利率評分跳過")
elif margin > 0.3:
    score += 20
    details.append(f"毛利率優良 {margin:.1%} (+20)")
elif margin > 0.1:
    score += 10
    details.append(f"毛利率普通 {margin:.1%} (+10)")
else:
    details.append(f"毛利率偏低 {margin:.1%} (+0)")

# E. 技術動能面（-20~40）
if rsi is None:
    # ✅ 修正：RSI 缺失時整區跳過，不做任何加減分
    warnings.append("RSI 無法計算，技術動能評分跳過")
elif rsi > 65:
    # ✅ 修正：eps 為 None 時不觸發假警報，只在確認虧損時才減分
    if eps is not None and eps <= 0:
        score -= 20
        details.append(f"🔴 背離警告：高動能(RSI={rsi:.1f})伴隨虧損，疑似炒作 (-20)")
    else:
        details.append(f"動能過熱 RSI={rsi:.1f}，觀察獲利支撐 (+0)")
elif 50 < rsi <= 65:
    score += 40
    details.append(f"技術動能自洽 RSI={rsi:.1f} (+40)")
else:
    details.append(f"動能偏弱 RSI={rsi:.1f} (+0)")

return min(max(score, 0), 125), details, warnings
```

# — API 端點 —

# ✅ 修正：改回同步 def，FastAPI 自動放入 thread pool，避免阻塞 event loop

@app.get(”/audit/{symbol}”)
def run_v12_audit(symbol: str):

```
# 第一層：網路 / 連線錯誤 → 500
try:
    ticker_str = f"{symbol.upper()}.TW"
    stock = yf.Ticker(ticker_str)
    hist = stock.history(period="100d")
except Exception as e:
    raise HTTPException(status_code=500, detail=f"yfinance 連線失敗：{str(e)}")

# 第二層：資料驗證錯誤 → 404 / 422
if hist is None or hist.empty:
    raise HTTPException(status_code=404, detail=f"找不到代號 {symbol}，請確認是否為有效台股代號")

if len(hist) < 20:
    raise HTTPException(status_code=422, detail=f"K 線資料不足（{len(hist)} 筆），至少需要 20 筆")

# 第三層：計算 / 邏輯錯誤 → 500
try:
    last_close = float(hist['Close'].iloc[-1])

    # RSI
    rsi_val = ta.rsi(hist['Close']).iloc[-1]
    rsi: Optional[float] = None if pd.isna(rsi_val) else round(float(rsi_val), 1)

    # ATR（含 fallback 旗標）
    atr_val = ta.atr(hist['High'], hist['Low'], hist['Close']).iloc[-1]
    atr_estimated = pd.isna(atr_val)
    atr = last_close * 0.03 if atr_estimated else float(atr_val)

    # 基本面
    info = stock.info
    if not info or (
        info.get('regularMarketPrice') is None and
        info.get('currentPrice') is None
    ):
        raise HTTPException(status_code=404, detail=f"無法取得 {symbol} 基本面資料，請確認代號")

    # 評分
    final_score, audit_details, warnings = get_v12_score(info, rsi)

    # 座標
    s_coord = last_close - (atr * 1.5)
    w_coord = last_close + (atr * 2.0)
    book_value = info.get('bookValue')
    r_coord = float(book_value) if book_value else last_close * 0.6
    r_estimated = book_value is None

    return {
        "symbol": symbol.upper(),
        "timestamp": datetime.now().isoformat(),
        "data_source": "Yahoo Finance（延遲約 15~20 分鐘，非即時）",
        "p_now": round(last_close, 2),
        "rsi": rsi,
        "v12_score": final_score,
        "v12_score_display": f"{final_score} / 125",
        "status": (
            "✅ 結構健全" if final_score >= 85 else
            "⚠️ 結構待校準" if final_score >= 50 else
            "🔴 高風險"
        ),
        "coordinates": {
            "W_resistance": round(w_coord, 2),
            "P_equilibrium": round(last_close, 2),
            "S_fracture": round(s_coord, 2),
            "R_geocenter": round(r_coord, 2),
            "atr_estimated": atr_estimated,
            "r_estimated": r_estimated
        },
        "audit_details": audit_details,
        "warnings": warnings
    }

except HTTPException:
    raise
except Exception as e:
    raise HTTPException(status_code=500, detail=f"審計引擎內部錯誤：{str(e)}")
```

# =============================================================

# 部署指南（Render / Railway）

# =============================================================

# 1. requirements.txt：

# fastapi

# uvicorn

# yfinance

# pandas_ta

# pandas

# 

# 2. 啟動指令：

# uvicorn main:app –host 0.0.0.0 –port $PORT

# 

# 3. Fugle 即時價升級：

# 在平台的 Environment Variables 設定 FUGLE_TOKEN=你的token

# 程式內用 os.getenv(“FUGLE_TOKEN”) 取用

# 絕對不要把 token 寫在程式碼裡

# 

# 4. 測試 API：

# 部署後開啟 https://你的網址/docs

# 即可看到自動產生的 Swagger 互動介面

# =============================================================
