from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/audit/{symbol}")
def audit(symbol: str):
    stock = yf.Ticker(symbol + ".TW")
    hist = stock.history(period="30d")
    if hist.empty:
        return {"error": "not found"}
    price = round(float(hist["Close"].iloc[-1]), 2)
    return {"symbol": symbol, "price": price}
import os
from datetime import datetime
from typing import Optional

import pandas as pd
import ta as ta_lib
import yfinance as yf
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
CORSMiddleware,
allow_origins=[”*”],
allow_methods=[“GET”, “OPTIONS”],
allow_headers=[”*”],
)

def get_twse_price(symbol: str) -> Optional[float]:
“””
從台灣證交所抓取當日最新收盤價（免費，無需 Token）
“””
try:
url = f”https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{symbol}.tw”
res = requests.get(url, timeout=5)
data = res.json()
price = data[“msgArray”][0].get(“z”) or data[“msgArray”][0].get(“y”)
if price and price != “-”:
return round(float(price), 2)
except Exception:
pass
return None

def get_v12_score(info: dict, rsi: Optional[float]):
score = 0
details = []
warnings = []

```
# A. EPS
eps_raw = info.get("trailingEps")
if eps_raw is None:
    warnings.append("trailingEps missing")
    eps = None
else:
    eps = eps_raw
    if eps > 0:
        score += 20
        details.append("EPS profit +20")
    else:
        details.append("EPS loss +0")

# B. P/B
pb = info.get("priceToBook")
if pb is None:
    warnings.append("priceToBook missing")
elif 0 < pb < 2:
    score += 20
    details.append("PB safe +20")
else:
    details.append("PB high +0")

# C. Revenue Growth
rev = info.get("revenueGrowth")
if rev is None:
    warnings.append("revenueGrowth missing")
elif rev > 0.15:
    score += 25
    details.append("Revenue strong +25")
elif rev > 0:
    score += 10
    details.append("Revenue mild +10")
else:
    details.append("Revenue decline +0")

# D. Gross Margin
margin = info.get("grossMargins")
if margin is None:
    warnings.append("grossMargins missing")
elif margin > 0.3:
    score += 20
    details.append("Margin good +20")
elif margin > 0.1:
    score += 10
    details.append("Margin ok +10")
else:
    details.append("Margin low +0")

# E. RSI
if rsi is None:
    warnings.append("RSI unavailable")
elif rsi > 65:
    if eps is not None and eps <= 0:
        score -= 20
        details.append("WARNING high RSI with loss -20")
    else:
        details.append("RSI hot watch +0")
elif 50 < rsi <= 65:
    score += 40
    details.append("RSI healthy +40")
else:
    details.append("RSI weak +0")

return min(max(score, 0), 125), details, warnings
```

@app.get(”/audit/{symbol}”)
def run_audit(symbol: str):
try:
stock = yf.Ticker(symbol.upper() + “.TW”)
hist = stock.history(period=“100d”)
except Exception as e:
raise HTTPException(status_code=500, detail=“yfinance error: “ + str(e))

```
if hist is None or hist.empty:
    raise HTTPException(status_code=404, detail="Symbol not found: " + symbol)

if len(hist) < 20:
    raise HTTPException(status_code=422, detail="Not enough data")

try:
    yf_price = round(float(hist["Close"].iloc[-1]), 2)

    # 嘗試用 TWSE 取得更即時的價格
    twse_price = get_twse_price(symbol.upper())
    p_now = twse_price if twse_price else yf_price
    data_source = "TWSE (realtime)" if twse_price else "Yahoo Finance (15-20min delay)"

    # RSI
    rsi_val = ta_lib.momentum.RSIIndicator(hist["Close"], window=14).rsi().iloc[-1]
    rsi = None if pd.isna(rsi_val) else round(float(rsi_val), 1)

    # ATR
    atr_val = ta_lib.volatility.AverageTrueRange(
        hist["High"], hist["Low"], hist["Close"], window=14
    ).average_true_range().iloc[-1]
    atr_estimated = pd.isna(atr_val)
    atr = yf_price * 0.03 if atr_estimated else float(atr_val)

    info = stock.info
    if not info or (info.get("regularMarketPrice") is None and info.get("currentPrice") is None):
        raise HTTPException(status_code=404, detail="No info for " + symbol)

    score, audit_details, warnings = get_v12_score(info, rsi)

    s_coord = p_now - (atr * 1.5)
    w_coord = p_now + (atr * 2.0)
    book_value = info.get("bookValue")
    r_coord = float(book_value) if book_value else p_now * 0.6
    r_estimated = book_value is None

    return {
        "symbol": symbol.upper(),
        "timestamp": datetime.now().isoformat(),
        "data_source": data_source,
        "p_now": p_now,
        "rsi": rsi,
        "v12_score": score,
        "v12_score_display": str(score) + " / 125",
        "status": "OK" if score >= 85 else ("WATCH" if score >= 50 else "RISK"),
        "coordinates": {
            "W_resistance": round(w_coord, 2),
            "P_equilibrium": round(p_now, 2),
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
    raise HTTPException(status_code=500, detail="Engine error: " + str(e))
    
```
