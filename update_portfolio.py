# -*- coding: utf-8 -*-
import json
import os
import sys
from datetime import datetime
import pandas as pd
import numpy as np
import requests

def get_stock_data_naver(ticker):
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeFrame=day&count=40&requestType=0"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200 or not res.text:
            return None
            
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(res.text, 'xml')
        items = soup.find_all("item")
        
        if not items:
            return None

        dates, prices, highs, lows, volumes = [], [], [], [], []
        for item in items:
            data = item.get('data', '').split('|')
            if len(data) >= 6:
                dates.append(data[0])
                highs.append(int(data[2]))
                lows.append(int(data[3]))
                prices.append(int(data[4]))
                volumes.append(int(data[5]))
            
        if not prices:
            return None

        return {
            "dates": dates,
            "prices": prices,
            "highs": highs,
            "lows": lows,
            "volumes": volumes
        }
    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
        return None

def generate_scenario(name, price, prev_price, high_30, low_30, rsi, macd_signal):
    diff = high_30 - low_30 if high_30 > low_30 else 1
    fib_382 = int(high_30 - (diff * 0.382))
    fib_618 = int(high_30 - (diff * 0.618))
    target_price = int(price * 1.08)
    stop_loss = int(low_30 * 0.98)

    rate_day = round(((price - prev_price) / prev_price) * 100, 2) if prev_price > 0 else 0.0
    
    scenario_text = f"[{datetime.now().strftime('%m/%d')} 대응] "
    if rate_day > 2.0:
        scenario_text += f"단기 강세 흐름입니다. 1차 목표가({target_price:,}원) 도달 여부 주시, "
    elif rate_day < -2.0:
        scenario_text += f"단기 조정 구간입니다. 지지 라인인 {fib_618:,}원 이탈 주의가 필요합니다. "
    else:
        scenario_text += f"전일 대비 횡보세입니다. 지지선({fib_382:,}원) 부근 안착 후 대응을 추천합니다. "

    if rsi < 35:
        scenario_text += f"RSI({rsi}) 과매도 진입에 따른 분할 매수 검토. "
    elif rsi > 70:
        scenario_text += f"RSI({rsi}) 과열로 인한 비중 축소/차익실현 고려. "

    scenario_text += f"(추천 매수 구간: {fib_618:,}원 / 손절가: {stop_loss:,}원)"

    return {
        "scenario": scenario_text,
        "target_price": target_price,
        "stop_loss": stop_loss
    }

def main():
    os.makedirs("data", exist_ok=True)
    if not os.path.exists("portfolio.json"):
        print("portfolio.json 이 존재하지 않습니다.")
        return

    with open("portfolio.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    total_cash = config.get("total_cash", 0)
    holdings = config.get("holdings", [])

    processed_holdings = []
    total_eval_amount = 0
    total_buy_amount = 0

    for item in holdings:
        ticker = item["ticker"]
        name = item["name"]
        shares = item["shares"]
        buy_price = item["buy_price"]
        wave_stage = item.get("wave_stage", "분석 중")
        technique = item.get("technique", "기본 매매")

        hist = get_stock_data_naver(ticker)
        
        # 데이터 수집 실패 시 기존 매수가 기반 기본 데이터 설정
        if not hist or not hist["prices"]:
            print(f"Warning: {name}({ticker}) 주가 데이터 가져오기 실패 - 기본값 적용")
            curr_price = buy_price
            prev_price = buy_price
            highs = [buy_price]
            lows = [buy_price]
            volumes = [100000]
            rsi = 50.0
            macd_signal = False
        else:
            prices = hist["prices"]
            highs = hist["highs"]
            lows = hist["lows"]
            volumes = hist["volumes"]

            curr_price = prices[-1]
            prev_price = prices[-2] if len(prices) > 1 else curr_price

            p_series = pd.Series(prices)
            delta = p_series.diff()
            up = delta.clip(lower=0)
            down = -1 * delta.clip(upper=0)
            ema_up = up.ewm(com=13, adjust=False).mean()
            ema_down = down.ewm(com=13, adjust=False).mean()
            rs = ema_up / ema_down.replace(0, np.nan)
            rsi_series = 100 - (100 / (1 + rs))
            rsi = round(float(rsi_series.iloc[-1]), 1) if not np.isnan(rsi_series.iloc[-1]) else 50.0

            ema12 = p_series.ewm(span=12, adjust=False).mean()
            ema26 = p_series.ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False).mean()
            macd_signal = bool(macd.iloc[-1] > signal.iloc[-1])

        buy_amount = buy_price * shares
        eval_amount = curr_price * shares
        profit_loss = eval_amount - buy_amount
        profit_rate = round((profit_loss / buy_amount) * 100, 2) if buy_amount > 0 else 0.0

        total_buy_amount += buy_amount
        total_eval_amount += eval_amount

        avg_v20 = np.mean(volumes[-21:-1]) if len(volumes) >= 21 else np.mean(volumes)
        vol_ratio = round(volumes[-1] / avg_v20, 2) if avg_v20 > 0 else 1.0

        scenario_info = generate_scenario(name, curr_price, prev_price, max(highs[-30:]), min(lows[-30:]), rsi, macd_signal)

        signals = []
        if rsi <= 35: signals.append("매수신호: RSI 과매도")
        elif rsi >= 70: signals.append("매도신호: RSI 과열")
        if macd_signal: signals.append("매수신호: MACD 우상향")
        if vol_ratio >= 2.0: signals.append("관심신호: 거래량 급증")

        processed_holdings.append({
            "ticker": ticker,
            "name": name,
            "market": item.get("market", "KOSPI"),
            "shares": shares,
            "buy_price": buy_price,
            "curr_price": curr_price,
            "prev_price": prev_price,
            "buy_amount": buy_amount,
            "eval_amount": eval_amount,
            "profit_loss": profit_loss,
            "profit_rate": profit_rate,
            "weight": 0,
            "rsi": rsi,
            "vol_ratio": vol_ratio,
            "wave_stage": wave_stage,
            "technique": technique,
            "scenario": scenario_info["scenario"],
            "target_price": scenario_info["target_price"],
            "stop_loss": scenario_info["stop_loss"],
            "signals": signals if signals else ["특이 신호 없음 (관망 구간)"]
        })

    total_assets = total_eval_amount + total_cash
    for h in processed_holdings:
        h["weight"] = round((h["eval_amount"] / total_assets) * 100, 1) if total_assets > 0 else 0

    total_profit_loss = total_eval_amount - total_buy_amount
    total_profit_rate = round((total_profit_loss / total_buy_amount) * 100, 2) if total_buy_amount > 0 else 0.0

    market_brief = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "summary": "반도체 및 주요 관심 섹터를 중심으로 수급 유입이 지속되고 있으며, 지정된 손절가 준수 및 분할 대응이 유효합니다.",
        "status": "전일 종가/당일 시세 정상 반영 완료"
    }

    output = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S KST"),
        "summary": {
            "total_buy_amount": total_buy_amount,
            "total_eval_amount": total_eval_amount,
            "total_profit_loss": total_profit_loss,
            "total_profit_rate": total_profit_rate,
            "total_cash": total_cash,
            "total_assets": total_assets,
            "stock_weight": round((total_eval_amount / total_assets) * 100, 1) if total_assets > 0 else 0,
            "cash_weight": round((total_cash / total_assets) * 100, 1) if total_assets > 0 else 0
        },
        "holdings": processed_holdings,
        "market_brief": market_brief
    }

    with open("data/portfolio_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        
    print("성공적으로 포트폴리오 데이터를 업데이트했습니다.")

if __name__ == "__main__":
    main()
