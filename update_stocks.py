# -*- coding: utf-8 -*-
"""
update_stocks.py  (v2 — GitHub 캐시 기반, KRX 직접 접속 없음)
================================================================
[이전 버전과의 가장 큰 차이점]
이전 버전은 pykrx로 KRX 서버에 종목당 1번씩(약 2,500번) 직접 접속했다.
그런데 GitHub Actions 서버(해외 IP)에서 KRX가 요청을 계속 빈 응답으로 막아서 실패했다.

이번 버전은 KRX에 전혀 접속하지 않는다. 대신 FinanceDataReader 프로젝트가
매일 자동으로 KRX 전종목 시세를 캐싱해서 올려주는 공개 GitHub 저장소
(FinanceData/fdr_krx_data_cache)에서 날짜별 CSV를 그대로 받아온다.
GitHub -> GitHub 요청이라 GitHub Actions 환경에서 막힐 걱정이 없고,
하루치 파일 하나에 전종목이 다 들어있어서 종목별로 개별 요청할 필요도 없다
(약 2,500번 요청 -> 약 130번 요청으로 감소, 실행 시간도 크게 단축).

전체 흐름
---------
1. 최근 LOOKBACK_DAYS 만큼의 날짜별 스냅샷 CSV를 GitHub에서 받아온다.
2. 주말/공휴일에는 직전 거래일 데이터가 그대로 이월되어 있으므로, 연속된
   날짜의 종가/거래량이 완전히 동일하면 "새 거래일이 아니다"로 보고 제거한다.
3. 종목(Code)별로 시계열을 만들어 기술적 신호 5가지를 계산한다.
4. 신호가 1개 이상 감지된 종목만 data/signals.json에 저장한다.
5. 그 종목들은 상세 차트 페이지에서 쓸 수 있도록 최근 시세 이력을
   data/history/{티커}.json 으로 별도 저장한다.
"""

import io
import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

# ----------------------------------------------------------------------------
# 설정값
# ----------------------------------------------------------------------------
CACHE_BASE_URL = "https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/refs/heads/master/data/listing/krx"

LOOKBACK_DAYS = 400          # 과거 몇 "달력일"치를 가져올지 (MA224 대비 넉넉하게. 캐시 시작점 이전은 자동으로 조기 중단됨)
VOLUME_SURGE_RATIO = 2.0     # 거래량 급증 판단 배수
ZIGZAG_THRESHOLD = 0.08      # ZigZag 스윙 판정 임계값
FIB_TOLERANCE = 0.02         # 피보나치 레벨 근접 판단 비율
MIN_SCORE_TO_INCLUDE = 2     # 이 점수 이상인 종목만 "신호 발견 목록"에 포함 (1이면 너무 많아서 노이즈가 큼)
WATCHLIST_TOP_N = 150        # 시장별(KOSPI/KOSDAQ) 시가총액 상위 몇 개까지 "신호 없어도 항상 조회 가능"하게 할지
HISTORY_DAYS_TO_SAVE = 90    # 상세 차트용으로 저장할 최근 거래일 수
REQUEST_TIMEOUT = 15

# ----------------------------------------------------------------------------
# DART(전자공시시스템) 연동 - 선택 사항
# ----------------------------------------------------------------------------
# opendart.fss.or.kr 에서 무료로 발급받은 API 키를 GitHub 저장소의
# Settings > Secrets and variables > Actions 에 "DART_API_KEY"라는 이름으로 등록하면
# 자동으로 최근 공시 목록을 함께 가져온다. 키가 없으면 이 기능은 조용히 건너뛴다.
DART_API_KEY = os.environ.get("DART_API_KEY", "").strip()
DART_DISCLOSURE_LOOKBACK_DAYS = 90
DART_MAX_ITEMS = 5


def fetch_daily_snapshot(date_obj):
    """
    특정 날짜(datetime)의 전종목 시세 캐시 CSV를 받아온다.
    해당 날짜 파일이 없으면(캐시 저장소 시작 이전 등) None을 반환한다.
    """
    date_str = date_obj.strftime("%Y-%m-%d")
    url = f"{CACHE_BASE_URL}/{date_str}.csv"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None
        df = pd.read_csv(io.StringIO(resp.text), index_col=0, dtype={"Code": str})
        df["Date"] = date_str
        return df[["Date", "Code", "Name", "Market", "Open", "High", "Low", "Close", "Volume", "Marcap"]]
    except Exception as e:
        print(f"  [경고] {date_str} 스냅샷 로드 실패: {e}", file=sys.stderr)
        return None


def build_panel():
    """
    최근 LOOKBACK_DAYS 만큼의 날짜별 스냅샷을 모두 받아서 하나의 DataFrame으로 합친다.
    그다음 주말/공휴일 이월 데이터(직전 거래일과 완전히 동일한 행)를 제거한다.

    LOOKBACK_DAYS는 넉넉하게(MA224까지 대비) 잡혀있지만, GitHub 캐시 저장소 자체가
    시작된 시점보다 과거로 가면 계속 404만 나오므로, 연속으로 CONSECUTIVE_MISS_LIMIT일치
    실패하면 "캐시 시작점을 넘어갔다"고 보고 더 이상 요청하지 않고 멈춘다 (실행시간 절약).
    """
    today = datetime.today()
    frames = []
    consecutive_misses = 0
    CONSECUTIVE_MISS_LIMIT = 15

    for days_back in range(LOOKBACK_DAYS):
        date_obj = today - timedelta(days=days_back)
        df = fetch_daily_snapshot(date_obj)
        if df is not None:
            frames.append(df)
            consecutive_misses = 0
        else:
            consecutive_misses += 1
            if consecutive_misses >= CONSECUTIVE_MISS_LIMIT:
                print(f"[{datetime.now()}] {CONSECUTIVE_MISS_LIMIT}일 연속 데이터 없음 "
                      f"-> 캐시 저장소 시작점을 넘어간 것으로 보고 수집을 중단합니다 "
                      f"({days_back + 1}일째, {date_obj.strftime('%Y-%m-%d')})")
                break

        if (days_back + 1) % 20 == 0:
            print(f"[{datetime.now()}] 스냅샷 수집 진행: {days_back + 1}/{LOOKBACK_DAYS}일")

    if not frames:
        raise RuntimeError("스냅샷을 하나도 받아오지 못했습니다. GitHub 캐시 저장소 상태를 확인해주세요.")

    panel = pd.concat(frames, ignore_index=True)
    panel = panel[panel["Market"].isin(["KOSPI", "KOSDAQ"])].copy()
    panel = panel.sort_values(["Code", "Date"]).reset_index(drop=True)

    # 주말/공휴일 이월 제거: 직전 날짜와 종가/거래량이 완전히 같으면 "새 거래가 없었다"고 보고 삭제
    is_duplicate = (
        panel.groupby("Code")[["Close", "Volume"]].shift() == panel[["Close", "Volume"]]
    ).all(axis=1)
    panel = panel[~is_duplicate].reset_index(drop=True)

    trading_days = panel.groupby("Code").size().max() if len(panel) else 0
    print(f"[{datetime.now()}] 패널 데이터 구성 완료: 종목 {panel['Code'].nunique()}개, "
          f"총 {len(panel)}행 (중복 이월 제거 후), 종목당 최대 거래일수 약 {trading_days}일")
    return panel


def load_custom_watchlist():
    """
    watchlist.txt에 사용자가 직접 적어둔 종목 코드를 읽어온다.
    시가총액 순위와 무관하게 이 종목들은 항상 조회 가능 목록에 포함된다
    (중소형주 등 시총 상위 300에 안 들어가는 보유/관심 종목을 위한 것).
    파일이 없으면 조용히 빈 세트를 반환한다.
    """
    path = "watchlist.txt"
    if not os.path.exists(path):
        return set()

    codes = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()  # '#'는 주석
            if not line:
                continue
            code = line.zfill(6) if line.isdigit() else line  # "5930" -> "005930" 자동 보정
            codes.add(code)

    if codes:
        print(f"[{datetime.now()}] 커스텀 워치리스트(watchlist.txt) {len(codes)}개 종목 추가 반영")
    return codes


def get_watchlist_codes(panel: pd.DataFrame, top_n=WATCHLIST_TOP_N):
    """
    시장(KOSPI/KOSDAQ)별로 '가장 최근 날짜' 기준 시가총액 상위 top_n 종목 코드를 뽑는다.
    이 종목들은 매수신호가 하나도 없어도(score=0) 상세페이지에서 항상 조회 가능하게 만든다
    (배찌님이 보유/관심 있는 대형주는 신호가 없을 때도 확인하고 싶을 수 있으니까).

    여기에 watchlist.txt로 직접 지정한 종목(시총 순위 무관)도 합쳐진다.
    """
    latest_date = panel["Date"].max()
    latest = panel[panel["Date"] == latest_date]

    watchlist = set()
    for market in ["KOSPI", "KOSDAQ"]:
        top = (
            latest[latest["Market"] == market]
            .sort_values("Marcap", ascending=False)
            .head(top_n)["Code"]
            .tolist()
        )
        watchlist.update(top)

    market_cap_count = len(watchlist)
    watchlist.update(load_custom_watchlist())

    print(f"[{datetime.now()}] 워치리스트(시가총액 상위) 구성: {market_cap_count}개 종목 "
          f"(KOSPI/KOSDAQ 각 상위 {top_n}) + 커스텀 지정 포함 총 {len(watchlist)}개")
    return watchlist


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """일반적인 RSI(Wilder 방식) 계산."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    """MACD선, 시그널선을 계산해서 (macd, signal_line) 튜플로 반환."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def zigzag_pivots(close: pd.Series, threshold=ZIGZAG_THRESHOLD):
    """
    종가 시리즈에서 ZigZag 피벗(스윙 고점/저점)을 추출한다.
    반환값: [(index_position, price, 'high' or 'low'), ...] 리스트 (시간순)
    """
    prices = close.values
    n = len(prices)
    if n < 5:
        return []

    pivots = []
    trend = None
    last_pivot_idx = 0
    last_pivot_price = prices[0]

    for i in range(1, n):
        change = (prices[i] - last_pivot_price) / last_pivot_price

        if trend is None:
            if change >= threshold:
                trend = "up"
                last_pivot_price = prices[i]
                last_pivot_idx = i
            elif change <= -threshold:
                trend = "down"
                last_pivot_price = prices[i]
                last_pivot_idx = i
        elif trend == "up":
            if prices[i] >= last_pivot_price:
                last_pivot_price = prices[i]
                last_pivot_idx = i
            elif (prices[i] - last_pivot_price) / last_pivot_price <= -threshold:
                pivots.append((last_pivot_idx, last_pivot_price, "high"))
                trend = "down"
                last_pivot_price = prices[i]
                last_pivot_idx = i
        elif trend == "down":
            if prices[i] <= last_pivot_price:
                last_pivot_price = prices[i]
                last_pivot_idx = i
            elif (prices[i] - last_pivot_price) / last_pivot_price >= threshold:
                pivots.append((last_pivot_idx, last_pivot_price, "low"))
                trend = "up"
                last_pivot_price = prices[i]
                last_pivot_idx = i

    if trend is not None:
        pivots.append((last_pivot_idx, last_pivot_price, "high" if trend == "up" else "low"))

    return pivots


def fibonacci_levels(low: float, high: float) -> dict:
    diff = high - low
    return {
        "23.6%": high - diff * 0.236,
        "38.2%": high - diff * 0.382,
        "50.0%": high - diff * 0.5,
        "61.8%": high - diff * 0.618,
        "78.6%": high - diff * 0.786,
    }


def check_fibonacci_support(close: pd.Series):
    pivots = zigzag_pivots(close)
    if len(pivots) < 2:
        return None

    (_, price_a, type_a), (_, price_b, type_b) = pivots[-2], pivots[-1]
    if type_a == type_b:
        return None

    low = min(price_a, price_b)
    high = max(price_a, price_b)
    if high == low:
        return None

    levels = fibonacci_levels(low, high)
    current_price = close.iloc[-1]

    for level_name, level_price in levels.items():
        if level_price == 0:
            continue
        if abs(current_price - level_price) / level_price <= FIB_TOLERANCE:
            return level_name

    return None


# 파동위치·매수타점 계산 기준 (프론트에도 그대로 노출해서 사용자가 근거를 알 수 있게 함)
WAVE_BASIS_NOTE = (
    "일봉(종가) 기준 · ZigZag 8% 스윙 전환점으로 구간을 나눈 단순화된 파동 카운트입니다. "
    "정통 엘리어트파동 이론의 세부 규칙(파동 간 피보나치 비율, 3파 최단파동 금지 등)까지 "
    "전부 검증한 것은 아니며, 참고용 스윙 위치 표시로만 활용해주세요."
)


def analyze_wave_and_levels(close: pd.Series):
    """
    ZigZag 피벗을 기반으로 (1) 지금이 몇 번째 스윙(파동)인지,
    (2) 상승파동이 어디까지 진행됐는지, (3) 매수타점/목표가/손절가를 계산한다.

    - 매수타점: 현재 상승 구간의 38.2% 되돌림 지점 (조정 시 매수 관점)
    - 목표가: 직전 하락폭 대비 1.272배 확장 지점 (일반적인 파동 확장 비율)
    - 손절가: 이번 상승의 시작점(직전 스윙 저점) 대비 2% 아래 (그 아래로 깨지면 상승 근거 무효화로 판단)
    """
    pivots = zigzag_pivots(close)
    if len(pivots) < 3:
        return None

    prev_swing, last_swing, current = pivots[-3], pivots[-2], pivots[-1]
    wave_count = len(pivots) - 1  # 확정된 스윙 개수 (진행중인 마지막 구간 제외)
    wave_number = ((wave_count - 1) % 5) + 1  # 5파 주기로 순환 라벨링 (단순화)
    direction = "상승" if current[2] == "high" else "하락"
    current_price = float(close.iloc[-1])

    prior_leg_size = abs(last_swing[1] - prev_swing[1])
    progress_pct = None
    if prior_leg_size > 0:
        progress_pct = round(abs(current_price - last_swing[1]) / prior_leg_size * 100, 1)

    result = {
        "wave_direction": direction,
        "wave_number": wave_number,
        "wave_progress_pct": progress_pct,
        "buy_point": None,
        "buy_point_2": None,
        "target_price": None,
        "target_price_2": None,
        "stop_loss": None,
    }

    if direction == "상승":
        swing_low = last_swing[1]
        # 1차: 38.2% 되돌림(얕은 눌림) / 2차: 61.8% 되돌림(깊은 눌림, 더 싸게 사고 싶을 때)
        result["buy_point"] = int(current_price - (current_price - swing_low) * 0.382)
        result["buy_point_2"] = int(current_price - (current_price - swing_low) * 0.618)
        # 1차 목표(매도): 직전 스윙고점(보수적) / 2차 목표: 1.272배 확장(공격적)
        result["target_price"] = int(current_price)  # 진행중 스윙의 현재 고점 = 1차 목표(근접)
        result["target_price_2"] = int(swing_low + prior_leg_size * 1.272)
        result["stop_loss"] = int(swing_low * 0.98)
    else:
        # 하락 파동이 진행 중일 때는 신규 매수 구간이 아니므로 손절가(참고용)만 제시
        result["stop_loss"] = int(current_price * 0.95)

    return result


# ----------------------------------------------------------------------------
# 차트 패턴 체크리스트 (밥그릇 / 공구리 / 눌림목)
# ----------------------------------------------------------------------------
# ⚠️ 이 세 가지는 정성적인 차트 패턴을 숫자 규칙으로 근사한 것입니다.
# 실제로 차트를 눈으로 보는 것과 100% 같은 결과가 아닐 수 있으니 참고용으로만 활용하세요.

PATTERN_BASIS_NOTE = (
    "눌림목: 20일선 상승중 + 60일선 위 유지 + 최근 20일 고점 대비 4~15% 하락. "
    "공구리(횡보다지기): 최근 15거래일 고가·저가 폭이 평균가 대비 8% 이내. "
    "밥그릇(라운딩바텀): 최근 50거래일 중 저점이 구간 중간 70% 안에 위치 + 고점 대비 10% 이상 하락 후 재상승 "
    "(1~4파는 저점 대비 회복 정도로 단순화해서 구분). 정성적 패턴의 숫자 근사치이며 참고용입니다."
)


def detect_pullback(close: pd.Series, ma20: pd.Series, ma60: pd.Series):
    """눌림목: 상승추세(20일선 상승중, 60일선 위) 유지한 채 최근 고점 대비 4~15% 조정."""
    if len(close) < 25 or pd.isna(ma20.iloc[-1]) or pd.isna(ma20.iloc[-10]) or pd.isna(ma60.iloc[-1]):
        return False
    if not (ma20.iloc[-1] > ma20.iloc[-10]):
        return False
    if close.iloc[-1] < ma60.iloc[-1]:
        return False
    recent_high = close.iloc[-20:].max()
    pullback_pct = (recent_high - close.iloc[-1]) / recent_high * 100
    return 4 <= pullback_pct <= 15


def detect_consolidation(close: pd.Series, window=15, threshold=0.08):
    """공구리(횡보다지기): 최근 window거래일간 가격 변동폭이 평균가 대비 threshold 이내."""
    if len(close) < window:
        return False
    recent = close.iloc[-window:]
    range_pct = (recent.max() - recent.min()) / recent.mean()
    return range_pct <= threshold


def detect_cup_pattern(close: pd.Series, window=50):
    """
    밥그릇(라운딩바텀): window 구간 안에서 저점이 중간 70% 지점에 위치하고,
    고점 대비 10% 이상 하락했다가 다시 회복 중인지 확인한다.
    반환값: None(해당없음) 또는 1~4 (진행 단계, 저점 대비 회복 정도로 단순화)
    """
    if len(close) < window:
        return None

    recent = close.iloc[-window:].reset_index(drop=True)
    min_idx = int(recent.idxmin())
    min_price = float(recent.iloc[min_idx])
    start_price = float(recent.iloc[0])
    current_price = float(recent.iloc[-1])

    if not (window * 0.15 <= min_idx <= window * 0.85):
        return None
    if start_price == 0 or (start_price - min_price) / start_price < 0.10:
        return None

    if min_idx >= window * 0.7 and current_price <= min_price * 1.03:
        return 1  # 아직 저점 형성/하락 진행형
    if current_price <= min_price * 1.05:
        return 2  # 바닥 다지기
    if current_price < start_price:
        return 3  # 회복 중
    return 4  # 시작가(직전 고점권) 회복/돌파


def compute_chart_patterns(close: pd.Series, ma20: pd.Series, ma60: pd.Series):
    """세 가지 패턴을 한번에 체크해서 감지된 것만 리스트로 반환."""
    patterns = []

    if detect_pullback(close, ma20, ma60):
        patterns.append({"name": "눌림목", "detail": "상승추세 중 조정 구간"})

    if detect_consolidation(close):
        patterns.append({"name": "공구리", "detail": "횡보 다지기 구간"})

    cup_stage = detect_cup_pattern(close)
    if cup_stage:
        patterns.append({"name": "밥그릇", "detail": f"{cup_stage}파 (라운딩바텀 진행단계)"})

    return patterns


def compute_rating(score: int, wave_direction, rsi):
    """
    감지된 신호 개수·파동 방향·RSI를 조합한 참고용 '매수 적합도' 별점(1~5)과 라벨을 계산한다.
    ※ 별도의 추가 정보가 아니라, 이미 계산된 신호들을 보기 쉽게 종합한 것일 뿐입니다.

    - 신호 1개당 +1점 (최대 3점)
    - 상승 파동 진행 중이면 +1점 / 하락 파동 진행 중이면 -1점
    - RSI 70 이상(과매수 구간)이면 이미 많이 올라서 신규 진입 매력이 낮다고 보고 -1점
    """
    stars = min(score, 3)

    if wave_direction == "상승":
        stars += 1
    elif wave_direction == "하락":
        stars -= 1

    if rsi is not None and rsi >= 70:
        stars -= 1

    stars = max(1, min(5, stars))

    if stars >= 4:
        label = "매수 적합"
    elif stars == 3:
        label = "관심 필요"
    else:
        label = "관망"

    return stars, label


def compute_signal_markers(dates, ma5, ma20, ma60, rsi, macd_line, signal_line):
    """
    전체 구간에서 매수/매도 신호가 실제로 '발생한 날'들을 찾아 차트 마커 리스트로 반환한다.
    (지금 시점의 신호가 아니라, 과거에 이 신호들이 어디서 떴었는지를 공부용으로 보여주기 위함)

    - 매수: 정배열전환, RSI과매도탈출(30 상향돌파), MACD골든크로스
    - 매도: 역배열전환, RSI과매수진입(70 상향돌파), MACD데드크로스
    """
    markers = []
    n = len(dates)

    aligned_up = (ma5 > ma20) & (ma20 > ma60)
    aligned_down = (ma5 < ma20) & (ma20 < ma60)

    for i in range(1, n):
        date = dates[i]

        if bool(aligned_up.iloc[i]) and not bool(aligned_up.iloc[i - 1]):
            markers.append({"date": date, "type": "buy", "label": "정배열전환"})
        if bool(aligned_down.iloc[i]) and not bool(aligned_down.iloc[i - 1]):
            markers.append({"date": date, "type": "sell", "label": "역배열전환"})

        if pd.notna(rsi.iloc[i]) and pd.notna(rsi.iloc[i - 1]):
            if rsi.iloc[i - 1] <= 30 < rsi.iloc[i]:
                markers.append({"date": date, "type": "buy", "label": "RSI과매도탈출"})
            if rsi.iloc[i - 1] < 70 <= rsi.iloc[i]:
                markers.append({"date": date, "type": "sell", "label": "RSI과매수진입"})

        if macd_line.iloc[i - 1] < signal_line.iloc[i - 1] and macd_line.iloc[i] > signal_line.iloc[i]:
            markers.append({"date": date, "type": "buy", "label": "MACD골든크로스"})
        if macd_line.iloc[i - 1] > signal_line.iloc[i - 1] and macd_line.iloc[i] < signal_line.iloc[i]:
            markers.append({"date": date, "type": "sell", "label": "MACD데드크로스"})

    return markers


def analyze_stock(group: pd.DataFrame):
    """
    종목 하나의 시계열(Date순 정렬된 DataFrame)을 받아서 신호 리스트와 부가정보를 계산한다.
    데이터가 부족하면 None 반환.
    """
    if len(group) < 65:  # MA60 계산에 최소 65개 거래일 필요
        return None

    close = group["Close"].reset_index(drop=True)
    volume = group["Volume"].reset_index(drop=True)
    dates = group["Date"].reset_index(drop=True)

    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    ma112 = close.rolling(112).mean()   # 데이터가 112거래일 이상 쌓이기 전까지는 전부 NaN (정상)
    ma224 = close.rolling(224).mean()   # 데이터가 224거래일 이상 쌓이기 전까지는 전부 NaN (정상)

    rsi = calc_rsi(close)
    macd_line, signal_line = calc_macd(close)
    signal_markers = compute_signal_markers(dates, ma5, ma20, ma60, rsi, macd_line, signal_line)

    signals = []

    if ma5.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1]:
        signals.append("정배열")

    if pd.notna(rsi.iloc[-2]) and pd.notna(rsi.iloc[-1]):
        if rsi.iloc[-2] <= 30 and rsi.iloc[-1] > 30:
            signals.append("RSI과매도탈출")

    if (macd_line.iloc[-2] < signal_line.iloc[-2]) and (macd_line.iloc[-1] > signal_line.iloc[-1]):
        signals.append("MACD골든크로스")

    avg_volume_20 = volume.iloc[-21:-1].mean()
    if avg_volume_20 > 0 and volume.iloc[-1] >= avg_volume_20 * VOLUME_SURGE_RATIO:
        signals.append("거래량급증")

    fib_hit = check_fibonacci_support(close)
    if fib_hit:
        signals.append(f"피보나치{fib_hit}지지")

    prev_close = close.iloc[-2]
    change_rate = ((close.iloc[-1] - prev_close) / prev_close * 100) if prev_close else None

    wave_info = analyze_wave_and_levels(close) or {}
    rsi_now = round(float(rsi.iloc[-1]), 1) if pd.notna(rsi.iloc[-1]) else None
    rating_stars, rating_label = compute_rating(len(signals), wave_info.get("wave_direction"), rsi_now)
    chart_patterns = compute_chart_patterns(close, ma20, ma60)

    return {
        "signals": signals,
        "score": len(signals),
        "price": int(close.iloc[-1]),
        "change_rate": round(float(change_rate), 2) if change_rate is not None else None,
        "volume": int(volume.iloc[-1]),
        "volume_ratio": round(float(volume.iloc[-1] / avg_volume_20), 2) if avg_volume_20 > 0 else None,
        "rsi": rsi_now,
        "wave_direction": wave_info.get("wave_direction"),
        "wave_number": wave_info.get("wave_number"),
        "wave_progress_pct": wave_info.get("wave_progress_pct"),
        "buy_point": wave_info.get("buy_point"),
        "buy_point_2": wave_info.get("buy_point_2"),
        "target_price": wave_info.get("target_price"),
        "target_price_2": wave_info.get("target_price_2"),
        "stop_loss": wave_info.get("stop_loss"),
        "rating_stars": rating_stars,
        "rating_label": rating_label,
        "signal_markers": signal_markers,
        "chart_patterns": chart_patterns,
        "ma5": ma5, "ma20": ma20, "ma60": ma60, "ma112": ma112, "ma224": ma224,
        "rsi_series": rsi, "macd_line": macd_line, "macd_signal": signal_line,
        # ↑ 전부 상세페이지 차트용 (JSON 저장 전에 analysis_out에서 제거됨)
    }


def build_corp_code_map():
    """
    DART가 제공하는 전체 회사 목록(zip 안의 CORPCODE.xml)을 받아서
    {종목코드: corp_code} 매핑을 만든다. DART_API_KEY가 없으면 빈 딕셔너리를 반환한다
    (즉, 공시 기능은 키가 없어도 에러 없이 그냥 비활성화된다).
    """
    if not DART_API_KEY:
        print(f"[{datetime.now()}] DART_API_KEY가 설정되지 않아 공시 조회는 건너뜁니다.")
        return {}

    try:
        url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={DART_API_KEY}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_bytes = zf.read(zf.namelist()[0])
        root = ET.fromstring(xml_bytes)

        mapping = {}
        for node in root.findall("list"):
            stock_code = (node.findtext("stock_code") or "").strip()
            corp_code = (node.findtext("corp_code") or "").strip()
            if stock_code:
                mapping[stock_code] = corp_code

        print(f"[{datetime.now()}] DART corp_code 매핑 {len(mapping)}건 로드 완료")
        return mapping
    except Exception as e:
        print(f"  [경고] DART corp_code 매핑 실패: {e} (공시 기능 없이 계속 진행)", file=sys.stderr)
        return {}


def fetch_recent_disclosures(corp_code):
    """DART 공시검색 API로 최근 공시 목록(최대 DART_MAX_ITEMS건)을 가져온다."""
    if not DART_API_KEY or not corp_code:
        return []

    try:
        end_de = datetime.today().strftime("%Y%m%d")
        start_de = (datetime.today() - timedelta(days=DART_DISCLOSURE_LOOKBACK_DAYS)).strftime("%Y%m%d")
        url = (
            "https://opendart.fss.or.kr/api/list.json"
            f"?crtfc_key={DART_API_KEY}&corp_code={corp_code}"
            f"&bgn_de={start_de}&end_de={end_de}&page_count=100"
        )
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        data = resp.json()
        if data.get("status") != "000":
            return []  # "013" 등은 "해당 기간 공시 없음" — 정상적인 빈 결과

        items = data.get("list", [])[:DART_MAX_ITEMS]
        return [
            {
                "title": it.get("report_nm"),
                "date": it.get("rcept_dt"),
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={it.get('rcept_no')}",
            }
            for it in items
        ]
    except Exception:
        return []


def save_history_json(ticker: str, name: str, market: str, group: pd.DataFrame, analysis: dict, disclosures=None):
    """
    상세 차트 페이지용 데이터를 data/history/{ticker}.json 으로 저장한다.
    OHLCV 이력 + 분석 결과(analysis)를 함께 담아서, 신호 목록(data/signals.json)에
    없는 종목(워치리스트 300종목 등)도 상세페이지에서 바로 조회할 수 있게 한다.
    """
    series_keys = ("ma5", "ma20", "ma60", "ma112", "ma224", "rsi_series", "macd_line", "macd_signal")
    series = {k: analysis.get(k) for k in series_keys}
    signal_markers = analysis.get("signal_markers", [])

    tail = group.tail(HISTORY_DAYS_TO_SAVE).reset_index(drop=True)
    n = len(tail)
    tail_dates = set(tail["Date"].tolist())

    analysis_out = {k: v for k, v in analysis.items() if k not in series_keys and k != "signal_markers"}

    def series_tail(key, digits=1):
        s = series.get(key)
        if s is None:
            return [None] * n
        return [None if pd.isna(v) else round(float(v), digits) for v in s.tail(n)]

    history = {
        "ticker": ticker,
        "name": name,
        "market": market,
        "analysis": analysis_out,
        "disclosures": disclosures or [],
        "signal_markers": [m for m in signal_markers if m["date"] in tail_dates],
        "dates": tail["Date"].tolist(),
        "open": tail["Open"].astype(int).tolist(),
        "high": tail["High"].astype(int).tolist(),
        "low": tail["Low"].astype(int).tolist(),
        "close": tail["Close"].astype(int).tolist(),
        "volume": tail["Volume"].astype(int).tolist(),
        "ma5": series_tail("ma5"),
        "ma20": series_tail("ma20"),
        "ma60": series_tail("ma60"),
        "ma112": series_tail("ma112"),
        "ma224": series_tail("ma224"),
        "rsi": series_tail("rsi_series"),
        "macd": series_tail("macd_line", digits=2),
        "macd_signal": series_tail("macd_signal", digits=2),
    }

    os.makedirs("data/history", exist_ok=True)
    with open(f"data/history/{ticker}.json", "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False)


def clean_history_dir():
    """
    이전 실행에서 만들어진 history JSON을 전부 지운다.
    (오늘 신호가 없는 종목의 차트 데이터가 저장소에 계속 남아 쌓이는 것을 방지)
    """
    history_dir = "data/history"
    if os.path.isdir(history_dir):
        for fname in os.listdir(history_dir):
            if fname.endswith(".json"):
                os.remove(os.path.join(history_dir, fname))


def main():
    panel = build_panel()
    clean_history_dir()

    watchlist_codes = get_watchlist_codes(panel)
    corp_code_map = build_corp_code_map()

    signal_stocks = []   # 대시보드 메인 목록 (score >= MIN_SCORE_TO_INCLUDE)
    universe_stocks = []  # 검색용 전체 목록 (신호 종목 + 워치리스트 300종목)

    for code, group in panel.groupby("Code"):
        group = group.sort_values("Date").reset_index(drop=True)
        name = group["Name"].iloc[-1]
        market = group["Market"].iloc[-1]

        analysis = analyze_stock(group)

        if not analysis:
            # 상장 65거래일 미만 등으로 전체 분석은 안 되지만, 워치리스트에 있다면
            # "왜 없는지"라도 알 수 있게 최소 정보만 담은 스텁 항목을 만든다.
            if code in watchlist_codes:
                close_stub = group["Close"].reset_index(drop=True)
                last_close = float(close_stub.iloc[-1])
                prev_close = float(close_stub.iloc[-2]) if len(close_stub) >= 2 else None
                change_rate = (
                    round((last_close - prev_close) / prev_close * 100, 2)
                    if prev_close else None
                )
                stub = {
                    "ticker": code, "name": name, "market": market,
                    "signals": [], "score": 0,
                    "price": int(last_close), "change_rate": change_rate,
                    "volume": int(group["Volume"].iloc[-1]), "volume_ratio": None,
                    "rsi": None, "wave_direction": None, "wave_number": None,
                    "wave_progress_pct": None, "buy_point": None, "buy_point_2": None,
                    "target_price": None, "target_price_2": None, "stop_loss": None,
                    "rating_stars": 1, "rating_label": "관망",
                    "chart_patterns": [],
                    "insufficient_data": True,
                    "trading_days_available": len(group),
                    "ma5": close_stub.rolling(5).mean(),
                    "ma20": close_stub.rolling(20).mean(),
                    "ma60": close_stub.rolling(60).mean(),
                }
                save_history_json(code, name, market, group, stub, [])
                stub = {k: v for k, v in stub.items() if k not in ("ma5", "ma20", "ma60")}
                universe_stocks.append(stub)
            continue

        has_signal = analysis["score"] >= MIN_SCORE_TO_INCLUDE
        in_watchlist = code in watchlist_codes

        if not (has_signal or in_watchlist):
            continue  # 신호도 없고 워치리스트에도 없으면 저장하지 않음 (저장소 용량 절약)

        disclosures = []
        if corp_code_map.get(code):
            disclosures = fetch_recent_disclosures(corp_code_map[code])

        entry = {"ticker": code, "name": name, "market": market, **{
            k: v for k, v in analysis.items()
            if k not in ("ma5", "ma20", "ma60", "ma112", "ma224", "rsi_series",
                         "macd_line", "macd_signal", "signal_markers")
        }}

        universe_stocks.append(entry)
        if has_signal:
            signal_stocks.append(entry)

        save_history_json(code, name, market, group, analysis, disclosures)

    signal_stocks.sort(key=lambda x: x["score"], reverse=True)
    universe_stocks.sort(key=lambda x: (x["score"], x["rating_stars"]), reverse=True)

    output = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_date": panel["Date"].max(),  # 실제 시세가 반영된 마지막 거래일 (실행 시각과 다를 수 있음)
        "market": "KOSPI+KOSDAQ",
        "total_scanned": int(panel["Code"].nunique()),
        "total_signals": len(signal_stocks),
        "total_universe": len(universe_stocks),
        "dart_enabled": bool(DART_API_KEY),
        "wave_basis_note": WAVE_BASIS_NOTE,
        "pattern_basis_note": PATTERN_BASIS_NOTE,
        "stocks": signal_stocks,
        "universe": universe_stocks,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/signals.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[{datetime.now()}] 완료: 전체 {panel['Code'].nunique()}종목 중 "
          f"신호 {len(signal_stocks)}개 / 조회 가능 전체(워치리스트 포함) {len(universe_stocks)}개")


if __name__ == "__main__":
    main()
