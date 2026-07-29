# -*- coding: utf-8 -*-
import json
import os
import sys
from datetime import datetime
import pandas as pd
import numpy as np
import requests

def get_stock_data_naver(ticker):
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeFrame=day&count=60&requestType=0"
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

def analyze_chart_technical(prices, highs, lows, volumes, rsi, macd_diff, vol_ratio):
    """
    일봉 차트 데이터를 기반으로 파동 위치 및 적용 매매기법 자동 진단
    """
    curr_price = prices[-1]
    high_30 = max(highs[-30:])
    low_30 = min(lows[-30:])
    
    # 이동평균선 계산
    ma5 = np.mean(prices[-5:]) if len(prices) >= 5 else curr_price
    ma20 = np.mean(prices[-20:]) if len(prices) >= 20 else curr_price
    ma60 = np.mean(prices[-60:]) if len(prices) >= 60 else curr_price

    technique = "눌림목 매매"
    wave_stage = "파동 분석 중"

    # 1. 공구리 돌파 및 눌림목 판단 (20일 박스권 상단 근처 및 20일선 지지)
    box_top = max(highs[-20:-5]) if len(highs) >= 20 else high_30
    if curr_price >= box_top * 0.97 and curr_price >= ma20:
        technique = "공구리 돌파 및 눌림목"
        wave_stage = "공구리(박스권) 상단 돌파 후 지지 확인 구간"
    # 2. 역매공파 (역배열 매집 완료 후 골파기 탈출)
    elif ma20 < ma60 and curr_price > ma20 and vol_ratio >= 1.5:
        technique = "역매공파 (역배열 수급 유입)"
        wave_stage = "역배열 하단 매집 완료 / 1차 분할 매수 타점"
    # 3. 밥그릇 파동 판단
    elif curr_price > ma20 and ma20 > ma60:
        technique = "밥그릇 3파 (주세 분출)"
        wave_stage = "밥그릇 3파 진행 중 (우상향 상승 파동)"
    elif curr_price <= ma20 and curr_price > low_30 * 1.05:
        technique = "밥그릇 2파 (골파기 지지)"
        wave_stage = "밥그릇 2파 지지 구간 (박스권 하단 매수)"
    else:
        technique = "피보나치 조정대 매매"
        wave_stage = "단기 조정 / 지지선 추적 구간"

    # 피보나치 지지/저항 라인 산출
    diff = high_30 - low_30 if high_30 > low_30 else 1
    fib_382 = int(high_30 - (diff * 0.382))
    fib_618 = int(high_30 - (diff * 0.618))
    target_price = int(high_30 * 1.05) if curr_price >= high_30 * 0.95 else int(curr_price * 1.08)
    stop_loss = int(low_30 * 0.97)

    # 시나리오 문장 생성
    scenario_text = f"[{datetime.now().strftime('%m/%d')} 차트 진단] "
    scenario_text += f"현재 {technique} 패턴으로 판단됩니다. "
    scenario_text += f"주요 지지선은 {fib_618:,}원이며, 손절가({stop_loss:,}원) 이탈 전까지 홀딩 유효합니다. "
    
    if rsi < 35:
        scenario_text += f"RSI({rsi}) 과매도 구간으로 기술적 반등 타점입니다. "
    elif rsi > 70:
        scenario_text += f"RSI({rsi}) 과열권으로 분할 익절 대응 권장합니다. "

    return {
        "technique": technique,
        "wave_stage": wave_stage,
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

    total_cash = config.get("total_cash", 10000000)
    holdings = config.get("holdings", [])

    processed_holdings = []
    total_eval_amount = 0
    total_buy_amount = 0

    for item in holdings:
        ticker = item["ticker"]
        name = item["name"]
        shares = item["shares"]
        buy_price = item["buy_price"]

        hist = get_stock_data_naver(ticker)
        
        if not hist or not hist["prices"]:
            print(f"Warning: {name}({ticker}) 주가 데이터 수집 실패 - 기본값 반영")
            curr_price = buy_price
            prev_price = buy_price
            highs = [buy_price]
            lows = [buy_price]
            volumes = [100000]
            rsi = 50.0
            vol_ratio = 1.0
            macd_diff = 0
        else:
            prices = hist["prices"]
            highs = hist["highs"]
            lows = hist["lows"]
            volumes = hist["volumes"]

            curr_price = prices[-1]
            prev_price = prices[-2] if len(prices) > 1 else curr_price

            # RSI 계산
            p_series = pd.Series(prices)
            delta = p_series.diff()
            up = delta.clip(lower=0)
            down = -1 * delta.clip(upper=0)
            ema_up = up.ewm(com=13, adjust=False).mean()
            ema_down = down.ewm(com=13, adjust=False).mean()
            rs = ema_up / ema_down.replace(0, np.nan)
            rsi_series = 100 - (100 / (1 + rs))
            rsi = round(float(rsi_series.iloc[-1]), 1) if not np.isnan(rsi_series.iloc[-1]) else 50.0

            # MACD 계산
            ema12 = p_series.ewm(span=12, adjust=False).mean()
            ema26 = p_series.ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False).mean()
            macd_diff = macd.iloc[-1] - signal.iloc[-1]

            # 거래량 비율 계산
            avg_v20 = np.mean(volumes[-21:-1]) if len(volumes) >= 21 else np.mean(volumes)
            vol_ratio = round(volumes[-1] / avg_v20, 2) if avg_v20 > 0 else 1.0

        buy_amount = buy_price * shares
        eval_amount = curr_price * shares
        profit_loss = eval_amount - buy_amount
        profit_rate = round((profit_loss / buy_amount) * 100, 2) if buy_amount > 0 else 0.0

        total_buy_amount += buy_amount
        total_eval_amount += eval_amount

        # 차트 분석 엔진으로 자동 진단
        tech_analysis = analyze_chart_technical(prices if hist else [buy_price], highs if hist else [buy_price], lows if hist else [buy_price], volumes if hist else [1000], rsi, macd_diff, vol_ratio)

        signals = []
        if rsi <= 35: signals.append("매수신호: RSI 과매도 구간")
        elif rsi >= 70: signals.append("매도신호: RSI 과열 구간")
        if macd_diff > 0: signals.append("매수신호: MACD 우상향")
        if vol_ratio >= 2.0: signals.append("관심신호: 평소 대비 거래량 200% 이상 급증")

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
            "wave_stage": tech_analysis["wave_stage"],
            "technique": tech_analysis["technique"],
            "scenario": tech_analysis["scenario"],
            "target_price": tech_analysis["target_price"],
            "stop_loss": tech_analysis["stop_loss"],
            "signals": signals if signals else ["특이 신호 없음 (관망 및 보유 유지)"]
        })

    total_assets = total_eval_amount + total_cash
    for h in processed_holdings:
        h["weight"] = round((h["eval_amount"] / total_assets) * 100, 1) if total_assets > 0 else 0

    total_profit_loss = total_eval_amount - total_buy_amount
    total_profit_rate = round((total_profit_loss / total_buy_amount) * 100, 2) if total_buy_amount > 0 else 0.0

    market_brief = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "summary": "핵심 주력 섹터(반도체/AI/우주)를 중심으로 실시간 차트 수급을 분석하여 매매 시나리오를 산출합니다.",
        "status": "전일 종가/당일 시세 및 차트 패턴 진단 완료"
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
        
    print("성공적으로 포트폴리오 차트 데이터 및 진단을 완료했습니다.")

if __name__ == "__main__":
    main()
