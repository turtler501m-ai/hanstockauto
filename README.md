# Seven Split Auto Trading

한국투자증권 KIS Open API 기반 국내 주식 자동매매 및 대시보드 프로젝트입니다. 보유 종목을 분할매수/분할매도 규칙으로 관리하고, 기술적 지표로 관심 종목을 스캔하며, 거래 이력은 SQLite에 저장합니다. FastAPI 대시보드에서 계좌, 승인 대기 주문, 전략 후보, 성과, 리스크 상태를 확인할 수 있습니다.

## 주요 기능

- KIS Open API 토큰 캐싱
- 계좌 잔고, 현재가, 일봉 차트, 현금 주문 API 연동
- RSI, SMA, Bollinger Band 기반 신호 생성
- 분할매수, 분할매도, 손절, 익절 규칙
- 포지션 비중, 현금 버퍼, 일일 손실 제한
- 주문 승인 대기열 및 대시보드 승인 처리
- SQLite 거래 이력 저장
- Slack 알림
- FastAPI 웹 대시보드
- GitHub Actions 예약 실행

## 실행 일정

GitHub Actions cron은 UTC 기준입니다.

| KST | 작업 |
| --- | --- |
| 08:50 | 장전 스캔 |
| 10:00 | 오전 장중 점검 |
| 13:00 | 오후 장중 점검 |
| 15:00 | 장마감 전 점검 |

## 로컬 준비

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

`.env` 파일에 KIS API 키, 계좌번호, 매매 모드 등을 설정합니다.

## 필수 환경 변수

| 이름 | 설명 |
| --- | --- |
| `KISTOCK_APP_KEY` | KIS Open API App Key |
| `KISTOCK_APP_SECRET` | KIS Open API App Secret |
| `KISTOCK_ACCOUNT` | 계좌번호 8자리 또는 계좌번호 8자리 + 상품코드 2자리, 예: `12345678` 또는 `1234567801` |

## 주요 설정값

| 이름 | 기본값 | 설명 |
| --- | --- | --- |
| `TRADING_ENV` | `demo` | `demo` 또는 `real` |
| `DRY_RUN` | `true` | `true`이면 실제 주문 제출 차단 |
| `ENABLE_LIVE_TRADING` | `false` | 실전 매매 최종 허용 스위치 |
| `REQUIRE_APPROVAL` | `true` | 주문 전 대시보드 승인 요구 |
| `SPLIT_N` | `7` | 분할 주문 기준 |
| `STOP_LOSS_PCT` | `-15` | 손절 수익률 기준 |
| `TAKE_PROFIT` | `30` | 익절 수익률 기준 |
| `RSI_BUY` | `30` | RSI 매수 기준 |
| `RSI_SELL` | `70` | RSI 매도 기준 |
| `TOTAL_CAPITAL` | `10000000` | 기준 운용 금액 |
| `MAX_POSITIONS` | `3` | 최대 보유 종목 수 |
| `MAX_SINGLE_WEIGHT` | `0.30` | 단일 종목 최대 비중 |
| `CASH_BUFFER` | `0.20` | 현금 보유 비율 |
| `MAX_DAILY_LOSS_PCT` | `3.0` | 일일 손실 중단 기준 |
| `SLACK_WEBHOOK_URL` | 빈 값 | Slack 알림 Webhook URL |
| `BALANCE_FETCH_TIMEOUT_SECONDS` | `25` | 대시보드 잔고 조회 서버 timeout |

## 대시보드 실행

Windows에서는 Git Bash 대신 `server.cmd` 사용을 권장합니다. 백그라운드에서 `uvicorn --reload`로 실행되므로, 대부분의 Python 코드 수정은 자동 반영됩니다.

```powershell
.\server.cmd restart
```

브라우저에서 접속:

```text
http://127.0.0.1:8000
```

자주 쓰는 명령:

```powershell
.\server.cmd start
.\server.cmd stop
.\server.cmd restart
.\server.cmd status
.\server.cmd logs
.\server.cmd tail
```

명령 설명:

| 명령 | 설명 |
| --- | --- |
| `start` | 서버가 꺼져 있으면 백그라운드로 시작 |
| `stop` | 8000 포트의 대시보드 서버 종료 |
| `restart` | 기존 서버 종료 후 다시 시작 |
| `status` | 실행 여부와 PID 확인 |
| `logs` | 서버 로그 최근 80줄 확인 |
| `logs -Lines 200` | 서버 로그 최근 200줄 확인 |
| `tail` | 서버 로그 실시간 보기. `Ctrl+C`를 눌러도 서버는 계속 실행됨 |

## 자동 반영 기준

- `.py` 파일 수정: `--reload`가 감지하여 자동 재시작
- `web/static/js`, `web/templates`, CSS 수정: 브라우저 새로고침으로 반영
- `.env`, 설치 패키지, 포트, 실행 옵션 변경: `.\server.cmd restart` 필요

잔고 조회는 KIS 응답이 느릴 수 있어 서버 timeout 기본값을 25초로 둡니다. 브라우저의 `/api/balance` 요청도 30초까지 기다립니다.

## 매매 엔진 실행

대시보드와 별도로 매매 엔진을 직접 실행할 수 있습니다.

```powershell
python src\trader.py
```

## 주문 안전장치

실전 주문은 아래 조건이 모두 만족될 때만 제출됩니다.

- `DRY_RUN=false`
- `TRADING_ENV=real`
- `ENABLE_LIVE_TRADING=true`

모의투자 주문은 `TRADING_ENV=demo`이고 `DRY_RUN=false`일 때 제출됩니다. `DRY_RUN=true`이면 주문은 기록만 되고 KIS 주문 API로 제출되지 않습니다.

`REQUIRE_APPROVAL=true`이면 전략이 만든 주문은 즉시 제출되지 않고 승인 대기열에 들어갑니다. 대시보드에서 승인해야 주문 처리 단계로 넘어갑니다.

## KIS 호출 제한 대응

KIS API가 `EGW00201` 초당 거래건수 초과를 반환하면 재시도 폭주를 막기 위해 해당 오류는 즉시 중단 처리합니다. 대시보드는 사용 가능한 잔고 캐시가 있으면 캐시를 보여주고, 캐시가 없으면 `/api/balance`에서 `429` 응답을 반환합니다.

잔고 조회는 짧은 시간 안에 반복 호출되지 않도록 내부 스로틀과 캐시를 사용합니다.

KIS 계좌 설정을 점검하려면 아래 명령을 실행합니다. 계좌와 키 길이만 마스킹해서 보여주고, 토큰 발급 및 잔고 조회 결과를 확인합니다.

```powershell
python tools\check-kis-account.py
```

`ERROR : INPUT INVALID_CHECK_ACNO`가 나오면 로컬 형식 오류보다는 KIS Developers의 App Key와 모의/실전 계좌 연결, `TRADING_ENV`와 계좌 종류의 일치 여부, 계좌 상품코드 2자리를 확인해야 합니다.

## 로컬 점검

```powershell
powershell -ExecutionPolicy Bypass -File tools\verify-local.ps1
```

개별 테스트 실행 예:

```powershell
python -m unittest discover -s tests
```

## 주의

이 프로젝트는 자동매매 구현 템플릿입니다. API 장애, 네트워크 지연, 잘못된 시장 데이터, 로직 오류, 급격한 가격 변동으로 손실이 발생할 수 있습니다. 실전 자금을 사용하기 전에 반드시 모의투자 환경에서 충분히 검증하세요.
