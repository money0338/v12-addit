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
