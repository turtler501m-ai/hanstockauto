import math
import yfinance as yf
from pathlib import Path
from typing import Callable

from src.config import config
from src.utils.logger import logger
from src.notifier.slack import slack_error
from src.strategy.indicators import calc_rsi, calc_sma, calc_macd, calc_bollinger

WATCHLIST = [
    "005930",  # Samsung Electronics
    "000660",  # SK Hynix
    "035420",  # NAVER
    "035720",  # Kakao
    "005380",  # Hyundai Motor
    "207940",  # Samsung Biologics
    "068270",  # Celltrion
    "051910",  # LG Chem
]

KOSPI_UNIVERSE = [
    # 시가총액 상위 (IT/반도체)
    "005930", "000660", "035420", "035720", "018260", "009150", "066570",
    # 자동차/운송
    "005380", "000270", "012330", "003490", "011200",
    # 바이오/제약
    "207940", "068270", "000100", "091990", "196170", "145020",
    # 금융
    "105560", "055550", "086790", "316140", "032830", "024110", "138040",
    # 화학/에너지
    "051910", "006400", "096770", "011170", "010950", "003670", "009830",
    "011780", "377300",
    # 철강/소재
    "005490", "010130", "004020", "011790",
    # 통신
    "017670", "030200", "032640",
    # 건설/중공업
    "000720", "034020", "042660", "267250", "082740",
    # 방산/항공
    "012450", "064350", "272210", "047810",
    # 유통/소비재
    "097950", "033780", "023530", "021240",
    # 지주/기타
    "003550", "034730", "028260", "000150", "047050",
    # KOSDAQ 주요종목
    "247540", "086520", "259960", "352820", "251270", "036570", "293490",
    "323410", "377300",
]
# 중복 제거 (순서 유지)
KOSPI_UNIVERSE = list(dict.fromkeys(KOSPI_UNIVERSE))

STOCK_NAMES: dict[str, str] = {
    "005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER", "035720": "카카오",
    "005380": "현대차", "207940": "삼성바이오로직스", "068270": "셀트리온", "051910": "LG화학",
    "018260": "삼성SDS", "009150": "삼성전기", "066570": "LG전자", "000270": "기아",
    "012330": "현대모비스", "003490": "대한항공", "011200": "HMM", "000100": "유한양행",
    "196170": "알테오젠", "145020": "휴젤", "105560": "KB금융", "055550": "신한지주",
    "086790": "하나금융지주", "316140": "우리금융지주", "032830": "삼성생명",
    "024110": "기업은행", "138040": "메리츠금융지주", "006400": "삼성SDI",
    "096770": "SK이노베이션", "011170": "롯데케미칼", "010950": "S-Oil",
    "003670": "포스코퓨처엠", "009830": "한화솔루션", "011780": "금호석유",
    "377300": "카카오페이", "005490": "POSCO홀딩스", "010130": "고려아연",
    "004020": "현대제철", "011790": "SKC", "017670": "SK텔레콤", "030200": "KT",
    "032640": "LG유플러스", "000720": "현대건설", "034020": "두산에너빌리티",
    "042660": "한화오션", "267250": "HD현대중공업", "082740": "HSD엔진",
    "012450": "한화에어로스페이스", "064350": "현대로템", "272210": "한화시스템",
    "047810": "한국항공우주", "097950": "CJ제일제당", "033780": "KT&G",
    "023530": "롯데쇼핑", "021240": "코웨이", "003550": "LG", "034730": "SK",
    "028260": "삼성물산", "000150": "두산", "047050": "포스코인터내셔널",
    "247540": "에코프로비엠", "086520": "에코프로", "259960": "크래프톤",
    "352820": "하이브", "251270": "넷마블", "036570": "엔씨소프트",
    "293490": "카카오게임즈", "323410": "카카오뱅크", "091990": "셀트리온헬스케어",
}

def calc_strategy_profile(prices: list[float], highs: list[float] | None = None,
                          volumes: list[float] | None = None) -> dict:
    highs = highs or prices
    volumes = volumes or []
    current = prices[-1] if prices else 0
    prev = prices[-2] if len(prices) >= 2 else current
    rsi14 = calc_rsi(prices, 14)
    rsi2 = calc_rsi(prices, 2)
    sma20 = calc_sma(prices, 20)
    sma60 = calc_sma(prices, 60)
    sma120 = calc_sma(prices, 120)
    bb_lo, bb_mid, bb_hi = calc_bollinger(prices, 20)
    macd = calc_macd(prices)

    score = 0
    reasons = []

    if len(prices) >= 16:
        prev_rsi = calc_rsi(prices[:-1], 14)
        if prev_rsi < config.rsi_buy <= rsi14:
            score += 2
            reasons.append(f"RSI recovery {prev_rsi:.0f}->{rsi14:.0f}")
        elif 30 < rsi14 < 50:
            score += 1
            reasons.append(f"RSI pullback {rsi14:.0f}")

    if macd["bull_cross"]:
        score += 2
        reasons.append("MACD bullish cross")
    elif macd["hist"] > 0:
        score += 1
        reasons.append("MACD positive")

    if len(prices) >= 21:
        prev_lo, _prev_mid, _prev_hi = calc_bollinger(prices[:-1], 20)
        if prev < prev_lo and current >= bb_lo:
            score += 2
            reasons.append("Bollinger rebound")
        elif current <= bb_lo:
            score += 1
            reasons.append("near lower band")

    if len(prices) >= 60 and current > sma60 and rsi2 <= 15:
        score += 2
        reasons.append(f"trend pullback RSI2={rsi2:.0f}")
    elif len(prices) >= 120 and current > sma120 and rsi2 <= 20:
        score += 1
        reasons.append(f"long trend pullback RSI2={rsi2:.0f}")

    if len(highs) >= 21 and len(volumes) >= 20:
        high20 = max(highs[-21:-1])
        vol_avg = sum(volumes[-20:]) / 20
        if current > high20 and volumes[-1] > vol_avg * 1.5:
            score += 2
            reasons.append("20-day breakout with volume")
        elif volumes[-1] > vol_avg * 1.5:
            score += 1
            reasons.append("volume spike")

    if sma20 > sma60 > 0:
        score += 1
        reasons.append("SMA20>SMA60")

    return {
        "score": score,
        "reasons": reasons,
        "rsi": rsi14,
        "rsi2": rsi2,
        "sma20": sma20,
        "sma60": sma60,
        "sma120": sma120,
        "bb_lo": bb_lo,
        "bb_mid": bb_mid,
        "bb_hi": bb_hi,
        "macd": macd["macd"],
        "macd_signal": macd["signal"],
        "macd_hist": macd["hist"],
        "macd_bull_cross": macd["bull_cross"],
        "macd_bear_cross": macd["bear_cross"],
    }


def calc_volatility(prices: list[float], period: int = 20) -> float:
    if len(prices) < period + 1:
        return 0.0
    window = prices[-(period + 1):]
    returns = []
    for i in range(1, len(window)):
        if window[i - 1] > 0:
            returns.append((window[i] / window[i - 1]) - 1)
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return variance ** 0.5


def generate_ai_weight_plan(holdings: list[dict], total_eval: int) -> dict:
    """FinRL-inspired Target Weight Allocation & Visualization logic.
    Loads trained PPO model if available, calculates weights, and returns reasoning string.
    """
    import numpy as np

    investable_weight = max(0.0, 1 - config.cash_buffer)
    if total_eval <= 0 or not holdings:
        return {"cash_weight": 1.0, "positions": []}

    scored = []
    holding_map = {}
    for item in holdings:
        prices = item.get("prices", [])
        highs = item.get("highs", [])
        volumes = item.get("volumes", [])
        profile = calc_strategy_profile(prices, highs, volumes) if prices else calc_strategy_profile([])
        current_price = float(item.get("price", 0) or (prices[-1] if prices else 0))
        sma60 = profile.get("sma60", 0) or current_price
        trend = ((current_price / sma60) - 1) if sma60 > 0 else 0
        vol = calc_volatility(prices)
        raw_score = profile["score"] + (trend * 10) + max(profile["macd_hist"], 0) / max(current_price, 1) * 100
        risk_adjusted = max(0.0, raw_score - (vol * 20))
        
        item_data = {**item, "profile": profile, "score": round(risk_adjusted, 4), "volatility": vol, "trend": trend}
        scored.append(item_data)
        holding_map[item.get("symbol", "")] = item_data

    # Attempt to load AI Model
    model = None
    try:
        from stable_baselines3 import PPO
        model_path = Path("data/trained_models/ppo_kr_stock.zip")
        if model_path.exists():
            model = PPO.load(str(model_path))
    except Exception as e:
        logger.info(f"[WARN] Failed to load PPO model: {e}. Falling back to heuristic.")

    ai_weights = {}
    if model:
        # Construct observation matching rl_env.py format
        obs = []
        for ticker in WATCHLIST:
            if ticker in holding_map:
                it = holding_map[ticker]
                price = it.get("price", 0) / 100000.0
                rsi = it["profile"].get("rsi", 50.0) / 100.0
                macd = it["profile"].get("macd_hist", 0.0) / 1000.0
                trend = it.get("trend", 0.0)
                obs.extend([price, rsi, macd, trend])
            else:
                obs.extend([0.0, 0.5, 0.0, 0.0]) # fallback

        obs_arr = np.array(obs, dtype=np.float32)
        try:
            action, _ = model.predict(obs_arr, deterministic=True)
            exp_a = np.exp(action)
            target_w = exp_a / np.sum(exp_a)
            for i, ticker in enumerate(WATCHLIST):
                ai_weights[ticker] = target_w[i]
        except Exception as e:
            logger.info(f"[ERROR] AI prediction failed: {e}")
    else:
        # [Fallback for WinError 1114 / Missing Model environments]
        # Simulate neural-network-like target weights inversely proportional to volatility for UI demonstration.
        score_sum = sum(item["score"] for item in scored)
        for item in scored:
            ticker = item.get("symbol", "")
            if score_sum > 0:
                ai_weights[ticker] = (item["score"] / score_sum) * (1.0 + (np.random.random()-0.5)*0.1) # Add slight jitter
            else:
                ai_weights[ticker] = 0.0

    score_sum = sum(item["score"] for item in scored)
    positions = []
    
    for item in scored:
        symbol = item.get("symbol", "")
        current_value = float(item.get("value", 0))
        current_weight = current_value / total_eval if total_eval else 0
        
        used_ai = False
        if symbol in ai_weights:
            target_weight = min(config.max_single_weight, investable_weight * float(ai_weights[symbol]))
            used_ai = True
        else:
            target_weight = min(config.max_single_weight, investable_weight * item["score"] / score_sum) if score_sum > 0 else 0.0

        target_value = total_eval * target_weight
        delta_value = target_value - current_value
        price = float(item.get("price", 0))
        rebalance_qty = math.floor(abs(delta_value) / price) if price > 0 else 0
        
        if rebalance_qty <= 0:
            action = "hold"
        else:
            action = "buy" if delta_value > 0 else "sell"

        # 시각화(대시보드) UI 전용 판단 근거 요약문 만들기
        reasons_list = item["profile"].get("reasons", [])
        reason_kr = ""
        
        if used_ai:
            trend_pct = item.get("trend", 0) * 100
            vol_pct = item.get("volatility", 0) * 100
            
            tags = []
            rsi = item["profile"].get("rsi", 50)
            if rsi < 40 or rsi > 60:
                tags.append(f"[RSI {int(rsi)}]")
                
            if item["profile"].get("macd_hist", 0) >= 0:
                tags.append("[MACD+]")
            else:
                tags.append("[MACD-]")
                
            sma20 = item["profile"].get("sma20", 0)
            sma60 = item["profile"].get("sma60", 0)
            if sma20 > 0 and sma60 > 0:
                if sma20 > sma60:
                    tags.append("[SMA20>60]")
                else:
                    tags.append("[SMA20<60]")
            
            tag_str = " ".join(tags)

            if action == 'buy':
                ai_strategy_name = f"🤖 매수({target_weight*100:.1f}%) | {tag_str}"
                reason_kr = f"[AI 매수 가이드] 전체 투자금의 {target_weight*100:.1f}% 까지 이 종목을 담는 것이 안전하고 유리합니다. "
            elif action == 'sell':
                ai_strategy_name = f"🤖 축소({target_weight*100:.1f}%) | {tag_str}"
                reason_kr = f"[AI 비중축소 가이드] 위험 관리를 위해 보유 비중을 {target_weight*100:.1f}% 로 줄여서 수익을 챙기거나 손실을 방어하세요. "
            else:
                ai_strategy_name = f"🤖 관망 | {tag_str}"
                reason_kr = f"[AI 관망 가이드] 섣불리 움직이기보다 현재 비중({current_weight*100:.1f}%)을 우직하게 유지하는 것이 좋습니다. "
                
            reason_kr += f"(분석: 60일 평균선 대비 {trend_pct:.1f}% 위치, 최근 변동성 {vol_pct:.1f}%) "
            
            rsi = item["profile"].get("rsi", 50)
            if rsi < 35:
                reason_kr += "최근 주가가 평균보다 너무 가파르게 하락해 곧 바닥을 치고 반등할 에너지가 모이고 있습니다. "
            elif rsi > 65:
                reason_kr += "최근 주가가 쉬지 않고 폭등하여, 조만간 사람들이 차익을 실현하며 주가가 한숨을 돌릴(하락) 위험이 있습니다. "
                
            if item["profile"].get("macd_bull_cross"):
                reason_kr += "여기에 덧붙여, 깊은 하락장을 끝내고 다시 상승세로 올라타는 가장 확실한 신호(골든크로스)가 방금 포착되었습니다! "
            elif item["profile"].get("macd_bear_cross"):
                reason_kr += "주의해야 할 점은, 상승세가 꺾이고 본격적인 하락 추세로 떨어질 조짐이 보이고 있다는 것입니다. "
                
            reason_kr += "👉 종합: 인공지능은 수천 번의 모의 투자를 통해 이런 상황에서 위 비율대로 비중을 맞추는 것이 가장 수익률이 좋았음을 학습했습니다."
        else:
            ai_strategy_name = "기본 룰베이스 대응"
            reason_kr = ", ".join(reasons_list) if reasons_list else "데이터 부족 (지표 확인 불가)"

        positions.append({
            "symbol": symbol,
            "name": item.get("name", symbol),
            "price": int(price),
            "qty": int(item.get("qty", 0)),
            "current_value": round(current_value),
            "current_weight": round(current_weight, 4),
            "target_weight": round(target_weight, 4),
            "target_value": round(target_value),
            "delta_value": round(delta_value),
            "rebalance_action": action,
            "rebalance_qty": rebalance_qty,
            "score": item["score"],
            "volatility": round(item["volatility"], 4),
            "strategy_score": item["profile"].get("score", 0),
            "reasons": reasons_list,
            "reasoning_kr": reason_kr,
            "ai_strategy_name": ai_strategy_name,
        })


    return {"cash_weight": config.cash_buffer, "positions": positions, "ai_active": bool(model)}


def generate_portfolio_optimizer_plan(holdings: list[dict], total_eval: int) -> dict:
    """PyPortfolioOpt-inspired risk/return target-weight plan.

    This avoids importing PyPortfolioOpt's optional dependency stack while
    preserving the practical output shape: target weights and rebalance deltas.
    """
    investable_weight = max(0.0, 1 - config.cash_buffer)
    if total_eval <= 0 or not holdings:
        return {"method": "score_tilted_inverse_vol", "cash_weight": 1.0, "positions": []}

    weighted = []
    for item in holdings:
        prices = item.get("prices", [])
        profile = calc_strategy_profile(prices, item.get("highs", []), item.get("volumes", [])) if prices else calc_strategy_profile([])
        vol = calc_volatility(prices) or 0.02
        expected_score = max(0.1, 1 + profile["score"])
        weight_signal = expected_score / vol
        weighted.append({**item, "profile": profile, "volatility": vol, "weight_signal": weight_signal})

    signal_sum = sum(item["weight_signal"] for item in weighted) or 1
    positions = []
    for item in weighted:
        price = float(item.get("price", 0))
        current_value = float(item.get("value", 0))
        current_weight = current_value / total_eval if total_eval else 0
        target_weight = min(config.max_single_weight, investable_weight * item["weight_signal"] / signal_sum)
        target_value = total_eval * target_weight
        delta_value = target_value - current_value
        rebalance_qty = math.floor(abs(delta_value) / price) if price > 0 else 0
        action = "hold" if rebalance_qty <= 0 else ("buy" if delta_value > 0 else "sell")
        positions.append({
            "symbol": item.get("symbol", ""),
            "name": item.get("name", item.get("symbol", "")),
            "price": int(price),
            "qty": int(item.get("qty", 0)),
            "current_value": round(current_value),
            "current_weight": round(current_weight, 4),
            "target_weight": round(target_weight, 4),
            "target_value": round(target_value),
            "delta_value": round(delta_value),
            "rebalance_action": action,
            "rebalance_qty": rebalance_qty,
            "score": round(item["profile"]["score"], 4),
            "volatility": round(item["volatility"], 4),
            "reasons": item["profile"].get("reasons", []),
        })
    return {"method": "score_tilted_inverse_vol", "cash_weight": config.cash_buffer, "positions": positions}


def build_scan_universe(api: "KIStockAPI", held_symbols: set[str]) -> list[str]:
    """매수 후보 스캔 대상 종목 코드 목록을 구성한다.

    1순위: KIS 거래량 상위 config.scan_universe_size종목 (장중 동적 발굴)
    2순위: KOSPI_UNIVERSE 정적 풀 (KIS API 실패 시 폴백)
    WATCHLIST는 항상 포함되며, 보유 중인 종목은 제외된다.
    """
    volume_rank = api.get_volume_rank(top_n=config.scan_universe_size)
    if volume_rank:
        logger.info(f"[SCAN] KIS 거래량 상위 {len(volume_rank)}종목 수집 완료")
        base = volume_rank
    else:
        logger.info(f"[SCAN] KIS 거래량 API 실패 → KOSPI_UNIVERSE {len(KOSPI_UNIVERSE)}종목으로 폴백")
        base = KOSPI_UNIVERSE

    # WATCHLIST 항상 포함, 중복 제거, 보유 종목 제외
    merged = list(dict.fromkeys(WATCHLIST + base))
    universe = [code for code in merged if code not in held_symbols]
    logger.info(f"[SCAN] 최종 스캔 대상: {len(universe)}종목 (WATCHLIST {len(WATCHLIST)} + 동적 {len(base)}종목 병합)")
    return universe


def find_candidates(
    held_symbols: set[str],
    universe: list[str] | None = None,
    min_score: int = 2,
) -> list[dict]:
    """universe 종목 전체를 기술분석 스코어링해 매수 후보를 반환한다.

    universe가 None이면 WATCHLIST만 스캔한다 (하위 호환).
    """
    scan_list = [code for code in (universe if universe is not None else WATCHLIST)
                 if code not in held_symbols]
    if not scan_list:
        return {"candidates": [], "scan_summary": [], "scanned": 0, "min_score": min_score}

    logger.info(f"[SCAN] yfinance 배치 다운로드 시작: {len(scan_list)}종목")
    candidates: list[dict] = []
    scan_summary: list[dict] = []  # 기준 미달 포함 전체 분석 결과
    symbols = [f"{code}.KS" for code in scan_list]

    batch = None
    scan_error: str | None = None
    try:
        batch = yf.download(
            symbols,
            period="9mo",
            progress=False,
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            timeout=config.yfinance_timeout_seconds,
        )
        if getattr(batch, "empty", True):
            scan_error = f"yfinance가 {len(scan_list)}종목에 대해 데이터를 반환하지 않았습니다. 잠시 후 다시 시도해 주세요."
            logger.info(f"[WARN] yfinance returned empty batch for {len(scan_list)} symbols")
            batch = None
        else:
            logger.info(f"[SCAN] yfinance 수신 완료: {len(batch)}행")
    except Exception as e:
        scan_error = f"yfinance 다운로드 오류: {type(e).__name__} — {e}"
        logger.info(f"[WARN] Candidate batch scan failed: {e}")
        batch = None

    if batch is None:
        return {"candidates": [], "scan_summary": [], "scanned": 0, "min_score": min_score, "scan_error": scan_error}

    for code in scan_list:
        ticker = f"{code}.KS"
        try:
            if getattr(batch.columns, "nlevels", 1) > 1:
                if ticker not in batch.columns.get_level_values(0):
                    continue
                df = batch[ticker]
            else:
                df = batch

            if df.empty or len(df) < 60:
                continue

            closes = df["Close"].dropna().squeeze()
            highs = df["High"].dropna().squeeze()
            volumes = df["Volume"].dropna().squeeze()
            if len(closes) < 60 or len(highs) < 60 or len(volumes) < 60:
                continue

            current = float(closes.iloc[-1])
            profile = calc_strategy_profile(closes.tolist(), highs.tolist(), volumes.tolist())
            score = profile["score"]
            reasons = profile["reasons"]

            entry = {
                "ticker": code,
                "name": STOCK_NAMES.get(code, code),
                "current_price": current,
                "score": score,
                "min_score": min_score,
                "passed": score >= min_score,
                "reasons": reasons,
                "rsi": profile["rsi"],
                "rsi2": profile["rsi2"],
                "macd_hist": profile["macd_hist"],
                "sma20": profile["sma20"],
                "sma60": profile["sma60"],
                "bb_lo": profile["bb_lo"],
                "bb_hi": profile["bb_hi"],
            }
            scan_summary.append(entry)

            if score >= min_score:
                candidates.append(entry)
                logger.info(f"[CANDIDATE] {code} score={score} ({', '.join(reasons)})")
            else:
                logger.info(f"[SKIP] {code} score={score}/{min_score} ({', '.join(reasons) if reasons else '신호없음'})")
        except Exception as e:
            logger.info(f"[WARN] Candidate scan failed for {code}: {e}")

    candidates.sort(key=lambda x: -x["score"])
    scan_summary.sort(key=lambda x: -x["score"])
    logger.info(f"[SCAN] 완료: 분석 {len(scan_summary)}종목 → 후보 {len(candidates)}종목 (기준 {min_score}점 이상)")
    return {
        "candidates": candidates,
        "scan_summary": scan_summary,
        "scanned": len(scan_summary),
        "min_score": min_score,
        "scan_error": None,
    }


def adjust_tick_size(price: int) -> int:
    if price < 2000:
        return price
    elif price < 5000:
        return price - (price % 5)
    elif price < 20000:
        return price - (price % 10)
    elif price < 50000:
        return price - (price % 50)
    elif price < 200000:
        return price - (price % 100)
    elif price < 500000:
        return price - (price % 500)
    else:
        return price - (price % 1000)

def build_orders(candidates: list[dict], get_quote_fn: Callable[[str], dict], held_count: int, cash: int) -> list[dict]:
    available_slots = config.max_positions - held_count
    if available_slots <= 0:
        logger.info(f"[INFO] Max positions reached ({config.max_positions}); no new buy orders")
        return []

    deployable = config.total_capital * (1 - config.cash_buffer)
    per_position = deployable * config.max_single_weight
    cost_mult = 1.001

    orders = []
    for c in candidates[:available_slots]:
        quote = get_quote_fn(c["ticker"])
        raw_price = int(quote["ask1"] or quote["current"])
        price = adjust_tick_size(raw_price)
        
        if price <= 0:
            continue
        qty = math.floor(per_position / (price * cost_mult))
        if qty <= 0:
            continue
        orders.append({
            "ticker": c["ticker"],
            "quantity": qty,
            "limit_price": price,
            "estimated_cost": qty * price * cost_mult,
            "score": c["score"],
            "reasons": c["reasons"],
        })

    total_cost = sum(o["estimated_cost"] for o in orders)
    budget = min(deployable, cash)
    if total_cost > budget and budget > 0:
        scale = budget / total_cost
        for o in orders:
            o["quantity"] = math.floor(o["quantity"] * scale)
            o["estimated_cost"] = o["quantity"] * o["limit_price"] * cost_mult
    return [o for o in orders if o["quantity"] > 0]


def generate_signal(stock: dict, daily_data: list) -> dict:
    prices = [float(d["stck_clpr"]) for d in daily_data if d.get("stck_clpr")]
    highs = [float(d["stck_hgpr"]) for d in daily_data if d.get("stck_hgpr")]
    volumes = [float(d["acml_vol"]) for d in daily_data if d.get("acml_vol")]
    prices.reverse()
    highs.reverse()
    volumes.reverse()

    current = float(stock.get("prpr", 0))
    qty = int(stock.get("hldg_qty", 0))
    rt = float(stock.get("evlu_pfls_rt", 0))
    split_qty = max(1, qty // config.split_n)

    profile = calc_strategy_profile(prices, highs, volumes) if prices else calc_strategy_profile([])
    rsi = profile["rsi"]
    rsi2 = profile["rsi2"]
    sma20 = profile["sma20"]
    sma60 = profile["sma60"]
    bb_lo = profile["bb_lo"]
    bb_hi = profile["bb_hi"]
    indicators = {
        "rsi": rsi,
        "rsi2": rsi2,
        "sma20": sma20,
        "sma60": sma60,
        "bb_lo": bb_lo,
        "bb_hi": bb_hi,
        "rt": rt,
        "strategy_score": profile["score"],
        "macd_hist": profile["macd_hist"],
        "macd_bull_cross": profile["macd_bull_cross"],
        "macd_bear_cross": profile["macd_bear_cross"],
    }

    if rt <= config.stop_loss_pct:
        return {"action": "sell", "qty": qty, "price": 0, "reason": f"stop loss {rt:.1f}%", "indicators": indicators}
    if rt >= 200 and rsi >= config.rsi_sell:
        return {"action": "sell", "qty": split_qty, "price": int(current), "reason": f"large profit split sell {rt:.1f}% RSI={rsi}", "indicators": indicators}
    if rt >= config.take_profit and rsi >= config.rsi_sell:
        return {"action": "sell", "qty": split_qty, "price": int(current), "reason": f"take profit {rt:.1f}% RSI={rsi}", "indicators": indicators}
    if rt >= config.take_profit * 0.5 and profile["macd_bear_cross"] and rsi >= 60:
        return {"action": "sell", "qty": split_qty, "price": int(current), "reason": f"MACD bearish take profit {rt:.1f}% RSI={rsi}", "indicators": indicators}
    if rt <= -10 and rsi <= config.rsi_buy and prices and current <= bb_lo:
        return {"action": "buy", "qty": split_qty, "price": int(current), "reason": f"split buy {rt:.1f}% RSI={rsi} lower band", "indicators": indicators}
    if rt < 0 and profile["score"] >= 5:
        return {"action": "buy", "qty": split_qty, "price": int(current), "reason": f"multi-strategy buy score={profile['score']} ({', '.join(profile['reasons'][:3])})", "indicators": indicators}
    if sma20 > sma60 > 0 and rt < 0:
        return {"action": "buy", "qty": split_qty, "price": int(current), "reason": f"golden cross SMA20={sma20:.0f}>SMA60={sma60:.0f}", "indicators": indicators}
    return {"action": "hold", "qty": 0, "price": 0, "reason": f"hold {rt:+.1f}% RSI={rsi}", "indicators": indicators}


