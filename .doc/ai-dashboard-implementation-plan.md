# 로컬 DB / GCP DB 분리 기준 신규 AI 대시보드 구현 계획

## 목적

현재 시스템은 다음 전제를 기준으로 설계한다.

- 로컬 개발/테스트 환경: 로컬 DB(SQLite 또는 `.runtime/trades.sqlite`)
- 클라우드 운영 환경: GCP DB(PostgreSQL 계열, `DATABASE_URL`)

따라서 목표는 로컬 DB와 GCP DB 중 하나로 강제 통일하는 것이 아니라, **같은 repository API와 같은 스키마 계약을 사용하되 환경별 DB backend만 다르게 선택하는 구조**를 만드는 것이다.

## 핵심 결론

- 로컬 DB는 개발, 테스트, 오프라인 검증, 빠른 디버깅 용도다.
- GCP DB는 클라우드 운영, 대시보드 운영 데이터, 실거래/모의거래 기록의 기준 저장소다.
- 화면과 비즈니스 로직은 DB 종류를 알면 안 된다. `connect_db()`와 repository 계층만 SQLite/PostgreSQL 차이를 흡수해야 한다.
- `trades.json`과 `git show origin/database:trades.json` 흐름은 운영 기준 저장소가 아니다. 필요하면 백업/호환/마이그레이션 보조 기능으로만 둔다.
- 신규 AI 대시보드는 현재 실행 환경의 DB를 기준으로 실제 데이터를 표시해야 한다.

## 환경별 역할

| 환경 | DB | 역할 |
| --- | --- | --- |
| 로컬 개발 | SQLite | 빠른 실행, UI 개발, 단위 테스트, 임시 데이터 검증 |
| 로컬 운영 리허설 | SQLite 또는 GCP DB | 실 API 연동 전 최종 점검 |
| GCP 클라우드 운영 | GCP PostgreSQL | 운영 대시보드, decision log, approval queue, trade history |
| GitHub Actions | GCP DB 권장 | 스케줄 실행 결과를 운영 DB에 기록 |

## DB 선택 규칙

권장 규칙:

```text
DATABASE_URL 있음
  -> GCP/PostgreSQL 사용

DATABASE_URL 없음
  -> 로컬 SQLite 사용
```

현재 `src/db/repository.py`의 `connect_db()` 방향은 이 규칙과 맞다. 다만 repository 계층이 SQLite와 PostgreSQL의 차이를 더 확실하게 숨겨야 한다.

필수 정리:

- row 변환 helper를 repository에 둔다.
- SQL placeholder 차이를 repository에서 처리한다.
- migration 또는 schema init이 SQLite/PostgreSQL 양쪽에서 동작해야 한다.
- 상위 코드에서 `sqlite3.Row` 같은 SQLite 전용 타입을 직접 쓰지 않게 한다.

## 현재 상태 재진단

### 이미 있는 기반

- `DATABASE_URL`이 설정되면 PostgreSQL로 연결되는 분기가 있다.
- `DATABASE_URL`이 없으면 로컬 SQLite를 사용한다.
- `trades`, `decision_logs`, `approvals` 초안이 있다.
- FastAPI 대시보드와 `/ai-dashboard` 라우트가 있다.
- `RiskEngine`, `OrderRouter` 초안이 있다.

### 정리해야 할 문제

- `src/train_lgbm.py`는 현재 `.runtime/trades.sqlite`를 직접 읽는다. 환경별 DB 선택 규칙을 우회한다.
- `src/dashboard.py` 일부는 `sqlite3.Row`에 의존한다. PostgreSQL row와 호환되는 변환 계층이 필요하다.
- `fetch_cloud_trades()`는 `git show origin/database:trades.json`를 읽는다. 이 흐름은 GCP DB 운영 기준과 충돌한다.
- `save_trade()`는 DB 저장과 `data/trades.json` export를 동시에 수행한다. 저장과 export를 분리해야 한다.
- 신규 AI 화면은 아직 정적 더미 데이터 기반이다.
- Paper/demo/live 데이터 경계가 명확하지 않다.

## 목표 아키텍처

```text
환경 설정
  -> DATABASE_URL 유무 판단
  -> repository.connect_db()
  -> 동일 repository 함수 사용

전략/AI/리스크/주문
  -> save_decision_log()
  -> save_approval()
  -> save_trade()
  -> save_portfolio_snapshot()

FastAPI
  -> GET /api/ai-dashboard/summary
  -> 현재 환경 DB에서 데이터 조회

/ai-dashboard
  -> summary API 기반 렌더링
```

## 권장 DB 스키마 계약

SQLite와 PostgreSQL 모두 같은 논리 스키마를 갖는다.

### `trades`

추가 권장 필드:

| 필드 | 설명 |
| --- | --- |
| `execution_mode` | `paper`, `demo`, `live` |
| `portfolio_type` | `PAPER`, `LIVE` |
| `order_submission_enabled` | 주문 API 전송 여부 |
| `source` | `rule`, `ranker`, `optimizer`, `manual` |
| `approval_id` | 승인 큐 연결 |
| `decision_id` | 판단 로그 연결 |

### `decision_logs`

AI 판단 재현용 핵심 테이블이다.

필수 필드:

- `ts`
- `symbol`
- `name`
- `source`
- `features_json`
- `signals_json`
- `model_versions`
- `final_action`
- `confidence`
- `expected_return`
- `risk_result`
- `route_status`
- `approval_id`
- `status`

기존 `indicators` 컬럼은 호환용으로 유지할 수 있다.

### `approvals`

추가 권장 필드:

- `decision_id`
- `risk_result`
- `model_version`
- `execution_mode`

### `portfolio_snapshots`

필드:

- `ts`
- `portfolio_type`
- `cash`
- `stock_eval`
- `total_eval`
- `pnl`
- `holdings_json`

### `model_runs`

필드:

- `model_name`
- `version`
- `status`
- `train_start`
- `train_end`
- `metrics_json`
- `artifact_path`
- `created_at`

## 신규 API 계약

### `GET /api/ai-dashboard/summary`

현재 실행 환경의 DB를 기준으로 신규 화면 전체 데이터를 내려준다.

예시 응답:

```json
{
  "health": {
    "ok": true,
    "db_backend": "sqlite",
    "db_role": "local",
    "trading_env": "demo",
    "dry_run": true,
    "enable_live_trading": false,
    "require_approval": true,
    "kill_switch_active": false,
    "active_model_version": "v1"
  },
  "metrics": {
    "total_eval": 128420000,
    "cash": 24000000,
    "stock_eval": 104420000,
    "pending_approvals": 3,
    "decision_count_today": 8,
    "daily_loss_usage_pct": 18.0,
    "paper_return_pct": 7.8,
    "live_return_pct": 1.1
  },
  "risk_checks": [],
  "decisions": [],
  "approvals": [],
  "audit_events": [],
  "performance": {
    "labels": [],
    "paper_return": [],
    "live_return": [],
    "drawdown": []
  }
}
```

`db_backend` 값:

- `sqlite`
- `postgres`

`db_role` 값:

- `local`
- `cloud`

## 신규 화면 레이아웃 조정

### 상단 상태

표시 항목:

- DB 역할: Local DB 또는 GCP DB
- DB backend: SQLite 또는 PostgreSQL
- KIS API 상태
- 활성 모델 버전
- Kill Switch
- 주문 모드
- 승인 필요 여부

### 메트릭

표시 항목:

- 총 평가자산
- 현금 비중
- 오늘 AI 판단 수
- 승인 대기 수
- 일일 손실 한도 사용률
- Paper 성과
- Live 성과

### AI 주문 후보

현재 환경 DB의 `decision_logs` 최신 데이터를 기준으로 표시한다.

상태값:

- `proposed`
- `risk_passed`
- `risk_blocked`
- `pending_approval`
- `paper_executed`
- `submitted`
- `executed`
- `failed`
- `rejected`

### 선택 후보 근거

표시 항목:

- 입력 피처 snapshot
- 모델 버전
- confidence
- expected return
- downside risk
- risk result
- approval status
- execution mode

## 단계별 구현 계획

### Phase 0: DB 추상화 정리

목표:

- 로컬 SQLite와 GCP PostgreSQL을 같은 코드 경로로 사용하게 만든다.

작업:

- `connect_db()`를 유일한 DB 연결 진입점으로 고정
- repository에 `fetch_all_dicts()`, `fetch_one_dict()`, `execute()` helper 추가
- SQLite 전용 `sqlite3.Row` 의존 제거
- `src/train_lgbm.py`의 SQLite 직접 접근 제거
- DB backend/role 확인 helper 추가
- schema init을 SQLite/PostgreSQL 모두에서 검증

완료 기준:

- `DATABASE_URL` 없음: 로컬 SQLite로 정상 동작
- `DATABASE_URL` 있음: GCP DB로 정상 동작
- 대시보드, 학습 스크립트, 주문 라우터가 모두 repository 경유

### Phase 1: Git/JSON 거래 조회 분리

목표:

- 운영 조회 경로에서 `trades.json`과 git 기반 조회를 제거한다.

작업:

- `fetch_cloud_trades()`를 운영 API에서 제거 또는 fallback/debug 용도로 변경
- `/api/trades`, `/api/performance`, `/api/trades/sync`가 현재 환경 DB를 기준으로 동작하게 정리
- `save_trade()`의 JSON export를 별도 함수로 분리
- 필요한 경우 `tools/export-trades-json` 같은 보조 명령으로 분리

완료 기준:

- 대시보드 조회 중 `git show origin/database:trades.json`가 실행되지 않는다.
- 로컬은 SQLite, 클라우드는 GCP DB에서 거래 기록을 조회한다.

### Phase 2: Summary API 구현

목표:

- 신규 AI 화면을 실제 DB 데이터로 렌더링한다.

작업:

- `GET /api/ai-dashboard/summary` 추가
- `health`, `metrics`, `risk_checks`, `decisions`, `approvals`, `audit_events`, `performance` 조합
- `db_backend`, `db_role` 표시
- API 부분 실패 구조 정의
- `ai_dashboard.js` 정적 배열 제거
- 로딩, 빈 상태, 오류 상태 구현

완료 기준:

- `/ai-dashboard`가 현재 환경 DB의 실제 데이터를 표시한다.
- 로컬과 클라우드에서 같은 화면 코드가 동작한다.

### Phase 3: Decision Log 확장

목표:

- AI 판단을 DB에서 재현 가능하게 만든다.

작업:

- `decision_logs` 확장 컬럼 또는 JSON 구조 추가
- `save_decision_log()` 입력 구조 확장
- `OrderRouter`에서 decision id를 approval/trade와 연결
- 기존 `indicators` 로그는 호환 처리
- `/api/decisions/history` 응답 정리

완료 기준:

- 후보 1건에 대해 `features -> model -> risk -> route` 흐름을 DB에서 복원할 수 있다.

### Phase 4: Risk Engine 운영화

목표:

- 리스크 엔진을 주문 전 필수 통과 단계로 고정한다.

작업:

- `RiskEngine.evaluate_order()` 결과 표준화
- Kill Switch, 일일 손실, 현금 부족, 종목 집중도, 주문 금액/횟수 검사 추가
- 후보별 risk result를 `decision_logs`에 저장
- 전체 리스크 상태를 summary API에 표시

완료 기준:

- AI 모델이 매수 신호를 내도 리스크 차단 시 주문이 생성되지 않는다.
- 화면에서 차단 사유를 확인할 수 있다.

### Phase 5: Approval Queue 통합

목표:

- 승인 큐를 로컬/GCP DB 모두에서 동일하게 동작하게 만든다.

작업:

- approval row에 `decision_id`, `risk_result`, `model_version`, `execution_mode` 연결
- 신규 화면 승인/거절 버튼 연동
- 처리 후 summary API 재조회
- 승인 실패 사유 표시

완료 기준:

- `REQUIRE_APPROVAL=true`에서는 주문 후보가 직접 실행되지 않고 현재 환경 DB의 승인 큐로 이동한다.
- 신규 화면에서 승인, 거절, 실패 상태가 반영된다.

### Phase 6: Paper/Live 분리

목표:

- 가상 성과와 실제 계좌 성과가 섞이지 않도록 한다.

작업:

- `execution_mode` 또는 `portfolio_type` 추가
- `paper_trades`와 `live_trades` 분리 여부 결정
- `sync_trades`는 live 계좌에만 적용
- paper ledger는 현재 환경 DB에서 독립 관리
- 성과 API에서 paper/live 분리 계산

완료 기준:

- `/ai-dashboard`에서 Paper 성과와 Live 성과가 분리 표시된다.
- 실계좌 동기화가 Paper 기록을 변경하지 않는다.

### Phase 7: 모델 학습/추론 DB 연동

목표:

- 로컬 학습은 로컬 DB, 클라우드 학습/운영은 GCP DB를 기준으로 동작한다.

작업:

- `src/train_lgbm.py`가 repository를 통해 `decision_logs`를 읽도록 변경
- 학습 결과를 `model_runs`에 저장
- 활성 모델 버전을 config 또는 DB registry에서 조회
- 모델 부재 시 fallback mode를 화면에 명확히 표시
- 후보별 `score`, `confidence`, `top_features` 저장

완료 기준:

- 환경별 DB 기준으로 학습 데이터, 모델 버전, 화면 표시가 연결된다.

### Phase 8: 운영 안정화

목표:

- 로컬과 GCP 운영 환경 모두에서 장애와 데이터 품질 문제를 줄인다.

작업:

- DB connection timeout 설정
- retry/backoff 적용
- migration 스크립트 도입
- DB health check 추가
- 민감정보 로그 출력 방지
- 대시보드 API에서 긴 외부 작업 제거

완료 기준:

- DB 장애 시 화면이 부분 오류 상태로 degrade된다.
- 로컬/클라우드 schema drift를 추적할 수 있다.

## 최우선 작업 목록

1. repository helper 추가로 SQLite/PostgreSQL row 차이 제거
2. `src/train_lgbm.py`의 SQLite 직접 접근 제거
3. `fetch_cloud_trades()`의 git 기반 조회를 운영 경로에서 제거
4. `save_trade()`의 DB 저장과 JSON export 분리
5. `GET /api/ai-dashboard/summary` 구현
6. `ai_dashboard.js` 정적 데이터 제거
7. `decision_logs` 확장 구조 정의
8. `RiskEngine` 결과를 decision log에 저장
9. approval queue와 decision log 연결
10. paper/live 분리 컬럼 추가

## 구현 시 주의사항

- 로컬 DB와 GCP DB는 역할이 다르지만 스키마 계약은 같아야 한다.
- 상위 로직은 DB backend를 직접 분기하지 않는다.
- `trades.json`은 source of truth가 아니다.
- 대시보드 요청 중 `git fetch`, `git show` 같은 외부 명령을 실행하지 않는다.
- 실전 주문 자동화보다 리스크 차단과 승인 큐를 먼저 완성한다.
- AI 모델 결과는 리스크 엔진보다 우선할 수 없다.
- 모델이 실제로 로드되지 않은 상태를 AI처럼 표시하지 않는다.
- Paper, demo, live 결과를 한 성과 지표로 섞지 않는다.

## 최종 권고

첫 구현 목표는 GCP DB로 강제 통일하는 것이 아니라 **로컬 SQLite와 GCP PostgreSQL을 같은 repository 계약으로 다루는 것**이다.

따라서 가장 먼저 DB 추상화 계층을 정리하고, git/json 기반 거래 조회를 운영 경로에서 제거한 뒤, 신규 AI 대시보드 summary API를 구현한다. 이후 decision log 확장, risk result 저장, approval queue 연결, paper/live 분리, 모델 학습 연동 순서로 확장한다.
