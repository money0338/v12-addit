import os
from datetime import datetime
from typing import Tuple, List, Optional

import pandas as pd
import ta as ta_lib
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()


app.add_middleware(
CORSMiddleware,
allow_origins=（"*"),
allow_methods=[“GET”, “OPTIONS”],
allow_headers=[”*”],
)

def get_v12_score(info, rsi):
score = 0
details = []
warnings = []
eps_raw = info.get('trailingEps')
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

pb = info.get('priceToBook')
if pb is None:
    warnings.append("priceToBook missing")
elif 0 < pb < 2:
    score += 20
    details.append("P/B safe +20")
else:
    details.append("P/B high +0")

rev_growth = info.get('revenueGrowth')
if rev_growth is None:
    warnings.append("revenueGrowth missing")
elif rev_growth > 0.15:
    score += 25
    details.append("Revenue strong +25")
elif rev_growth > 0:
    score += 10
    details.append("Revenue mild +10")
else:
    details.append("Revenue decline +0")

margin = info.get('grossMargins')
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

if rsi is None:
    warnings.append("RSI unavailable")
elif rsi > 65:
    if eps is not None and eps <= 0:
        score -= 20
        details.append("WARNING: high RSI with loss -20")
    else:
        details.append("RSI hot, watch profit +0")
elif 50 < rsi <= 65:
    score += 40
    details.append("RSI healthy +40")
else:
    details.append("RSI weak +0")

return min(max(score, 0), 125), details, warnings
```

@app.get(”/audit/{symbol}”)
def run_v12_audit(symbol: str):
try:
ticker_str = symbol.upper() + “.TW”
stock = yf.Ticker(ticker_str)
hist = stock.history(period=“100d”)
except Exception as e:
raise HTTPException(status_code=500, detail=“yfinance error: “ + str(e))

```
if hist is None or hist.empty:
    raise HTTPException(status_code=404, detail="Symbol not found: " + symbol)

if len(hist) < 20:
    raise HTTPException(status_code=422, detail="Not enough data")

try:
    last_close = float(hist['Close'].iloc[-1])

    rsi_series = ta_lib.momentum.RSIIndicator(hist['Close'], window=14).rsi()
    rsi_val = rsi_series.iloc[-1]
    rsi = None if pd.isna(rsi_val) else round(float(rsi_val), 1)

    atr_series = ta_lib.volatility.AverageTrueRange(
        hist['High'], hist['Low'], hist['Close'], window=14
    ).average_true_range()
    atr_val = atr_series.iloc[-1]
    atr_estimated = pd.isna(atr_val)
    atr = last_close * 0.03 if atr_estimated else float(atr_val)

    info = stock.info
    if not info or (info.get('regularMarketPrice') is None and info.get('currentPrice') is None):
        raise HTTPException(status_code=404, detail="No info for " + symbol)

    final_score, audit_details, warnings = get_v12_score(info, rsi)

    s_coord = last_close - (atr * 1.5)
    w_coord = last_close + (atr * 2.0)
    book_value = info.get('bookValue')
    r_coord = float(book_value) if book_value else last_close * 0.6
    r_estimated = book_value is None

    return {
        "symbol": symbol.upper(),
        "timestamp": datetime.now().isoformat(),
        "data_source": "Yahoo Finance 15-20min delay",
        "p_now": round(last_close, 2),
        "rsi": rsi,
        "v12_score": final_score,
        "v12_score_display": str(final_score) + " / 125",
        "status": "OK" if final_score >= 85 else ("WATCH" if final_score >= 50 else "RISK"),
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
    raise HTTPException(status_code=500, detail="Engine error: " + str(e))
```






