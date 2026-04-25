"""
세븐스플릿 자동매매 엔진
KIStock API + 기술지표 기반
"""
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import yfinance as yf

# ── KST 타임존 ────────────────────────────────────────────
KST = timezone(timedelta(hours=9))

# ── 설정 ──────────────────────────────────────────────────
KISTOCK_APP_KEY    = os.environ.get("KISTOCK_APP_KEY", "")
KISTOCK_APP_SECRET = os.environ.get("KISTOCK_APP_SECRET", "")
KISTOCK_ACCOUNT    = os.environ.get("KISTOCK_ACCOUNT", "")
SLACK_WEBHOOK_URL  = os.environ.get("SLACK_WEBHOOK_URL", "")

# 환경: demo(모의) | real(실전)
TRADING_ENV = os.environ.get("TRADING_ENV", "demo")
DRY_RUN     = os.environ.get("DRY_RUN", "true").lower() == "true"

# 세븐스플릿 파라미터
SPLIT_N       = int(os.environ.get("SPLIT_N", "7"))
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "-15"))
TAKE_PROFIT   = float(os.environ.get("TAKE_PROFIT", "30"))
RSI_BUY       = int(os.environ.get("RSI_BUY", "30"))
RSI_SELL      = int(os.environ.get("RSI_SELL", "70"))

# 포지션 사이징
TOTAL_CAPITAL     = float(os.environ.get("TOTAL_CAPITAL", "10000000"))
MAX_POSITIONS     = int(os.environ.get("MAX_POSITIONS", "3"))
MAX_SINGLE_WEIGHT = float(os.environ.get("MAX_SINGLE_WEIGHT", "0.30"))
CASH_BUFFER       = float(os.environ.get("CASH_BUFFER", "0.20"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("MAX_DAILY_LOSS_PCT", "3.0"))

# API URL (모의/실전 자동 분기)
BASE_URL = (
    "https://openapi.koreainvestment.com:9443"
    if TRADING_ENV == "real"
    else "https://openapivts.koreainvestment.com:29443"
)

# 데이터 디렉토리
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 감시 종목 리스트
WATCHLIST = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "035420",  # NAVER
    "035720",  # 카카오
    "005380",  # 현대차
    "207940",  # 삼성바이오로직스
    "068270",  # 셀트리온
    "051910",  # LG화학
]


# ── 로그 ──────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
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


# ── Slack 알림 ─────────────────────────────────────────────
def send_slack(text: str = "", blocks: list = None, color: str = None):
    if not SLACK_WEBHOOK_URL:
        return
    if color and blocks:
        payload = {"attachments": [{"color": color, "blocks": blocks, "fallback": text}]}
    elif blocks:
        payload = {"text": text, "blocks": blocks}
    else:
        payload = {"text": text}
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code != 200:
            log(f"[WARN] Slack 전송 실패 HTTP {r.status_code}: {r.text[:100]}")
    except Exception as e:
        log(f"[WARN] Slack 알림 예외: {e}")


def slack_session_start(cash: int, total: int, stock_count: int):
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    mode = "🔴 실거래" if not DRY_RUN else "🔵 모의실행"
    env_str = "실전 API" if TRADING_ENV == "real" else "모의투자 API"
    send_slack(
        text=f"[세븐스플릿] 자동매매 시작 {now}",
        blocks=[
            {"type": "header",
             "text": {"type": "plain_text", "text": "🤖 세븐스플릿 자동매매 시작", "emoji": True}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*실행 시각*\n{now}"},
                {"type": "mrkdwn", "text": f"*실행 모드*\n{mode}"},
                {"type": "mrkdwn", "text": f"*API 환경*\n{env_str}"},
                {"type": "mrkdwn", "text": f"*예수금*\n{cash:,}원"},
                {"type": "mrkdwn", "text": f"*총 평가금액*\n{total:,}원"},
                {"type": "mrkdwn", "text": f"*보유 종목 수*\n{stock_count}개"},
            ]},
            {"type": "divider"},
        ],
        color="#2196F3"
    )


def slack_order(name: str, symbol: str, action: str, qty: int, price: int,
                reason: str, ok: bool, indicators: dict):
    emoji = "🟢" if action == "buy" else "🔴"
    action_str = "매수" if action == "buy" else "매도"
    status = "✅ 성공" if ok else "❌ 실패"
    color = "#36a64f" if (action == "buy" and ok) else ("#e74c3c" if not ok else "#f0ad4e")
    price_str = f"{price:,}원" if price else "시장가"
    amount_str = f"{qty * price:,}원" if price else "-"
    rsi_val = indicators.get("rsi", "-")
    rsi_str = f"{rsi_val:.1f}" if isinstance(rsi_val, float) else str(rsi_val)
    send_slack(
        text=f"[{action_str}] {name} {qty}주 {status}",
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn",
                "text": f"{emoji} *{name}* (`{symbol}`) — {action_str} {status}"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*수량*\n{qty}주"},
                {"type": "mrkdwn", "text": f"*단가*\n{price_str}"},
                {"type": "mrkdwn", "text": f"*금액*\n{amount_str}"},
                {"type": "mrkdwn", "text": f"*RSI*\n{rsi_str}"},
                {"type": "mrkdwn", "text": f"*SMA20/60*\n{indicators.get('sma20', 0):.0f} / {indicators.get('sma60', 0):.0f}"},
                {"type": "mrkdwn", "text": f"*수익률*\n{indicators.get('rt', 0):+.2f}%"},
            ]},
            {"type": "context",
             "elements": [{"type": "mrkdwn", "text": f"📋 사유: {reason}"}]},
        ],
        color=color
    )


def slack_candidates(candidates: list):
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    lines = [
        f"• *{c['ticker']}* — {c['current_price']:,.0f}원 | 스코어 {c['score']} | {', '.join(c['reasons'])}"
        for c in candidates
    ]
    send_slack(
        text=f"[세븐스플릿] 신규 매수 후보 {len(candidates)}종목",
        blocks=[
            {"type": "header",
             "text": {"type": "plain_text", "text": "🔍 신규 매수 후보 탐색", "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn",
                "text": f"_{now}_\n\n" + "\n".join(lines)}},
        ],
        color="#9C27B0"
    )


def slack_session_end(results: list, cash: int, total: int, pnl: int):
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    buy_cnt  = sum(1 for r in results if r["action"] == "buy"  and r["ok"])
    sell_cnt = sum(1 for r in results if r["action"] == "sell" and r["ok"])
    fail_cnt = sum(1 for r in results if not r["ok"])
    pnl_color = "#36a64f" if pnl >= 0 else "#e74c3c"
    pnl_emoji = "📈" if pnl >= 0 else "📉"

    if not results:
        send_slack(
            text="[세븐스플릿] 전체 종목 홀드 — 액션 없음",
            blocks=[{"type": "section", "text": {"type": "mrkdwn",
                "text": f"⏸️ *전체 종목 홀드* — 매매 신호 없음\n_{now}_"}}],
            color="#9E9E9E"
        )
        return

    lines = []
    for r in results:
        e = "🟢" if r["action"] == "buy" else "🔴"
        st = "✅" if r["ok"] else "❌"
        lines.append(f"{e}{st} {r['name']} {r['action']} {r['qty']}주 — {r['reason']}")

    send_slack(
        text=f"[세븐스플릿] 매매 완료 {now}",
        blocks=[
            {"type": "header",
             "text": {"type": "plain_text", "text": f"{pnl_emoji} 세븐스플릿 매매 완료", "emoji": True}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*완료 시각*\n{now}"},
                {"type": "mrkdwn", "text": f"*총 평가금액*\n{total:,}원"},
                {"type": "mrkdwn", "text": f"*예수금 잔액*\n{cash:,}원"},
                {"type": "mrkdwn", "text": f"*평가 손익*\n{pnl:+,}원"},
                {"type": "mrkdwn", "text": f"*매수 체결*\n{buy_cnt}건"},
                {"type": "mrkdwn", "text": f"*매도 체결*\n{sell_cnt}건"},
            ]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn",
                "text": "*거래 내역*\n" + "\n".join(lines)}},
            *(
                [{"type": "context",
                  "elements": [{"type": "mrkdwn", "text": f"⚠️ 실패 {fail_cnt}건 포함"}]}]
                if fail_cnt else []
            ),
        ],
        color=pnl_color
    )


def slack_error(msg: str):
    send_slack(
        text=f"[오류] {msg}",
        blocks=[{"type": "section", "text": {"type": "mrkdwn",
            "text": f"🚨 *자동매매 오류 발생*\n```{msg}```"}}],
        color="#e74c3c"
    )


# ── SQLite 매매 이력 ───────────────────────────────────────
DB_PATH = DATA_DIR / "trades.db"


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       TEXT    NOT NULL,
                symbol   TEXT    NOT NULL,
                name     TEXT    NOT NULL,
                action   TEXT    NOT NULL,
                qty      INTEGER NOT NULL,
                price    INTEGER NOT NULL,
                reason   TEXT,
                ok       INTEGER NOT NULL,
                env      TEXT,
                dry_run  INTEGER
            )
        """)


def save_trade(symbol: str, name: str, action: str, qty: int, price: int,
               reason: str, ok: bool):
    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO trades "
                "(ts, symbol, name, action, qty, price, reason, ok, env, dry_run) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, symbol, name, action, qty, price, reason,
                 int(ok), TRADING_ENV, int(DRY_RUN))
            )
    except Exception as e:
        log(f"[WARN] 매매 이력 저장 실패: {e}")


# ── KIStock API ────────────────────────────────────────────
class KIStockAPI:
    TOKEN_CACHE = DATA_DIR / "kis_token.json"
    _err_count  = 0   # 서킷 브레이커 카운터
    MAX_ERRORS  = 5

    def __init__(self):
        self.access_token = self._load_or_fetch_token()

    # ── 토큰 관리 ──────────────────────────────────────────
    def _load_or_fetch_token(self) -> str:
        """캐시 파일이 있고 유효하면 재사용, 아니면 새로 발급"""
        if self.TOKEN_CACHE.exists():
            try:
                cached = json.loads(self.TOKEN_CACHE.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(cached["expires_at"])
                if expires_at > datetime.now() + timedelta(minutes=5):
                    log(f"[OK] 토큰 캐시 사용 (만료: {cached['expires_at']})")
                    return cached["token"]
            except Exception:
                pass
        return self._fetch_token()

    def _fetch_token(self) -> str:
        url  = f"{BASE_URL}/oauth2/tokenP"
        body = {"grant_type": "client_credentials",
                "appkey": KISTOCK_APP_KEY, "appsecret": KISTOCK_APP_SECRET}
        log("[API] 토큰 발급 요청 중...")
        try:
            r = requests.post(url, json=body, timeout=15)
            log(f"[API] 토큰 응답 HTTP {r.status_code}")
            r.raise_for_status()
            data  = r.json()
            token = data.get("access_token", "")
            if not token:
                msg = f"토큰 발급 실패 — 응답: {data}"
                log(f"[ERROR] {msg}"); slack_error(msg); sys.exit(1)
            expires_at = datetime.now() + timedelta(hours=23)
            self.TOKEN_CACHE.write_text(
                json.dumps({"token": token, "expires_at": expires_at.isoformat()}),
                encoding="utf-8"
            )
            log(f"[OK] 토큰 발급 성공 (만료: {data.get('access_token_token_expired', '')})")
            return token
        except requests.exceptions.ConnectionError as e:
            msg = f"API 서버 연결 실패: {e}"
            log(f"[ERROR] {msg}"); slack_error(msg); sys.exit(1)
        except requests.exceptions.HTTPError as e:
            msg = f"토큰 발급 HTTP 오류: {e} — {r.text[:300]}"
            log(f"[ERROR] {msg}"); slack_error(msg); sys.exit(1)
        except Exception as e:
            msg = f"토큰 발급 예외: {e}"
            log(f"[ERROR] {msg}"); slack_error(msg); sys.exit(1)

    # ── 공통 헤더 ──────────────────────────────────────────
    def _headers(self, tr_id: str) -> dict:
        return {
            "authorization": f"Bearer {self.access_token}",
            "appkey":        KISTOCK_APP_KEY,
            "appsecret":     KISTOCK_APP_SECRET,
            "tr_id":         tr_id,
            "custtype":      "P",
            "Content-Type":  "application/json",
        }

    def _hashkey(self, payload: dict) -> str:
        """주문 보안을 위한 HashKey 생성"""
        try:
            resp = requests.post(
                f"{BASE_URL}/uapi/hashkey",
                headers={"content-type": "application/json",
                         "appkey": KISTOCK_APP_KEY, "appsecret": KISTOCK_APP_SECRET},
                json=payload, timeout=10
            )
            return resp.json().get("HASH", "")
        except Exception as e:
            log(f"[WARN] HashKey 생성 실패: {e}")
            return ""

    def _check_circuit(self):
        """API 오류 누적 시 서킷 브레이커 작동"""
        if self.__class__._err_count >= self.MAX_ERRORS:
            msg = f"API 오류 {self.__class__._err_count}회 연속 — 서킷 브레이커 작동"
            log(f"[ERROR] {msg}"); slack_error(msg); sys.exit(1)

    def _ok(self):
        self.__class__._err_count = 0

    def _fail(self):
        self.__class__._err_count += 1

    # ── 잔고 조회 ──────────────────────────────────────────
    def get_balance(self) -> dict:
        self._check_circuit()
        tr_id = "VTTC8434R" if TRADING_ENV == "demo" else "TTTC8434R"
        url   = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
        cano  = KISTOCK_ACCOUNT[:8]
        acnt  = KISTOCK_ACCOUNT[8:] if len(KISTOCK_ACCOUNT) > 8 else "01"
        params = {
            "CANO": cano, "ACNT_PRDT_CD": acnt,
            "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
            "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
        }
        log(f"[API] 잔고 조회 (계좌: {cano}-{acnt}, env={TRADING_ENV})")
        try:
            r = requests.get(url, headers=self._headers(tr_id), params=params, timeout=15)
            log(f"[API] 잔고 응답 HTTP {r.status_code}")
            r.raise_for_status()
            data  = r.json()
            rt_cd = data.get("rt_cd", "?")
            msg   = data.get("msg1", "")
            log(f"[API] 잔고 결과 rt_cd={rt_cd} msg={msg}")
            if rt_cd != "0":
                log(f"[ERROR] 잔고 조회 실패: {msg}")
                self._fail()
                return {"output1": [], "output2": [{}]}
            self._ok()
            stocks  = data.get("output1", [])
            summary = data.get("output2", [{}])
            cash    = int(summary[0].get("dnca_tot_amt", 0)) if summary else 0
            log(f"[OK] 예수금: {cash:,}원 / 보유종목: {len(stocks)}개")
            return data
        except Exception as e:
            log(f"[ERROR] 잔고 조회 예외: {e}")
            self._fail()
            return {"output1": [], "output2": [{}]}

    # ── 현재가 조회 (매도호가 포함) ────────────────────────
    def get_quote(self, symbol: str) -> dict:
        self._check_circuit()
        try:
            r = requests.get(
                f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
                headers=self._headers("FHKST01010100"),
                params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
                timeout=10,
            )
            output = r.json().get("output", {})
            self._ok()
            return {
                "current": float(output.get("stck_prpr", 0)),
                "ask1":    float(output.get("askp1", 0)),
                "bid1":    float(output.get("bidp1", 0)),
            }
        except Exception as e:
            log(f"[WARN] {symbol} 현재가 조회 실패: {e}")
            self._fail()
            return {"current": 0, "ask1": 0, "bid1": 0}

    # ── 일봉 시세 조회 ─────────────────────────────────────
    ETF_MARKET_CODES = {
        "102110", "133690", "148020", "152100", "157490",
        "229200", "251340", "261240", "273130", "278530",
        "305720", "381170", "448290", "481190",
    }

    def get_daily(self, symbol: str, n: int = 60) -> list:
        self._check_circuit()
        url   = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        today = datetime.now(KST).strftime("%Y%m%d")
        start = (datetime.now(KST) - timedelta(days=365 * 3)).strftime("%Y%m%d")
        mrkt_div = "E" if symbol in self.ETF_MARKET_CODES else "J"
        params = {
            "FID_COND_MRKT_DIV_CODE": mrkt_div,
            "FID_INPUT_ISCD":         symbol,
            "FID_INPUT_DATE_1":       start,
            "FID_INPUT_DATE_2":       today,
            "FID_PERIOD_DIV_CODE":    "D",
            "FID_ORG_ADJ_PRC":        "0",
        }
        try:
            r = requests.get(url, headers=self._headers("FHKST03010100"), params=params, timeout=15)
            log(f"[API] {symbol}({mrkt_div}) 시세 HTTP {r.status_code}")
            if r.status_code != 200:
                log(f"[WARN] {symbol} 시세 오류: {r.text[:200]}")
                self._fail(); return []
            data  = r.json()
            rt_cd = data.get("rt_cd", "?")
            if rt_cd != "0":
                log(f"[WARN] {symbol} 시세 rt_cd={rt_cd} msg={data.get('msg1','')}")
                self._fail(); return []
            self._ok()
            output = data.get("output2", [])
            log(f"[OK] {symbol} 시세 {len(output)}일치 수신")
            return output[:n]
        except Exception as e:
            log(f"[WARN] {symbol} 시세 조회 예외: {e}")
            self._fail(); return []

    # ── 주문 ───────────────────────────────────────────────
    def place_order(self, symbol: str, order_type: str, price: int, qty: int) -> dict:
        if DRY_RUN:
            log(f"[DRY_RUN] {order_type.upper()} {symbol} {qty}주 @ {price if price else '시장가'}")
            return {"rt_cd": "0", "msg1": "모의주문 완료"}

        is_demo = TRADING_ENV == "demo"
        tr_id = ("VTTC0802U" if is_demo else "TTTC0802U") if order_type == "buy" \
                else ("VTTC0801U" if is_demo else "TTTC0801U")

        url  = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
        body = {
            "CANO":        KISTOCK_ACCOUNT[:8],
            "ACNT_PRDT_CD": KISTOCK_ACCOUNT[8:] if len(KISTOCK_ACCOUNT) > 8 else "01",
            "PDNO":        symbol,
            "ORD_DVSN":    "01" if price == 0 else "00",
            "ORD_QTY":     str(qty),
            "ORD_UNPR":    str(price),
        }
        headers = self._headers(tr_id)
        hashkey = self._hashkey(body)
        if hashkey:
            headers["hashkey"] = hashkey

        self._check_circuit()
        try:
            r = requests.post(url, headers=headers, json=body, timeout=15)
            r.raise_for_status()
            self._ok()
            return r.json()
        except Exception as e:
            log(f"[ERROR] 주문 실패: {e}")
            self._fail()
            return {"rt_cd": "1", "msg1": str(e)}


# ── 기술 지표 ──────────────────────────────────────────────
def calc_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    return round(100 - (100 / (1 + ag / al)), 2)


def calc_sma(prices: list, period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period


def calc_bollinger(prices: list, period: int = 20) -> tuple:
    if len(prices) < period:
        p = prices[-1] if prices else 0
        return p, p, p
    w   = prices[-period:]
    mid = sum(w) / period
    std = (sum((x - mid) ** 2 for x in w) / period) ** 0.5
    return round(mid - 2 * std), round(mid), round(mid + 2 * std)


# ── 신규 매수 후보 탐색 (WATCHLIST + yfinance) ─────────────
def find_candidates(held_symbols: set, min_score: int = 2) -> list:
    """WATCHLIST에서 아직 보유하지 않은 종목 중 매수 후보 탐색"""
    candidates = []
    for code in WATCHLIST:
        if code in held_symbols:
            continue
        try:
            df = yf.download(f"{code}.KS", period="3mo", progress=False, auto_adjust=True)
            if df.empty or len(df) < 30:
                log(f"[WARN] {code} yfinance 데이터 부족 — 스킵")
                continue

            closes  = df["Close"].squeeze()
            volumes = df["Volume"].squeeze()
            current = float(closes.iloc[-1])
            score, reasons = 0, []

            # RSI 30~50: 과매도 회복 구간
            rsi = calc_rsi(closes.tolist())
            if 30 < rsi < 50:
                score += 1
                reasons.append(f"RSI {rsi:.0f}")

            # 5일선 돌파
            ma5 = closes.rolling(5).mean()
            if current > float(ma5.iloc[-1]) and float(closes.iloc[-2]) <= float(ma5.iloc[-2]):
                score += 1
                reasons.append("5일선 돌파")

            # 거래량 급증 (20일 평균 1.5배 이상)
            vol_avg = float(volumes.rolling(20).mean().iloc[-1])
            if float(volumes.iloc[-1]) > vol_avg * 1.5:
                score += 1
                reasons.append("거래량 급증")

            if score >= min_score:
                candidates.append({
                    "ticker": code, "current_price": current,
                    "score": score, "reasons": reasons,
                })
                log(f"[후보] {code} 스코어={score} ({', '.join(reasons)})")

        except Exception as e:
            log(f"[WARN] {code} 후보 분석 실패: {e}")

    candidates.sort(key=lambda x: -x["score"])
    return candidates


# ── 포지션 사이징 (신규 매수 주문 계산) ───────────────────
def build_orders(candidates: list, get_quote_fn, held_count: int, cash: int) -> list:
    available_slots = MAX_POSITIONS - held_count
    if available_slots <= 0:
        log(f"[INFO] 최대 보유 종목 수({MAX_POSITIONS}) 도달 — 신규 매수 없음")
        return []

    deployable   = TOTAL_CAPITAL * (1 - CASH_BUFFER)
    per_position = deployable * MAX_SINGLE_WEIGHT
    cost_mult    = 1.001  # 수수료 여유

    orders = []
    for c in candidates[:available_slots]:
        quote = get_quote_fn(c["ticker"])
        price = int(quote["ask1"] or quote["current"])
        if price <= 0:
            continue
        qty = math.floor(per_position / (price * cost_mult))
        if qty <= 0:
            continue
        orders.append({
            "ticker":         c["ticker"],
            "quantity":       qty,
            "limit_price":    price,
            "estimated_cost": qty * price * cost_mult,
            "score":          c["score"],
            "reasons":        c["reasons"],
        })

    # 총 비용이 운용 가능 자본 또는 예수금 초과 시 비례 축소
    total_cost = sum(o["estimated_cost"] for o in orders)
    budget = min(deployable, cash)
    if total_cost > budget and budget > 0:
        scale = budget / total_cost
        for o in orders:
            o["quantity"] = math.floor(o["quantity"] * scale)
            o["estimated_cost"] = o["quantity"] * o["limit_price"] * cost_mult

    return [o for o in orders if o["quantity"] > 0]


# ── 세븐스플릿 신호 (보유 종목) ───────────────────────────
def generate_signal(stock: dict, daily_data: list) -> dict:
    prices = [float(d["stck_clpr"]) for d in daily_data if d.get("stck_clpr")]
    prices.reverse()

    current = float(stock.get("prpr", 0))
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
        return {"action": "sell", "qty": qty, "price": 0,
                "reason": f"손절 {rt:.1f}%", "indicators": indicators}
    if rt >= 200 and rsi >= RSI_SELL:
        return {"action": "sell", "qty": split_q, "price": int(current),
                "reason": f"수익 {rt:.1f}% 분할매도 RSI={rsi}", "indicators": indicators}
    if rt >= TAKE_PROFIT and rsi >= RSI_SELL:
        return {"action": "sell", "qty": split_q, "price": int(current),
                "reason": f"목표달성 {rt:.1f}% RSI={rsi}", "indicators": indicators}
    if rt <= -10 and rsi <= RSI_BUY and prices and current <= bb_lo:
        return {"action": "buy", "qty": split_q, "price": int(current),
                "reason": f"분할매수 {rt:.1f}% RSI={rsi} BB하단", "indicators": indicators}
    if sma20 > sma60 > 0 and rt < 0:
        return {"action": "buy", "qty": split_q, "price": int(current),
                "reason": f"골든크로스 매수 SMA20={sma20:.0f}>SMA60={sma60:.0f}", "indicators": indicators}

    return {"action": "hold", "qty": 0, "price": 0,
            "reason": f"홀드 {rt:+.1f}% RSI={rsi}", "indicators": indicators}


# ── 일일 손실 한도 체크 ────────────────────────────────────
def check_daily_loss(pnl: int) -> bool:
    """당일 손실이 MAX_DAILY_LOSS_PCT 이상이면 신규 매수 중단"""
    if TOTAL_CAPITAL <= 0 or pnl >= 0:
        return False
    loss_pct = abs(pnl) / TOTAL_CAPITAL * 100
    if loss_pct >= MAX_DAILY_LOSS_PCT:
        msg = f"일일 손실 한도 도달 — 손실 {loss_pct:.1f}% ≥ {MAX_DAILY_LOSS_PCT}% (신규 매수 중단)"
        log(f"[WARN] {msg}")
        slack_error(msg)
        return True
    return False


# ── 메인 ──────────────────────────────────────────────────
def run():
    log("=" * 60)
    log(f"세븐스플릿 자동매매 시작 | DRY_RUN={DRY_RUN} | ENV={TRADING_ENV}")
    log("=" * 60)

    check_secrets()
    init_db()

    api = KIStockAPI()

    # 잔고 조회
    balance  = api.get_balance()
    stocks   = balance.get("output1", [])
    summary  = balance.get("output2", [{}])[0]
    cash     = int(summary.get("dnca_tot_amt", 0))
    tot_evlu = int(summary.get("tot_evlu_amt", 0))
    pnl      = int(summary.get("evlu_pfls_smtl_amt", 0))

    log(f"예수금: {cash:,}원 | 총평가: {tot_evlu:,}원 | 손익: {pnl:+,}원 | 보유: {len(stocks)}종목")

    slack_session_start(cash=cash, total=tot_evlu, stock_count=len(stocks))

    daily_loss_halt = check_daily_loss(pnl)
    results = []

    # ── 1단계: 보유 종목 세븐스플릿 신호 처리 ─────────────
    held_symbols: set = set()

    for s in stocks:
        sym  = s.get("pdno", "")
        name = s.get("prdt_name", sym)
        rt   = float(s.get("evlu_pfls_rt", 0))
        held_symbols.add(sym)
        log(f"\n--- {name}({sym}) | 수익률 {rt:+.2f}% ---")

        daily  = api.get_daily(sym, n=60)
        signal = generate_signal(s, daily)
        ind    = signal["indicators"]

        log(f"  지표: RSI={ind['rsi']} SMA20={ind['sma20']:.0f} SMA60={ind['sma60']:.0f} "
            f"BB({ind['bb_lo']:.0f}~{ind['bb_hi']:.0f})")
        log(f"  신호: {signal['action'].upper()} — {signal['reason']}")

        if signal["action"] == "hold":
            continue

        if signal["action"] == "buy":
            if daily_loss_halt:
                log("  [SKIP] 일일 손실 한도 초과 — 매수 중단")
                continue
            cost = signal["qty"] * signal["price"]
            if cost > cash:
                log(f"  [SKIP] 예수금 부족 — 필요 {cost:,}원 / 보유 {cash:,}원")
                continue

        result = api.place_order(sym, signal["action"], signal["price"], signal["qty"])
        ok     = result.get("rt_cd") == "0"
        log(f"  주문 {'성공' if ok else '실패'}: {result.get('msg1', '')}")

        save_trade(sym, name, signal["action"], signal["qty"], signal["price"],
                   signal["reason"], ok)

        results.append({
            "name": name, "symbol": sym, "action": signal["action"],
            "qty": signal["qty"], "price": signal["price"],
            "reason": signal["reason"], "ok": ok, "indicators": ind,
        })

        slack_order(name=name, symbol=sym, action=signal["action"],
                    qty=signal["qty"], price=signal["price"],
                    reason=signal["reason"], ok=ok, indicators=ind)

        if ok and signal["action"] == "buy":
            cash -= signal["qty"] * signal["price"]

    # ── 2단계: WATCHLIST 신규 매수 후보 탐색 ──────────────
    if not daily_loss_halt:
        log("\n--- WATCHLIST 신규 매수 후보 탐색 ---")
        candidates = find_candidates(held_symbols)

        if candidates:
            slack_candidates(candidates)
            new_orders = build_orders(candidates, api.get_quote, len(held_symbols), cash)

            for o in new_orders:
                sym    = o["ticker"]
                qty    = o["quantity"]
                price  = o["limit_price"]
                reason = f"신규매수 스코어={o['score']} ({', '.join(o['reasons'])})"
                log(f"\n--- 신규매수 {sym} {qty}주 @ {price:,}원 ---")
                log(f"  사유: {reason}")

                result = api.place_order(sym, "buy", price, qty)
                ok     = result.get("rt_cd") == "0"
                log(f"  주문 {'성공' if ok else '실패'}: {result.get('msg1', '')}")

                save_trade(sym, sym, "buy", qty, price, reason, ok)

                ind = {"rsi": "-", "sma20": 0, "sma60": 0, "rt": 0}
                results.append({
                    "name": sym, "symbol": sym, "action": "buy",
                    "qty": qty, "price": price, "reason": reason,
                    "ok": ok, "indicators": ind,
                })

                slack_order(name=sym, symbol=sym, action="buy", qty=qty, price=price,
                            reason=reason, ok=ok, indicators=ind)

                if ok:
                    cash -= qty * price
        else:
            log("[INFO] 신규 매수 후보 없음")

    # ── 세션 종료 ──────────────────────────────────────────
    log("\n" + "=" * 60)
    if not results:
        log("전체 종목 홀드 — 액션 없음")

    slack_session_end(results=results, cash=cash, total=tot_evlu, pnl=pnl)
    log("자동매매 완료")


if __name__ == "__main__":
    run()
