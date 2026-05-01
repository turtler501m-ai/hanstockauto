# AI 자동매매 시스템 구축 기획서

## 목적

현재 프로젝트는 규칙 기반 자동매매 엔진에 AI/포트폴리오 비중 계산 기능이 일부 결합된 상태다. 진정한 AI 자동매매 시스템으로 발전시키려면 단순히 모델을 붙이는 것이 아니라, 데이터 수집, 피처 생성, 모델 학습, 백테스트, 리스크 관리, 주문 실행, 모니터링, 사후 분석이 하나의 폐쇄 루프로 연결되어야 한다.

이 문서는 HanStockAuto를 실전 운영 가능한 AI 자동매매 플랫폼으로 발전시키기 위한 기획과 단계별 구축안을 정리한다.

## 현재 상태 진단

### 현재 강점

- KIS Open API 연동 기반이 있다.
- DRY_RUN, demo/real 환경 구분, `ENABLE_LIVE_TRADING` 같은 기본 주문 방어장치가 있다.
- RSI, MACD, SMA, Bollinger, 거래량 기반 후보 스캔 로직이 있다.
- FastAPI 대시보드가 있어 잔고, 신호, 후보, 승인 큐, 거래 기록을 볼 수 있다.
- SQLite 거래 기록과 GitHub Actions 스케줄 실행 구조가 있다.
- FinRL, PyPortfolioOpt, qlib, freqtrade 등 외부 프로젝트를 vendor로 두고 방향성을 탐색한 흔적이 있다.

### 현재 한계

- AI 기능은 실질적으로 대부분 휴리스틱 비중 계산에 가깝다.
- 모델 학습 데이터, 피처, 라벨, 평가 기준, 모델 버전 관리가 정립되어 있지 않다.
- 백테스트/워크포워드 검증/페이퍼트레이딩/실거래 전환 단계가 연결되어 있지 않다.
- 주문 실행 정책과 승인 큐 정책이 완전히 통합되어 있지 않다.
- 리스크 관리가 일부 설정값 중심이며 포트폴리오 전체 위험 관리 체계는 부족하다.
- 대시보드 요청 중 git fetch를 수행하는 등 운영 안정성 측면에서 정리가 필요하다.
- Python 실행환경과 테스트 자동화가 완전히 고정되어 있지 않다.

## 목표 시스템 정의

### 비전

AI 자동매매 시스템은 다음 질문에 일관되게 답할 수 있어야 한다.

1. 어떤 데이터를 근거로 판단했는가?
2. 어떤 모델 또는 전략이 판단했는가?
3. 과거 검증에서 어느 정도의 기대 성과와 위험을 보였는가?
4. 현재 포트폴리오 위험 한도 안에서 주문 가능한가?
5. 주문 후 실제 결과가 모델 기대와 얼마나 달랐는가?
6. 이 차이를 다음 학습과 전략 개선에 어떻게 반영할 것인가?

### 핵심 원칙

- AI 판단은 반드시 검증 가능한 데이터와 모델 버전에 연결한다.
- 실전 주문은 리스크 엔진을 통과해야 한다.
- 모델이 확신해도 손실 한도, 종목 집중도, 유동성 한도, 일일 주문 한도를 넘지 않는다.
- 처음부터 완전 자동 실거래를 목표로 하지 않고, 분석 → 백테스트 → 페이퍼트레이딩 → 승인형 실거래 → 제한적 자동 실거래 순서로 전환한다.
- 모든 주문 후보, 승인, 실행, 실패, 사후 성과를 기록한다.

## 목표 아키텍처

```text
데이터 수집 계층
  -> KIS 시세/잔고/주문 데이터
  -> yfinance 또는 보조 시장 데이터
  -> 거래 기록, 승인 기록, 포트폴리오 스냅샷

데이터 저장 계층
  -> raw market data
  -> feature store
  -> model registry
  -> backtest results
  -> live decision logs

AI/전략 계층
  -> rule-based baseline
  -> supervised ranking model
  -> portfolio optimizer
  -> reinforcement learning policy
  -> ensemble decision engine

리스크 계층
  -> 주문 전 검증
  -> 포지션/현금/손실/유동성 한도
  -> circuit breaker
  -> kill switch

실행 계층
  -> approval queue
  -> dry-run executor
  -> demo executor
  -> real executor

운영 계층
  -> dashboard
  -> alerts
  -> audit logs
  -> performance attribution
  -> retraining pipeline
```

## 데이터 전략

### 1. 데이터 소스

| 데이터 | 용도 | 우선순위 |
| --- | --- | --- |
| KIS 일봉/현재가/호가 | 실전 판단 기준, 주문 전 검증 | 최우선 |
| KIS 잔고/체결/주문 | 포트폴리오 상태와 결과 추적 | 최우선 |
| yfinance | 보조 과거 데이터, 빠른 실험 | 중간 |
| 거래 기록 SQLite/JSON | 모델 사후 평가, 손익 분석 | 높음 |
| 외부 지수/환율/금리 | 시장 regime 피처 | 중간 |
| 뉴스/공시/수급 | 확장 피처 | 후순위 |

### 2. 저장 구조

현재는 SQLite 거래 기록 중심이다. AI 시스템에는 다음 저장 영역이 필요하다.

```text
data/
  raw/
    market_daily/
    quotes/
    balances/
  features/
    daily_features.parquet
    portfolio_features.parquet
  models/
    registry.json
    ranking/
    allocation/
    rl/
  backtests/
    runs/
  decisions/
    live_decisions.sqlite
```

권장:

- 초기에는 SQLite + Parquet 조합으로 충분하다.
- raw 데이터와 feature 데이터를 분리한다.
- 실시간 판단 로그는 재현 가능하도록 입력 feature snapshot과 모델 버전을 함께 저장한다.

### 3. 피처 설계

기본 기술적 피처:

- 수익률: 1일, 3일, 5일, 20일, 60일
- 변동성: 5일, 20일, 60일
- RSI: 2, 14
- MACD, MACD histogram
- SMA 이격도: price/SMA20, price/SMA60, SMA20/SMA60
- Bollinger 위치: 현재가가 밴드 내 어디에 있는지
- 거래량: 20일 평균 대비 현재 거래량
- 고점/저점 돌파 여부

포트폴리오 피처:

- 보유 비중
- 평가 손익률
- 보유 기간
- 종목별 실현/미실현 손익
- 현금 비중
- 포트폴리오 변동성
- 종목 간 상관관계

시장 regime 피처:

- KOSPI/KOSDAQ 추세
- 시장 전체 상승 종목 비율
- 시장 변동성
- 금리/환율/미국 지수 변화율

## 모델 전략

### 1. Rule-Based Baseline

현재 전략을 baseline으로 유지한다.

역할:

- AI 모델의 최소 비교 기준
- 모델 장애 시 fallback
- 설명 가능한 기본 전략

개선:

- 현재 점수화 로직을 `StrategySignal` 형태의 구조화된 출력으로 바꾼다.
- 각 신호에 confidence와 expected holding period를 추가한다.

### 2. Supervised Ranking Model

목표:

- 후보 종목을 "매수할 만한 순서"로 정렬한다.

라벨 예시:

- 5거래일 후 수익률
- 20거래일 후 수익률
- 20거래일 내 최대 낙폭
- 수익률 - 위험 패널티

모델 후보:

- LightGBM 또는 XGBoost
- RandomForest baseline
- Logistic/Linear model as explainable baseline

출력:

```json
{
  "symbol": "005930",
  "model": "ranker_lgbm_v1",
  "score": 0.72,
  "expected_return_20d": 0.035,
  "downside_risk": 0.018,
  "confidence": 0.64,
  "top_features": ["rsi14", "volume_ratio", "macd_hist"]
}
```

### 3. Portfolio Allocation Model

목표:

- 어떤 종목을 얼마나 보유할지 결정한다.

초기 접근:

- PyPortfolioOpt 스타일의 mean-variance 또는 inverse volatility
- ranking score를 기대수익률 proxy로 사용
- 최대 종목 비중, 현금 비중, turnover 제한 포함

출력:

```json
{
  "target_cash_weight": 0.2,
  "positions": [
    {
      "symbol": "005930",
      "current_weight": 0.12,
      "target_weight": 0.18,
      "action": "buy",
      "qty": 3
    }
  ]
}
```

### 4. Reinforcement Learning Policy

목표:

- 포트폴리오 상태에서 매수/매도/비중 조절 정책을 학습한다.

주의:

- RL은 데이터 누수, 과최적화, 거래비용 반영 실패에 취약하다.
- 초기 실전 주문 결정권을 RL에 직접 주면 위험하다.

권장 역할:

- 초기에는 "추천 비중 참고 모델"로만 사용
- supervised ranker와 risk engine을 통과한 후보 안에서만 allocation 제안
- 페이퍼트레이딩으로 충분히 검증 후 제한적 사용

환경 설계:

- observation: 종목별 피처 + 포트폴리오 상태 + 시장 regime
- action: 종목별 target weight 또는 buy/sell/hold
- reward: 수익률 - drawdown penalty - turnover cost - concentration penalty
- transaction cost: 수수료, 세금, 슬리피지 반영

### 5. Ensemble Decision Engine

실전 판단은 단일 모델이 아니라 여러 신호의 합의로 만든다.

예시:

```text
최종 매수 후보 =
  rule score >= threshold
  AND ranking model score >= threshold
  AND risk engine 승인
  AND portfolio optimizer target_weight > current_weight
```

최종 action 결정:

| 조건 | action |
| --- | --- |
| 손절 한도 초과 | sell |
| risk engine 차단 | hold |
| model confidence 낮음 | approval queue |
| ranker + rule + optimizer 동의 | buy candidate |
| RL만 단독 추천 | watch only |

## 리스크 관리 체계

### 1. 주문 전 리스크 체크

모든 주문은 다음 검사를 통과해야 한다.

- `DRY_RUN`, `TRADING_ENV`, `ENABLE_LIVE_TRADING` 상태 확인
- 종목별 최대 비중
- 전체 주식 노출 비중
- 현금 버퍼
- 일일 손실 한도
- 일일 주문 횟수/금액 한도
- 최소 거래대금 또는 유동성 조건
- 동일 종목 연속 주문 제한
- API circuit breaker 상태
- 주문 가격이 현재 호가와 너무 멀리 떨어져 있지 않은지

### 2. Kill Switch

즉시 모든 주문을 중지하는 전역 스위치가 필요하다.

추천 설정:

```env
KILL_SWITCH=false
MAX_DAILY_ORDER_AMOUNT=1000000
MAX_DAILY_ORDER_COUNT=5
MAX_PORTFOLIO_EXPOSURE=0.80
MAX_SYMBOL_WEIGHT=0.30
MAX_DRAWDOWN_STOP=0.05
```

### 3. 자동화 단계별 권한

| 단계 | 설명 | 주문 권한 |
| --- | --- | --- |
| Analysis Only | 신호 계산만 수행 | 없음 |
| Dry Run | 주문을 가정하고 기록 | 실제 API 호출 없음 |
| Demo Trading | 모의투자 주문 | 모의 계좌만 |
| Approval Mode | 실계좌 주문 전 수동 승인 | 승인 후 실행 |
| Limited Auto | 검증된 일부 전략만 자동 | 금액/횟수 제한 |
| Full Auto | 완전 자동 | 장기 검증 후에도 비추천 |

권장:

- 기본 운영은 Approval Mode.
- 손절은 정책에 따라 자동 허용할 수 있으나, 금액 한도와 circuit breaker를 반드시 적용한다.

## 백테스트와 검증 체계

### 1. 검증 단계

```text
단위 테스트
  -> 지표 계산/주문 수량/리스크 체크

과거 데이터 백테스트
  -> 전략과 모델 후보 성과 비교

워크포워드 검증
  -> 과거 일부로 학습, 이후 기간으로 평가

페이퍼트레이딩
  -> 실시간 데이터로 가상 주문 기록

모의투자
  -> KIS demo 주문

승인형 실거래
  -> 사람이 승인한 주문만 실행

제한적 자동 실거래
  -> 검증된 전략만 작은 금액으로 자동
```

### 2. 성과 지표

수익 지표:

- 누적 수익률
- 연환산 수익률
- 월별 수익률
- benchmark 대비 초과수익

위험 지표:

- MDD
- 변동성
- Sharpe ratio
- Sortino ratio
- 손실 거래 평균
- VaR 또는 expected shortfall

매매 품질:

- 승률
- 평균 수익/평균 손실
- profit factor
- turnover
- 거래비용 비중
- 슬리피지 영향

모델 품질:

- rank IC
- top-k 수익률
- calibration
- feature importance
- regime별 성과

## 대시보드 기획

### 1. AI 의사결정 화면

필수 정보:

- 추천 action
- 추천 수량
- 모델 confidence
- 근거 feature
- 예상 수익/위험
- 리스크 체크 결과
- 승인 필요 여부
- 모델 버전

예시 카드:

```text
삼성전자 005930
추천: 매수 3주
모델: ranker_lgbm_v1 + optimizer_v1
신뢰도: 64%
예상 20일 수익률: +3.5%
Downside risk: -1.8%
리스크 체크: 통과
실행 모드: 승인 필요
```

### 2. 운영 관제 화면

필수 패널:

- 현재 모드: dry-run/demo/real
- kill switch
- circuit breaker
- 오늘 주문 금액/횟수
- 일일 손익과 손실 한도 사용률
- 모델 상태와 마지막 학습 시각
- 데이터 freshness
- 실패한 API 호출 요약

### 3. 사후 분석 화면

필수 기능:

- 주문 당시 모델 판단 조회
- 실제 결과와 예상 결과 비교
- 종목별 누적 성과
- 전략별 성과
- 승인 거절/승인 주문의 결과 비교
- 모델 버전별 성과

## 코드 구조 개편안

현재 구조를 확장 가능한 플랫폼 구조로 정리한다.

```text
src/
  api/
    kis_api.py
  config.py
  dashboard.py
  data/
    collectors.py
    feature_store.py
    market_cache.py
  db/
    repository.py
    models.py
  execution/
    order_executor.py
    approval_queue.py
    order_router.py
  models/
    ranker.py
    allocator.py
    rl_policy.py
    registry.py
  risk/
    checks.py
    circuit_breaker.py
    limits.py
  strategy/
    indicators.py
    seven_split.py
    ensemble.py
  backtest/
    engine.py
    metrics.py
    reports.py
  monitoring/
    alerts.py
    audit.py
  trader.py
```

핵심 분리 원칙:

- `strategy`: 무엇을 하고 싶은가
- `risk`: 해도 되는가
- `execution`: 어떻게 주문할 것인가
- `data`: 어떤 근거로 판단했는가
- `models`: 어떤 AI가 판단했는가
- `monitoring`: 결과가 어땠는가

## 데이터베이스 설계 초안

### `orders`

| 컬럼 | 설명 |
| --- | --- |
| id | 주문 ID |
| created_at | 생성 시각 |
| symbol | 종목코드 |
| action | buy/sell |
| qty | 수량 |
| price | 가격 |
| source | rule/ranker/optimizer/rl/manual |
| status | proposed/approved/rejected/submitted/executed/failed |
| reason | 사람이 읽을 수 있는 근거 |
| model_version | 모델 버전 |
| risk_result | 리스크 검사 결과 JSON |

### `decisions`

| 컬럼 | 설명 |
| --- | --- |
| id | 판단 ID |
| ts | 판단 시각 |
| symbol | 종목코드 |
| features_json | 입력 피처 |
| signals_json | rule/model/optimizer 결과 |
| final_action | 최종 판단 |
| confidence | 신뢰도 |
| model_versions | 사용 모델 버전 |

### `portfolio_snapshots`

| 컬럼 | 설명 |
| --- | --- |
| id | 스냅샷 ID |
| ts | 시각 |
| cash | 현금 |
| total_eval | 총 평가금 |
| pnl | 평가손익 |
| holdings_json | 보유 종목 |

### `model_runs`

| 컬럼 | 설명 |
| --- | --- |
| id | 학습/평가 실행 ID |
| model_name | 모델명 |
| version | 버전 |
| train_start | 학습 시작 데이터 |
| train_end | 학습 종료 데이터 |
| metrics_json | 성과 지표 |
| artifact_path | 모델 파일 경로 |

## 단계별 구축 로드맵

### Phase 0: 기반 안정화

목표:

- 현재 시스템이 안정적으로 실행되고 검증되도록 만든다.

작업:

- `/api/trades` 중복 제거
- `save_trade()` 인자 오류 수정
- `check_secrets()` 구현
- circuit breaker 구현
- Python 실행환경 고정
- UTF-8 검사 유지
- 단위 테스트 통과

완료 기준:

- compile/test 통과
- 대시보드 주요 API smoke test 통과
- dry-run 주문 기록 정상화

### Phase 1: AI 데이터 파이프라인

목표:

- 모델 학습과 실시간 판단에 사용할 데이터를 축적한다.

작업:

- market data cache 추가
- portfolio snapshot 저장
- decision log 저장
- feature generation 모듈 추가
- raw/features/models/backtests 디렉터리 정리

완료 기준:

- 동일 시점 판단을 feature snapshot으로 재현 가능
- 최소 1년 이상 일봉 feature dataset 생성 가능

### Phase 2: Supervised Ranker 구축

목표:

- 매수 후보를 모델 기반으로 정렬한다.

작업:

- 라벨 정의
- 학습 dataset 생성
- baseline model 학습
- top-k backtest
- 대시보드에 모델 점수 표시

완료 기준:

- rule baseline 대비 top-k 후보 성과 비교 리포트 생성
- 실전 주문 없이 추천 후보만 기록

### Phase 3: 리스크 엔진과 주문 라우터

목표:

- 모든 주문 후보가 동일한 리스크 검사를 통과하게 한다.

작업:

- `risk/checks.py`
- `execution/order_router.py`
- approval queue 통합
- kill switch
- daily limit

완료 기준:

- 모든 주문 경로가 risk engine을 거침
- approval/dry-run/demo/real 실행 모드가 하나의 order router에서 분기

### Phase 4: 포트폴리오 최적화

목표:

- 종목 선택뿐 아니라 비중 결정까지 모델화한다.

작업:

- target weight optimizer
- turnover penalty
- current holdings-aware rebalance
- transaction cost 반영
- 대시보드 리밸런싱 설명 강화

완료 기준:

- 목표 비중과 주문 수량이 재현 가능
- 리스크 한도를 넘는 리밸런싱 주문이 차단됨

### Phase 5: 페이퍼트레이딩과 모의투자

목표:

- 실시간 데이터에서 모델 판단을 누적 검증한다.

작업:

- paper trading ledger
- demo 계좌 실행
- model vs actual 성과 비교
- 승인 주문과 미승인 주문 결과 비교

완료 기준:

- 최소 1~3개월 paper/demo 성과 리포트
- 모델별 성과와 손실 원인 분석 가능

### Phase 6: 제한적 실거래 자동화

목표:

- 검증된 일부 전략만 작은 금액으로 자동 실행한다.

조건:

- 일정 기간 paper/demo 성과 기준 통과
- MDD와 일일 손실 한도 충족
- 주문 실패율 낮음
- dashboard/alert/kill switch 정상
- 사람이 언제든 중지 가능

권장 제한:

- 최초 자동 실거래는 전체 자본의 5~10% 이하
- 종목당 1~3% 이하
- 일일 주문 횟수 제한
- 신규 매수는 승인형 유지, 손절/리밸런싱 일부만 자동화 검토

## 운영 정책

### 기본 운영 모드

권장 기본값:

```env
TRADING_ENV=demo
DRY_RUN=true
ENABLE_LIVE_TRADING=false
REQUIRE_APPROVAL=true
KILL_SWITCH=false
```

실계좌 자동화는 아래 조건을 모두 만족해야 한다.

- 테스트 통과
- 백테스트 통과
- paper/demo 성과 통과
- 승인 큐 정상 동작
- kill switch 정상 동작
- 리스크 한도 설정 완료
- Slack 또는 대체 알림 정상

### 모델 재학습 정책

권장:

- 일봉 기반 모델은 주 1회 또는 월 1회 재학습
- 재학습 후 바로 실전 반영하지 않고 validation 리포트 확인
- 성능이 baseline보다 나쁘면 이전 모델 유지
- 모델 버전 rollback 가능해야 함

### 알림 정책

필수 알림:

- 주문 후보 생성
- 승인 대기
- 주문 실행/실패
- circuit breaker open
- kill switch active
- 일일 손실 한도 접근
- 데이터 수집 실패
- 모델 추론 실패

## 성공 기준

### 기술적 성공 기준

- 모든 주문 판단이 decision log로 재현 가능
- 모든 주문이 risk engine을 통과
- 모델 버전과 성과가 추적 가능
- 백테스트, paper, demo, real 결과가 같은 지표 체계로 비교 가능
- 대시보드에서 운영 상태와 위험 상태를 즉시 파악 가능

### 투자 시스템 성공 기준

- baseline 전략보다 개선된 위험 조정 수익률
- 낮은 MDD
- 과도한 turnover 방지
- 특정 종목/섹터 편중 방지
- 모델 성과 저하 시 자동 또는 수동으로 fallback 가능

## 즉시 착수할 작업

1. 현재 실행 안정화: `/api/trades`, `save_trade()`, `check_secrets()`, circuit breaker 수정
2. decision log 테이블 추가
3. paper trading ledger 추가
4. feature generation 모듈 추가
5. supervised ranker baseline 구축
6. risk engine과 order router 분리
7. 대시보드에 모델 점수, 리스크 검사 결과, 모델 버전 표시
8. paper/demo 성과 리포트 생성

## 주의사항

AI 자동매매는 모델을 붙인다고 완성되지 않는다. 실제 핵심은 "모델의 판단을 검증 가능한 데이터와 리스크 통제 안에 넣고, 결과를 다시 학습과 운영 개선으로 되돌리는 구조"다. 따라서 실전 주문 자동화보다 먼저 데이터 품질, 백테스트, 페이퍼트레이딩, 승인 큐, 리스크 엔진을 완성해야 한다.

최종 목표는 완전 자동 주문이 아니라, 사람이 이해하고 중지할 수 있으며 검증 가능한 AI 의사결정 시스템이다.
