# 한스톡 AI 자동매매 시스템 최적 구현 마스터 플랜

본 문서는 앞서 분석된 `implementation-risk-analysis.md`의 한계점들과, 현재 GitHub 및 퀀트 업계(FinRL, Qlib 등)에서 검증된 **오픈소스 AI 트레이딩 아키텍처 베스트 프랙티스**를 결합하여 도출한 **가장 현실적이고 강력한 최적 구현 계획(Master Plan)**입니다.

---

## 🌟 핵심 아키텍처 전환 목표 (To-Be)

현재의 **단일 스크립트(Monolithic) + GitHub Actions(Stateless)** 구조에서 벗어나, **모듈화된 파이프라인 + 상시 구동형(Event-driven) 아키텍처**로 전환해야 합니다.

1. **상태 관리**: 로컬 SQLite에서 벗어나 클라우드 호스팅 DB(PostgreSQL/Supabase 등) 적용.
2. **배치/스트리밍 분리**: 과거 데이터 수집/학습(Offline) 파이프라인과 실시간 추론(Online) 파이프라인의 물리적 분리 및 로직(Feature) 공유.
3. **MLOps 도입**: 모델 가중치(.pkl, .onnx)와 성능 지표를 추적하기 위한 경량화된 모델 레지스트리(MLflow 등) 연동.

---

## 🛠 단계별 최적 구현(마이그레이션) 계획

### Phase 1: 인프라 독립 및 데이터 파이프라인 정비 (안정성 확보)
가장 시급한 것은 GitHub Actions의 한계(초기화, 타임아웃, 메모리 제한)로부터 시스템을 탈출시키는 것입니다.

* **Task 1.1: 클라우드 DB 연동**
  * 기존 로컬 `trades.db`를 클라우드 DB(예: Supabase, AWS RDS 등)로 마이그레이션.
  * `Paper Trades`(가상 장부)와 `Live Trades`(실제 장부) 테이블을 분리하여 설계.
* **Task 1.2: 24/7 구동 환경(VPS) 구축**
  * AWS EC2, Oracle Cloud (Free Tier) 또는 댁내 미니 PC/NAS 등에 도커(Docker) 기반으로 FastAPI 서버와 스케줄러(APScheduler)를 상시 구동.
* **Task 1.3: Feature Pipeline (Feature Store) 통합**
  * `trader.py` 내부에 산재된 보조지표(RSI, MACD 등) 계산 로직을 `features.py`로 분리.
  * 백테스트 시 과거 데이터(Pandas DataFrame)와 실시간 KIS API 데이터(JSON/Dict) 양쪽 모두에 **동일하게 적용할 수 있는 공통 함수** 구현.

### Phase 2: 핵심 매매 엔진 리팩토링 (리스크/주문 분리)
단일 스크립트(`trader.py`)가 모든 것을 결정하는 구조를 쪼개어 파이프라인 형태로 만듭니다.

* **Task 2.1: Risk Engine 분리**
  * `check_daily_loss`, `check_exposure` 등의 방어 로직을 `RiskEngine` 클래스로 캡슐화.
  * 입력: AI 모델의 매수/매도 제안 비중
  * 출력: 리스크가 반영된 **최종 승인 비중(0%~100%)** 및 거절 사유
* **Task 2.2: Order Router 구현**
  * `RiskEngine`을 통과한 신호를 받아, 현재 설정(`DRY_RUN`, `TRADING_ENV`, `REQUIRE_APPROVAL`)에 따라 다음 중 하나로 분기하는 라우터 클래스 제작:
    1. KIS 모의/실전 계좌로 전송 (Live Execution)
    2. 승인 큐 대기열에 적재 (Pending Approval)
    3. Paper DB에만 가상 체결 기록 (Paper Trading)
* **Task 2.3: Decision Log 로깅 체계 구축**
  * 라우터에서 어떤 경로를 타든, 의사결정의 근거(해당 시점의 모델 점수, 피처 값 등)를 별도 `decision_logs` 테이블에 비동기로 저장.

### Phase 3: AI 모델 통합 및 MLOps (지능화)
안전망(Risk Engine)이 완성되었으므로, 이제 무거운 AI 모델을 붙여도 계좌가 파산할 위험이 없습니다.

* **Task 3.1: Supervised Ranker (LightGBM) 도입**
  * FinRL(강화학습) 도입 전, 상대적으로 설명력(Explainability)이 좋고 안정적인 LightGBM 기반의 종목 랭킹 모델 선적용.
  * 모델 추론부(`predict.py`)를 작성하고, `OrderRouter` 앞단에 배치.
* **Task 3.2: 포트폴리오 비중 최적화 모델(Allocator)**
  * 개별 종목 점수 외에, 포트폴리오 전체의 변동성(Volatility)을 최소화하는 비중 최적화(PyPortfolioOpt 활용) 파이프라인 추가.
* **Task 3.3: 경량 MLOps (모델 버저닝)**
  * 사용할 모델 파일(.pkl)을 `models/` 디렉토리에 버전별로 관리(`ranker_v1.pkl`, `ranker_v2.pkl`).
  * 시스템 설정(`config.yaml`)에서 현재 활성화할 모델 버전을 지정할 수 있도록 구성.

### Phase 4: 신규 AI 대시보드 API 연동 (모니터링 고도화)
기획하신 `ai_dashboard.html` 화면에 생명을 불어넣는 단계입니다.

* **Task 4.1: 관제센터 API 엔드포인트 구현**
  * `GET /api/system/health`: 데이터 수집 상태, 현재 활성 모델 버전, 서킷브레이커 상태 응답.
  * `GET /api/risk/status`: Paper 성과, Live 자산, 일일 한도 소진율 응답.
  * `GET /api/decisions/history`: 최근 의사결정 로그(Decision Log) 및 거절/통과 사유 목록 응답.
* **Task 4.2: 실시간 Kill Switch 구현**
  * `POST /api/system/kill`: 즉시 모든 신규 매수 스케줄러를 정지(Halt)시키고, 보유 종목 전량 시장가 매도(또는 유지) 명령을 수행하는 비상 API 구현.

---

## 🎯 도입 시 예상되는 기대 효과 (Return on Investment)

1. **안정성 극대화**: GitHub Actions의 타임아웃 스트레스 없이, 독립된 서버와 DB에서 안정적으로 24시간 작동하며 장중 급변 사태에 실시간 대응(Kill Switch)이 가능해집니다.
2. **AI 성능 개선(피드백 루프)**: 모델이 언제, 왜 그런 판단을 했는지 `Decision Log`에 박혀있으므로, 주말마다 데이터를 꺼내어 모델이 틀린 이유를 분석하고 `v2`, `v3` 모델로 재학습시키는 **선순환 구조**가 완성됩니다.
3. **가상/실전 분리 심리적 안정감**: `Paper Trading` 모드가 완벽히 분리되므로, 훌륭한 새 AI 전략이 떠올랐을 때 섣불리 내 돈을 태우지 않고 2주간 가상 장부에서 검증한 뒤 실전(Live)으로 스위치를 켤 수 있습니다.

**권장 실행 방안:** 전체를 한 번에 바꾸려 하지 말고, **Phase 1(DB 분리와 상시 기동 서버 구축)**부터 시작하여 기존 코드를 서서히 이식(Refactoring)해 나가는 점진적 접근이 가장 안전합니다.
