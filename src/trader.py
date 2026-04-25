"""
세븐스플릿 자동매매 엔진
KIStock API + Claude AI 기반
"""
import os
import json
import requests
from datetime import datetime, time
from typing import Optional

# ── 설정 ──────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
KISTOCK_APP_KEY   = os.environ.get("KISTOCK_APP_KEY", "")
KISTOCK_APP_SECRET= os.environ.get("KISTOCK_APP_SECRET", "")
KISTOCK_ACCOUNT   = os.environ.get("KISTOCK_ACCOUNT", "")   # 계좌번호
KAKAO_TOKEN       = os.environ.get("KAKAO_TOKEN", "")       # 카카오 알림 (선택)

# 세븐스플릿 전략 파라미터
SPLIT_N       = int(os.environ.get("SPLIT_N", "7"))          # 분할 횟수
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "-15")) # 손절 기준 %
TAKE_PROFIT   = float(os.environ.get("TAKE_PROFIT", "30"))   # 1차 목표 수익 %
RSI_BUY       = int(os.environ.get("RSI_BUY", "30"))         # RSI 매수 기준
RSI_SELL      = int(os.environ.get("RSI_SELL", "70"))        # RSI 매도 기준
DRY_RUN       = os.environ.get("DRY_RUN", "true").lower() == "true"  # 모의 실행

BASE_URL = "https://openapi.koreainvestment.com:9443"

# ── KIStock API ────────────────────────────────────────────
class KIStockAPI:
    def __init__(self):
        self.access_token = None
        self._get_token()

    def _get_token(self):
        url = f"{BASE_URL}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": KISTOCK_APP_KEY,
            "appsecret": KISTOCK_APP_SECRET,
        }
        r = requests.post(url, json=body, timeout=10)
        r.raise_for_status()
        self.access_token = r.json()["access_token"]

    def _headers(self, tr_id: str) -> dict:
        return {
            "authorization": f"Bearer {self.access_token}",
            "appkey": KISTOCK_APP_KEY,
            "appsecret": KISTOCK_APP_SECRET,
            "tr_id": tr_id,
            "custtype": "P",
            "Content-Type": "application/json",
        }

    def get_balance(self) -> dict:
        url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
        params = {
            "CANO": KISTOCK_ACCOUNT[:8],
            "ACNT_PRDT_CD": KISTOCK_ACCOUNT[8:],
            "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
            "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
        }
        r = requests.get(url, headers=self._headers("TTTC8434R"), params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def get_price(self, symbol: str) -> dict:
        url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol}
        r = requests.get(url, headers=self._headers("FHKST01010100"), params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def get_daily(self, symbol: str, n: int = 20) -> list:
        """최근 n일 일별 시세"""
        url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        today = datetime.now().strftime("%Y%m%d")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",
            "FID_INPUT_DATE_1": "",
            "FID_INPUT_DATE_2": today,
        }
        r = requests.get(url, headers=self._headers("FHKST01010400"), params=params, timeout=10)
        r.raise_for_status()
        data = r.json().get("output2", [])
        return data[:n]

    def place_order(self, symbol: str, order_type: str, price: int, qty: int) -> dict:
        """
        order_type: "buy" | "sell"
        price: 0이면 시장가
        """
        if DRY_RUN:
            log(f"[DRY_RUN] {order_type.upper()} {symbol} {qty}주 @ {price if price else '시장가'}")
            return {"rt_cd": "0", "msg1": "모의주문 완료", "dry_run": True}

        url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = "TTTC0802U" if order_type == "buy" else "TTTC0801U"
        body = {
            "CANO": KISTOCK_ACCOUNT[:8],
            "ACNT_PRDT_CD": KISTOCK_ACCOUNT[8:],
            "PDNO": symbol,
            "ORD_DVSN": "01" if price == 0 else "00",  # 01=시장가, 00=지정가
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
        }
        r = requests.post(url, headers=self._headers(tr_id), json=body, timeout=10)
        r.raise_for_status()
        return r.json()


# ── 기술 지표 ──────────────────────────────────────────────
def calc_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calc_sma(prices: list, period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period

def calc_bollinger(prices: list, period: int = 20, k: float = 2.0) -> tuple:
    if len(prices) < period:
        p = prices[-1]
        return p, p, p
    window = prices[-period:]
    mid = sum(window) / period
    std = (sum((x - mid)**2 for x in window) / period) ** 0.5
    return round(mid - k*std, 0), round(mid, 0), round(mid + k*std, 0)


# ── Claude AI 분석 ─────────────────────────────────────────
def ask_claude(prompt: str) -> str:
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 800,
        "system": (
            "당신은 세븐스플릿(7분할 매매) 전문 자동매매 AI입니다. "
            "분석 결과를 반드시 JSON 형식으로만 반환하세요. "
            "응답 예시: {\"action\": \"buy\"|\"sell\"|\"hold\", \"qty\": 숫자, \"price\": 숫자, \"reason\": \"한줄이유\"}"
        ),
        "messages": [{"role": "user", "content": prompt}]
    }
    r = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=30)
    r.raise_for_status()
    return r.json()["content"][0]["text"]


# ── 세븐스플릿 신호 생성 ───────────────────────────────────
def generate_signal(stock: dict, daily_data: list) -> dict:
    """
    stock: {pdno, prdt_name, hldg_qty, pchs_avg_pric, prpr, evlu_pfls_rt}
    returns: {action, qty, price, reason, indicators}
    """
    prices = [float(d["stck_clpr"]) for d in daily_data if d.get("stck_clpr")]
    prices.reverse()  # 오래된 것 → 최신 순

    current_price = float(stock["prpr"])
    avg_price     = float(stock["pchs_avg_pric"])
    qty           = int(stock["hldg_qty"])
    rt            = float(stock["evlu_pfls_rt"])
    name          = stock["prdt_name"]
    symbol        = stock["pdno"]

    # 기술 지표 계산
    rsi   = calc_rsi(prices)
    sma20 = calc_sma(prices, 20)
    sma60 = calc_sma(prices, 60)
    bb_lo, bb_mid, bb_hi = calc_bollinger(prices)

    split_qty = max(1, qty // SPLIT_N)

    indicators = {
        "rsi": rsi, "sma20": sma20, "sma60": sma60,
        "bb_lo": bb_lo, "bb_mid": bb_mid, "bb_hi": bb_hi,
        "current": current_price, "avg": avg_price, "rt": rt
    }

    # ── 규칙 기반 1차 판단 ──
    # 손절
    if rt <= STOP_LOSS_PCT:
        return {"action": "sell", "qty": qty, "price": 0,
                "reason": f"손절 기준 도달 ({rt}%)", "indicators": indicators}

    # 강 매도: 수익 200% 초과 + RSI 과매수
    if rt >= 200 and rsi >= RSI_SELL:
        return {"action": "sell", "qty": split_qty, "price": int(current_price),
                "reason": f"세븐스플릿 분할매도 — +{rt}%, RSI {rsi}", "indicators": indicators}

    # 1차 목표 수익 + RSI 과매수
    if rt >= TAKE_PROFIT and rsi >= RSI_SELL:
        return {"action": "sell", "qty": split_qty, "price": int(current_price),
                "reason": f"목표수익 달성 분할매도 — +{rt}%, RSI {rsi}", "indicators": indicators}

    # 매수: 하락 + RSI 과매도 + 볼린저 하단
    if rt <= -10 and rsi <= RSI_BUY and current_price <= bb_lo:
        return {"action": "buy", "qty": split_qty, "price": int(current_price),
                "reason": f"세븐스플릿 분할매수 — {rt}%, RSI {rsi}, BB하단", "indicators": indicators}

    # 골든크로스
    if sma20 > sma60 and rt < 0:
        return {"action": "buy", "qty": split_qty, "price": int(current_price),
                "reason": f"골든크로스 + 손실구간 매수 — SMA20 {sma20:.0f} > SMA60 {sma60:.0f}", "indicators": indicators}

    return {"action": "hold", "qty": 0, "price": 0,
            "reason": f"홀드 유지 — +{rt}%, RSI {rsi}", "indicators": indicators}


# ── 카카오 알림 ────────────────────────────────────────────
def send_kakao(message: str):
    if not KAKAO_TOKEN:
        return
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {KAKAO_TOKEN}"}
    data = {"template_object": json.dumps({
        "object_type": "text",
        "text": message,
        "link": {"web_url": "https://github.com/turtler501m-ai/hanstockauto"}
    })}
    try:
        requests.post(url, headers=headers, data=data, timeout=10)
    except Exception as e:
        log(f"카카오 알림 실패: {e}")


# ── 로그 ──────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


# ── 메인 실행 ──────────────────────────────────────────────
def run():
    log("=" * 60)
    log(f"세븐스플릿 자동매매 시작 | DRY_RUN={DRY_RUN}")
    log("=" * 60)

    api = KIStockAPI()

    # 잔고 조회
    balance = api.get_balance()
    stocks  = balance.get("output1", [])
    summary = balance.get("output2", [{}])[0]
    cash    = int(summary.get("dnca_tot_amt", 0))

    log(f"예수금: ₩{cash:,} | 보유종목: {len(stocks)}개")

    results = []

    for stock in stocks:
        symbol = stock["pdno"]
        name   = stock["prdt_name"]
        rt     = float(stock["evlu_pfls_rt"])

        log(f"\n[{name}({symbol})] 수익률 {rt:+.2f}%")

        try:
            daily = api.get_daily(symbol, n=60)
        except Exception as e:
            log(f"  시세 조회 실패: {e}")
            continue

        signal = generate_signal(stock, daily)
        action = signal["action"]
        ind    = signal["indicators"]

        log(f"  RSI={ind['rsi']} | SMA20={ind['sma20']:.0f} | BB({ind['bb_lo']:.0f}~{ind['bb_hi']:.0f})")
        log(f"  신호: {action.upper()} | {signal['reason']}")

        if action != "hold":
            # 매수 가능 잔고 확인
            if action == "buy":
                cost = signal["qty"] * signal["price"]
                if cost > cash:
                    log(f"  예수금 부족 — 필요 ₩{cost:,}, 보유 ₩{cash:,} → 스킵")
                    continue

            # 주문 실행
            order_result = api.place_order(
                symbol=symbol,
                order_type=action,
                price=signal["price"],
                qty=signal["qty"]
            )

            ok = order_result.get("rt_cd") == "0"
            status = "성공" if ok else "실패"
            log(f"  주문 {status}: {action.upper()} {signal['qty']}주 @ {signal['price'] or '시장가'}")

            results.append({
                "symbol": symbol, "name": name,
                "action": action, "qty": signal["qty"],
                "price": signal["price"], "reason": signal["reason"],
                "status": status
            })

            if ok and action == "buy":
                cash -= signal["qty"] * signal["price"]

    # ── 결과 요약 및 알림 ──
    if results:
        lines = [f"[세븐스플릿 자동매매] {datetime.now().strftime('%m/%d %H:%M')}"]
        for r in results:
            emoji = "🟢" if r["action"] == "buy" else "🔴"
            lines.append(f"{emoji} {r['name']} {r['action'].upper()} {r['qty']}주 — {r['status']}")
            lines.append(f"   사유: {r['reason']}")
        msg = "\n".join(lines)
        log(f"\n{msg}")
        send_kakao(msg)
    else:
        log("\n전체 종목 홀드 — 액션 없음")

    log("\n자동매매 완료")
    return results


if __name__ == "__main__":
    run()
