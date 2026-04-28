# HanStockAuto 개선안 상세 분석

## 개요

현재 프로젝트는 KIS Open API 기반 국내 주식 자동매매 엔진, SQLite 거래 기록, Slack 알림, FastAPI 대시보드, 후보 종목 스캔 및 AI/포트폴리오 비중 계산 기능을 함께 가진 구조다. 기본적인 모듈 분리는 이미 되어 있지만, 실제 운영 관점에서는 몇 가지 실행 차단 이슈와 안전장치 미완성, 대시보드 라우팅 중복, 테스트/실행환경 불안정성이 남아 있다.

이 문서는 현재 코드 기준으로 개선 우선순위와 구체적인 조치 방향을 정리한다.

## 현재 구조 요약

| 영역 | 주요 파일 | 역할 |
| --- | --- | --- |
| 실행 엔진 | `src/trader.py` | 잔고 조회, 보유 종목 신호 계산, 신규 후보 스캔, 주문 실행, 알림/DB 기록 |
| KIS 연동 | `src/api/kis_api.py` | 토큰 캐시, 잔고/시세/일봉/거래량/주문 API |
| 전략 | `src/strategy/seven_split.py` | 7분할 매매, RSI/MACD/SMA/Bollinger 점수화, 후보 스캔, AI 비중 계산 |
| 지표 | `src/strategy/indicators.py` | RSI, SMA, MACD, Bollinger 계산 |
| 저장소 | `src/db/repository.py` | SQLite 초기화 및 거래 저장, JSON export |
| 알림 | `src/notifier/slack.py` | Slack 세션/주문/후보/오류 알림 |
| 대시보드 | `src/dashboard.py`, `web/` | FastAPI API, HTML/CSS/JS UI |
| 테스트 | `tests/test_trader_core.py` | 전략 핵심 로직 및 일부 API 상태 테스트 |
| 운영 | `.github/workflows/*` | GitHub Actions 스케줄 실행 및 거래 기록 브랜치 반영 |

## 우선순위 0: 실행 차단 가능성이 높은 결함

### 1. `/api/trades` 라우트 중복

위치:

- `src/dashboard.py`의 첫 번째 `@app.get("/api/trades")`
- 같은 파일 하단의 두 번째 `@app.get("/api/trades")`

문제:

- 동일 경로가 두 번 등록되어 동작이 불명확하다.
- 유지보수자가 어느 함수가 실제 응답을 담당하는지 혼동하기 쉽다.
- 첫 번째 구현은 SQLite 조회 중심이고, 두 번째 구현은 cloud trades fetch + fallback + 디버그 파일 쓰기를 포함한다.

개선안:

- 하나의 `/api/trades`만 남긴다.
- cloud trades 조회는 별도 함수로 유지하되, 실패 시 SQLite fallback을 명확히 한다.
- 디버그 파일 `out.txt` 기록은 제거한다.
- 필요하면 `/api/trades/cloud`와 `/api/trades/local`을 분리한다.

권장 순서:

1. 중복 라우트 제거
2. 공통 응답 스키마 정리
3. 프론트엔드 `renderTrades()`가 기대하는 필드(`ts`, `action`, `name`, `symbol`, `price`, `qty`, `reason`, `ok`) 보장

### 2. `save_trade()` 호출 인자 불일치

위치:

- 정의: `src/db/repository.py`
- 문제 호출: `src/dashboard.py`의 승인 주문 실행 흐름

문제:

`save_trade()` 정의는 다음 인자를 요구한다.

```python
save_trade(symbol, name, action, qty, price, reason, ok, order_submission_enabled)
```

하지만 대시보드 승인 주문 처리에서는 마지막 인자를 넘기지 않는다. 승인 주문이 실제로 실행되는 경로에서 `TypeError`가 발생할 수 있다.

개선안:

- `trader.ORDER_SUBMISSION_ENABLED`를 명시적으로 전달한다.
- 또는 `save_trade()`에 기본값을 둔다.

권장:

```python
trader.save_trade(
    item["symbol"],
    item["name"],
    item["action"],
    item["qty"],
    item["price"],
    item["reason"],
    ok,
    trader.ORDER_SUBMISSION_ENABLED,
)
```

### 3. 서킷브레이커 구현과 테스트 불일치

위치:

- `src/api/kis_api.py`
- `tests/test_trader_core.py`

문제:

- `KIStockAPI.circuit_status()`는 항상 `opened=False`를 반환한다.
- `reset_circuit()`은 `pass`다.
- 테스트는 `_fail()` 메서드와 에러 카운트 누적을 기대한다.

영향:

- API 장애가 반복되어도 실제로 차단되지 않는다.
- 테스트 기대와 구현이 맞지 않아 회귀 검증 신뢰도가 떨어진다.
- 자동매매 시스템에서 외부 API 장애 시 주문/조회 반복이 계속될 수 있다.

개선안:

- `_fail()`, `_success()`, `_check_circuit()` 구현
- `kis_circuit_cooldown_seconds` 설정 활용
- 실패 횟수와 opened timestamp를 클래스 변수로 관리
- API 메서드 공통 wrapper 또는 명시적 try/except에서 실패 기록

권장 동작:

- 연속 실패 `MAX_ERRORS` 이상이면 opened
- cooldown 전에는 API 호출 차단
- cooldown 이후 첫 호출 허용 또는 half-open 상태로 전환
- 성공 시 카운터 리셋

## 우선순위 1: 주문 안전성과 운영 안정성

### 4. 필수 환경변수 검증 미완성

위치:

- `src/trader.py`의 `check_secrets()`
- `src/dashboard.py`의 `_required_env_missing()`

문제:

- 대시보드는 필수 환경변수 누락을 확인하지만, 실제 트레이딩 엔진은 `check_secrets()`가 비어 있다.
- GitHub Actions나 로컬 실행에서 키 누락 시 API 호출 단계에서 실패한다.

개선안:

- `trader.run()` 시작 직후 `check_secrets()` 호출
- 필수값: `KISTOCK_APP_KEY`, `KISTOCK_APP_SECRET`, `KISTOCK_ACCOUNT`
- 실전 주문 조건에서는 `ENABLE_LIVE_TRADING`과 `DRY_RUN` 상태를 로그와 Slack에 더 명확히 표시

권장 정책:

- demo/real 모두 KIS credentials 누락 시 즉시 중단
- `TRADING_ENV=real`이고 `DRY_RUN=false`일 때는 추가 승인 플래그 필수

### 5. 승인 큐와 자동 주문 흐름의 경계 정리

문제:

- `trader.run()`은 후보 주문을 바로 `place_order()`로 보낸다.
- 대시보드는 승인 큐를 제공한다.
- `REQUIRE_APPROVAL` 설정은 존재하지만 실제 주문 흐름에 충분히 반영되어 있지 않다.

개선안:

- `REQUIRE_APPROVAL=true`일 때는 신규 매수 후보와 AI/optimizer 주문을 승인 큐에만 넣는다.
- 보유 종목 stop-loss 같은 긴급 매도는 정책을 분리한다.
- 자동 실행과 수동 승인 실행의 기록 포맷을 통일한다.

권장 정책 예시:

| 주문 유형 | REQUIRE_APPROVAL=true | REQUIRE_APPROVAL=false |
| --- | --- | --- |
| 손절 매도 | 즉시 실행 또는 별도 긴급 정책 | 즉시 실행 |
| 익절 매도 | 승인 큐 | 즉시 실행 |
| 물타기/분할 매수 | 승인 큐 | 즉시 실행 |
| 신규 후보 매수 | 승인 큐 | 즉시 실행 |
| AI 리밸런싱 | 승인 큐 | 승인 큐 권장 |

### 6. 현금/수량 계산의 보수성 강화

현재:

- 후보 주문은 `TOTAL_CAPITAL`, `CASH_BUFFER`, `MAX_SINGLE_WEIGHT` 기반으로 수량을 산정한다.
- 주문 비용이 예산을 초과하면 비율로 축소한다.

개선안:

- 매수 주문마다 수수료/세금/호가 단위/최소 주문 가능 금액 고려
- 현재 잔고 현금 기준을 더 강하게 적용
- 이미 보유한 종목의 추가 매수 시 단일 종목 최대 비중 재계산
- 주문 전 최종 quote 재조회

## 우선순위 2: 대시보드 품질 개선

### 7. API 요청 중 `git fetch` 수행 제거

위치:

- `src/dashboard.py`의 `fetch_cloud_trades()`

문제:

- 웹 요청 처리 중 `git fetch`와 `git show`를 실행한다.
- 요청 지연, git lock, 네트워크 실패, 권한 문제를 유발한다.
- 동시 요청 시 불안정할 수 있어 10초 캐시가 있지만 근본 해결은 아니다.

개선안:

- cloud trades 동기화는 별도 스케줄 작업으로 분리
- 대시보드는 로컬 캐시 파일 또는 SQLite만 읽기
- 실패 시 마지막 정상 캐시를 반환하고 상태 정보를 함께 제공

권장 구조:

```text
scheduled sync job
  -> git fetch/show
  -> data/cloud_trades_cache.json

dashboard request
  -> read cache
  -> fallback sqlite
```

### 8. 대시보드 HTML/JS 인코딩과 문구 관리

현재 확인:

- 파일 자체는 UTF-8이다.
- Windows PowerShell 5.1에서 `Get-Content` 기본 읽기 시 깨져 보인다.
- `.editorconfig`, `.gitattributes`, `tools/check-encoding.ps1`, `.doc/encoding-check.md`를 추가했다.

추가 개선안:

- UI 문구를 JS 객체 또는 별도 JSON으로 분리
- 브라우저에서 실제 렌더링을 기준으로 점검
- PowerShell에서는 `Get-Content -Encoding UTF8` 사용
- CI에 `tools/check-encoding.ps1` 또는 유사한 UTF-8 검사 추가

### 9. 프론트엔드 오류 처리 정리

문제:

- API 실패 메시지가 그대로 테이블에 표시된다.
- 일부 버튼은 실패 후 disabled 상태 복구가 일관되지 않을 수 있다.
- 자동 refresh와 수동 요청이 겹칠 때 UI 상태가 섞일 수 있다.

개선안:

- fetch helper에서 표준 에러 객체 사용
- 버튼 busy 상태와 자동 refresh 상태 분리
- API별 loading, empty, error 상태 컴포넌트화
- `/api/health` 결과에 따라 위험한 버튼 비활성화

## 우선순위 3: 전략/데이터 품질 개선

### 10. yfinance 의존 후보 스캔의 불확실성

현재:

- KIS 거래량 순위로 universe를 얻고, yfinance로 9개월 데이터를 다운로드한다.
- yfinance 실패 시 후보가 0개가 된다.

문제:

- yfinance는 한국 종목 데이터가 지연/누락/장애일 수 있다.
- 자동매매 판단의 핵심 데이터가 KIS와 yfinance로 분리되어 있다.

개선안:

- 후보 스캔도 KIS daily API 중심으로 전환하거나 캐시 계층 추가
- yfinance는 보조 데이터로만 사용
- 후보 스캔 결과에 `data_source`, `data_age`, `scan_error`를 명확히 포함
- 실패한 종목 목록을 로그에 요약

### 11. 전략 파라미터와 백테스트 연결

현재:

- RSI, MACD, SMA, Bollinger, volume breakout을 점수화한다.
- 백테스트 체계는 문서상 필요성이 언급되어 있지만 실제 자동 검증 흐름은 부족하다.

개선안:

- `src/backtest.py` 또는 `tests/backtest_fixture` 추가
- 전략 파라미터 변경 시 과거 데이터 기준 성과 비교
- 수익률뿐 아니라 MDD, 승률, 평균 손익비, 거래 횟수, turnover 측정
- 후보 스캔 점수별 결과를 저장해 threshold를 조정할 근거 확보

### 12. AI/optimizer 기능의 의미 명확화

현재:

- stable-baselines3 모델이 있으면 PPO를 로드한다.
- 없으면 heuristic fallback을 사용한다.
- 대시보드에서는 AI처럼 표시될 수 있다.

문제:

- 모델 부재 시 결과는 실제 AI 추론이 아니라 휴리스틱이다.
- 랜덤 jitter가 들어가면 같은 입력에 다른 목표 비중이 나올 수 있다.

개선안:

- `ai_active`가 false이면 UI에 "휴리스틱 모드"로 명확히 표시
- 랜덤 jitter 제거 또는 seed 고정
- 모델 버전, 학습 기간, 입력 피처, 마지막 학습 시각 표시
- 실제 주문 연결은 항상 승인 큐를 거치게 한다.

## 우선순위 4: 테스트와 개발환경

### 13. Python 실행환경 고정

현재 확인:

- `python -m compileall src tests` 실행 시 Python Manager가 런타임 인덱스를 네트워크로 찾으려다 실패했다.
- 로컬 `.venv`가 없다.

개선안:

- `.python-version` 또는 `pyproject.toml`로 Python 버전 고정
- `requirements.txt`만이 아니라 lock 파일 도입 검토
- Windows 로컬 실행 가이드에 `py -3.12 -m venv .venv` 명시
- CI에서 `python -m compileall`과 테스트를 기본 실행

권장 검증 명령:

```powershell
python -m compileall src tests
python -m unittest discover -s tests
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-encoding.ps1
```

### 14. 테스트 불일치 정리

문제:

- 테스트는 `_fail()`과 서킷브레이커 상태를 기대하지만 구현이 없다.
- KIS API 외부 호출은 테스트에서 mock되어야 한다.

개선안:

- API 클래스는 네트워크 호출 부분과 상태 관리 부분을 분리
- `requests.Session`을 주입 가능하게 변경
- 후보 스캔/yfinance는 fixture나 fake downloader로 테스트
- 대시보드 라우트는 FastAPI `TestClient`로 smoke test 추가

권장 테스트 추가:

- `/api/health` returns config flags
- `/api/trades` fallback behavior
- approval approve/reject status transition
- `DRY_RUN=true`에서 `place_order()`가 외부 API를 호출하지 않는지
- circuit breaker open/cooldown/reset behavior

## 우선순위 5: 저장소와 운영 데이터 관리

### 15. SQLite와 JSON export 역할 분리

현재:

- `save_trade()`가 SQLite insert 후 `data/trades.json`도 export한다.
- GitHub Actions는 `data/trades.json`을 database 브랜치로 복사한다.

문제:

- 저장 함수가 DB 저장과 cloud sync용 export를 동시에 담당한다.
- 거래가 많아질수록 매 insert마다 전체 JSON export 비용이 커진다.

개선안:

- `save_trade()`는 DB insert만 담당
- `export_trades_json()`을 별도 함수로 분리
- GitHub Actions 종료 단계에서 한 번만 export
- 대시보드 cloud cache와 local DB의 우선순위를 문서화

### 16. 민감정보와 런타임 파일 정리

확인 대상:

- `.env`
- `data/kis_token.json`
- `.runtime/trades.sqlite`
- `logs/`

개선안:

- `.env`는 git 추적 금지 확인
- token cache는 만료/환경별 분리 유지
- 실거래 계좌번호 일부 마스킹 로그 처리
- Slack 메시지에 민감정보가 포함되지 않도록 점검

## 단계별 실행 계획

### Phase 1: 즉시 안정화

목표: 현재 실행을 막거나 운영 중 오류를 만들 수 있는 문제 제거

작업:

- `/api/trades` 중복 제거
- `save_trade()` 호출 인자 수정
- `out.txt` 디버그 파일 쓰기 제거
- `check_secrets()` 구현 및 `run()`에서 호출
- `tools/check-encoding.ps1` CI 또는 수동 점검 절차에 포함

완료 기준:

- `python -m compileall src tests` 통과
- `python -m unittest discover -s tests` 통과
- 대시보드 `/api/health`, `/api/trades`, `/api/approvals` smoke test 통과

### Phase 2: 주문 안전성 강화

목표: 실수로 주문이 나가거나 API 장애 중 반복 호출되는 위험 감소

작업:

- 서킷브레이커 구현
- `REQUIRE_APPROVAL`을 실제 주문 흐름에 반영
- 승인 큐와 자동 주문 정책 문서화
- 주문 전 최종 현금/수량/비중 검증 함수 추가

완료 기준:

- `DRY_RUN=true`에서 외부 주문 API 호출 없음
- `REQUIRE_APPROVAL=true`에서 신규 매수는 승인 큐로만 이동
- 연속 API 실패 시 circuit open 테스트 통과

### Phase 3: 대시보드/운영 개선

목표: 대시보드를 안정적인 운영 화면으로 정리

작업:

- API 요청 중 `git fetch` 제거
- cloud trades cache 동기화 분리
- 프론트엔드 loading/error/empty 상태 정리
- AI active/fallback 표시 개선

완료 기준:

- 대시보드 요청이 네트워크/git 상태와 독립적으로 응답
- 실패 시 사용자에게 명확한 상태 표시
- cloud cache 실패 시 local DB fallback 정상 동작

### Phase 4: 전략 검증과 백테스트

목표: 전략 파라미터 변경을 데이터로 검증

작업:

- 백테스트 모듈 추가
- KIS/yfinance 데이터 캐시 도입
- 점수 기준별 성과 리포트 생성
- AI/heuristic 결과 재현성 확보

완료 기준:

- 파라미터 변경 전후 성과 비교 가능
- 후보 스캔 threshold 조정 근거 확보
- AI fallback 결과가 재현 가능

## 권장 우선 작업 목록

1. `src/dashboard.py`의 `/api/trades` 중복 제거
2. 승인 주문의 `save_trade()` 호출 수정
3. `src/api/kis_api.py` 서킷브레이커 구현
4. `src/trader.py`의 `check_secrets()` 구현
5. `REQUIRE_APPROVAL` 정책을 자동 주문 흐름에 연결
6. Python 로컬 실행환경 구성 후 compile/test 실행
7. 대시보드 git fetch 분리
8. 백테스트 기반 전략 검증 추가

## 남은 확인 사항

- 현재 로컬 `python` 명령이 Python Manager에 연결되어 있어 실제 테스트 실행이 막혀 있다. `.venv` 또는 명시적 Python 3.12 설치가 먼저 필요하다.
- Git 상태 확인은 저장소 소유자와 샌드박스 사용자 차이로 `safe.directory` 설정 없이는 제한된다.
- 브라우저 렌더링 기준의 대시보드 확인은 아직 수행하지 않았다.
- KIS 실계정/모의계정 API 응답 형태는 네트워크와 인증 정보가 필요하므로 mock 테스트와 실제 smoke test를 분리해야 한다.
