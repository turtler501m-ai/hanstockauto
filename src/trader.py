"""
세븐스플릿 자동매매 엔진
KIStock API + Claude AI 기반
"""
import os
import sys
import json
import requests
from datetime import datetime

# ── 설정 ──────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
KISTOCK_APP_KEY    = os.environ.get("KISTOCK_APP_KEY", "")
KISTOCK_APP_SECRET = os.environ.get("KISTOCK_APP_SECRET", "")
KISTOCK_ACCOUNT    = os.environ.get("KISTOCK_ACCOUNT", "")
KAKAO_TOKEN        = os.environ.get("KAKAO_TOKEN", "")

SPLIT_N       = int(os.environ.get("SPLIT_N", "7"))
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "-15"))
TAKE_PROFIT   = float(os.environ.get("TAKE_PROFIT", "30"))
RSI_BUY       = int(os.environ.get("RSI_BUY", "30"))
RSI_SELL      = int(os.environ.get("RSI_SELL", "70"))
DRY_RUN       = os.environ.get("DRY_RUN", "true").lower() == "true"

BASE_URL = "https://openapi.koreainvestment.com:9443"


# ── 로그 ──────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    log_file = os.environ.get("LOG_FILE", "")
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ── Secrets 검증 ──────────────────────────────────────────
def check_secrets():
    missing = []
    if not KISTOCK_APP_KEY:    missing.append("KISTOCK_APP_KEY")
    if not KISTOCK_APP_SECRET: missing.append("KISTOCK_APP_SECRET")
    if not KISTOCK_ACCOUNT:    missing.append("KISTOCK_ACCOUNT")
    if missing:
        log(f"[ERROR] 필수 Secrets 미등록: {', '.join(missing)}")
        log("[ERROR] GitHub → Settings → Secrets and variables → Actions 에서 등록하세요")
        sys.exit(1)
    log(f"[OK] Secrets 확인: APP_KEY={KISTOCK_APP_KEY[:8]}... / ACCOUNT={KISTOCK_ACCOUNT[:4]}****")


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
        log("[API] 토큰 발급 요청 중...")
        try:
            r = requests.post(url, json=body, timeout=15)
            log(f"[API] 토큰 응답 HTTP {r.status_code}")
            r.raise_for_status()
            data = r.json()
            self.access_token = data.get("access_token", "")
            expires = data.get("access_token_token_expired", "")
            if not self.access_token:
                log(f"[ERROR] 토큰 발급 실패 — 응답: {data}")
                sys.exit(1)
            log(f"[OK] 토큰 발급 성공 (만료: {expires})")
        except requests.exceptions.ConnectionError as e:
            log(f"[ERROR] API 서버 연결 실패: {e}")
            sys.exit(1)
        except requests.exceptions.HTTPError as e:
            log(f"[ERROR] 토큰 발급 HTTP 오류: {e} — {r.text[:300]}")
            sys.exit(1)
        except Exception as e:
            log(f"[ERROR] 토큰 발급 예외: {e}")
            sys.exit(1)

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
        cano = KISTOCK_ACCOUNT[:8]
        acnt = KISTOCK_ACCOUNT[8:] if len(KISTOCK_ACCOUNT) > 8 else "01"
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt,
            "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
            "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
        }
        log(f"[API] 잔고 조회 (계좌: {cano}-{acnt})")
        try:
            r = requests.get(url, headers=self._headers("TTTC8434R"), params=params, timeout=15)
            log(f"[API] 잔고 응답 HTTP {r.status_code}")
            r.raise_for_status()
            data = r.json()
            rt_cd = data.get("rt_cd", "?")
            msg   = data.get("msg1", "")
            log(f"[API] 잔고 결과 rt_cd={rt_cd} msg={msg}")
            if rt_cd != "0":
                log(f"[ERROR] 잔고 조회 실패: {msg}")
                return {"output1": [], "output2": [{}]}
            stocks  = data.get("output1", [])
            summary = data.get("output2", [{}])
            cash    = int(summary[0].get("dnca_tot_amt", 0)) if summary else 0
            log(f"[OK] 예수금: {cash:,}원 / 보유종목: {len(stocks)}개")
            return data
        except Exception as e:
            log(f"[ERROR] 잔고 조회 예외: {e}")
            return {"output1": [], "output2": [{}]}

    def get_daily(self, symbol: str, n: int = 60) -> list:
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
        try:
            r = requests.get(url, headers=self._headers("FHKST01010400"), params=params, timeout=15)
            r.raise_for_status()
            return r.json().get("output2", [])[:n]
        except Exception as e:
            log(f"[WARN] {symbol} 시세 조회 실패: {e}")
            return []

    def place_order(self, symbol: str, order_type: str, price: int, qty: int) -> dict:
        if DRY_RUN:
            log(f"[DRY_RUN] {order_type.upper()} {symbol} {qty}주 @ {price if price else '시장가'}")
            return {"rt_cd": "0", "msg1": "모의주문 완료"}

        url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = "TTTC0802U" if order_type == "buy" else "TTTC0801U"
        body = {
            "CANO": KISTOCK_ACCOUNT[:8],
            "ACNT_PRDT_CD": KISTOCK_ACCOUNT[8:] if len(KISTOCK_ACCOUNT) > 8 else "01",
            "PDNO": symbol,
            "ORD_DVSN": "01" if price == 0 else "00",
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
        }
        try:
            r = requests.post(url, headers=self._headers(tr_id), json=body, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log(f"[ERROR] 주문 실패: {e}")
            return {"rt_cd": "1", "msg1": str(e)}


# ── 기술 지표 ──────────────────────────────────────────────
def calc_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    return round(100 - (100 / (1 + ag/al)), 2)

def calc_sma(prices: list, period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period

def calc_bollinger(prices: list, period: int = 20) -> tuple:
    if len(prices) < period:
        p = prices[-1] if prices else 0
        return p, p, p
    w = prices[-period:]
    mid = sum(w) / period
    std = (sum((x-mid)**2 for x in w) / period) ** 0.5
    return round(mid - 2*std), round(mid), round(mid + 2*std)


# ── 세븐스플릿 신호 ────────────────────────────────────────
def generate_signal(stock: dict, daily_data: list) -> dict:
    prices = [float(d["stck_clpr"]) for d in daily_data if d.get("stck_clpr")]
    prices.reverse()

    current = float(stock.get("prpr", 0))
    avg     = float(stock.get("pchs_avg_pric", current))
    qty     = int(stock.get("hldg_qty", 0))
    rt      = float(stock.get("evlu_pfls_rt", 0))
    split_q = max(1, qty // SPLIT_N)

    rsi   = calc_rsi(prices) if prices else 50.0
    sma20 = calc_sma(prices, 20)
    sma60 = calc_sma(prices, 60)
    bb_lo, bb_mid, bb_hi = calc_bollinger(prices)

    indicators = {"rsi": rsi, "sma20": sma20, "sma60": sma60,
                  "bb_lo": bb_lo, "bb_hi": bb_hi, "rt": rt}

    if rt <= STOP_LOSS_PCT:
        return {"action":"sell","qty":qty,"price":0,
                "reason":f"손절 {rt:.1f}%","indicators":indicators}
    if rt >= 200 and rsi >= RSI_SELL:
        return {"action":"sell","qty":split_q,"price":int(current),
                "reason":f"수익 {rt:.1f}% 분할매도 RSI={rsi}","indicators":indicators}
    if rt >= TAKE_PROFIT and rsi >= RSI_SELL:
        return {"action":"sell","qty":split_q,"price":int(current),
                "reason":f"목표달성 {rt:.1f}% RSI={rsi}","indicators":indicators}
    if rt <= -10 and rsi <= RSI_BUY and prices and current <= bb_lo:
        return {"action":"buy","qty":split_q,"price":int(current),
                "reason":f"분할매수 {rt:.1f}% RSI={rsi} BB하단","indicators":indicators}
    if sma20 > sma60 > 0 and rt < 0:
        return {"action":"buy","qty":split_q,"price":int(current),
                "reason":f"골든크로스 매수 SMA20={sma20:.0f}>SMA60={sma60:.0f}","indicators":indicators}

    return {"action":"hold","qty":0,"price":0,
            "reason":f"홀드 {rt:+.1f}% RSI={rsi}","indicators":indicators}


# ── 카카오 알림 ────────────────────────────────────────────
def send_kakao(message: str):
    if not KAKAO_TOKEN:
        return
    try:
        requests.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            headers={"Authorization": f"Bearer {KAKAO_TOKEN}"},
            data={"template_object": json.dumps({
                "object_type": "text", "text": message,
                "link": {"web_url": "https://github.com/turtler501m-ai/hanstockauto"}
            })}, timeout=10
        )
    except Exception as e:
        log(f"[WARN] 카카오 알림 실패: {e}")


# ── 메인 ──────────────────────────────────────────────────
def run():
    log("=" * 60)
    log(f"세븐스플릿 자동매매 시작 | DRY_RUN={DRY_RUN}")
    log("=" * 60)

    # 1. Secrets 검증
    check_secrets()

    # 2. API 초기화 (토큰 발급)
    api = KIStockAPI()

    # 3. 잔고 조회
    balance  = api.get_balance()
    stocks   = balance.get("output1", [])
    summary  = balance.get("output2", [{}])[0]
    cash     = int(summary.get("dnca_tot_amt", 0))
    tot_evlu = int(summary.get("tot_evlu_amt", 0))
    pnl      = int(summary.get("evlu_pfls_smtl_amt", 0))

    log(f"예수금: {cash:,}원 | 총평가: {tot_evlu:,}원 | 손익: {pnl:+,}원 | 보유: {len(stocks)}종목")

    if not stocks:
        log("[WARN] 보유 종목 없음 — 매매 스킵")
        return

    results = []

    for s in stocks:
        sym  = s.get("pdno", "")
        name = s.get("prdt_name", sym)
        rt   = float(s.get("evlu_pfls_rt", 0))
        log(f"\n--- {name}({sym}) | 수익률 {rt:+.2f}% ---")

        daily  = api.get_daily(sym, n=60)
        signal = generate_signal(s, daily)
        ind    = signal["indicators"]

        log(f"  지표: RSI={ind['rsi']} SMA20={ind['sma20']:.0f} SMA60={ind['sma60']:.0f} BB({ind['bb_lo']:.0f}~{ind['bb_hi']:.0f})")
        log(f"  신호: {signal['action'].upper()} — {signal['reason']}")

        if signal["action"] != "hold":
            if signal["action"] == "buy":
                cost = signal["qty"] * signal["price"]
                if cost > cash:
                    log(f"  [SKIP] 예수금 부족 — 필요 {cost:,}원 / 보유 {cash:,}원")
                    continue

            result = api.place_order(sym, signal["action"], signal["price"], signal["qty"])
            ok     = result.get("rt_cd") == "0"
            log(f"  주문 {'성공' if ok else '실패'}: {result.get('msg1','')}")

            results.append({
                "name": name, "action": signal["action"],
                "qty": signal["qty"], "price": signal["price"],
                "reason": signal["reason"], "ok": ok
            })
            if ok and signal["action"] == "buy":
                cash -= signal["qty"] * signal["price"]
    log("\n" + "=" * 60)
    if results:
        lines = [f"[세븐스플릿] {datetime.now().strftime('%m/%d %H:%M')}"]
        for r in results:
            e = "🟢" if r["action"] == "buy" else "🔴"
            lines.append(f"{e} {r['name']} {r['action'].upper()} {r['qty']}주 ({'성공' if r['ok'] else '실패'})")
            lines.append(f"   {r['reason']}")
        msg = "\n".join(lines)
        log(msg)
        send_kakao(msg)
    else:
        log("전체 종목 홀드 — 액션 없음")

    log("자동매매 완료")


if __name__ == "__main__":
    run()
