# 신규 개선사항 설계 및 개발 정리

## 목적

현재 HanStockAuto는 규칙 기반 자동매매, 승인 큐, 리스크 엔진, FastAPI 대시보드, 신규 AI 대시보드 초안을 갖고 있다. 앞으로의 개선은 단순 기능 추가가 아니라 다음 목표를 만족해야 한다.

- 로컬 개발은 로컬 DB(SQLite)로 빠르게 검증한다.
- 클라우드 운영은 GCP DB(PostgreSQL)를 기준 저장소로 사용한다.
- 대시보드, 학습, 주문 라우터는 DB 종류를 직접 알지 않고 같은 repository API를 사용한다.
- AI 판단은 입력 피처, 모델 버전, 리스크 결과, 주문 라우팅 결과까지 추적 가능해야 한다.
- 실전 주문 자동화보다 리스크 차단과 승인 큐를 먼저 안정화한다.

## 개선 방향 요약

| 영역 | 현재 상태 | 개선 방향 |
| --- | --- | --- |
| DB | SQLite/PostgreSQL 분기 초안 있음 | repository 계층으로 완전 추상화 |
| 대시보드 | 신규 AI 화면은 정적 데이터 중심 | summary API 기반 실제 데이터 렌더링 |
| 거래 기록 | DB 저장과 JSON export가 결합됨 | DB 저장과 export/sync 분리 |
| 클라우드 조회 | git/trades.json 조회가 섞임 | GCP DB를 클라우드 운영 기준으로 사용 |
| Decision Log | indicators 중심 단순 로그 | 피처/모델/리스크/라우팅 결과 저장 |
| Risk Engine | 일부 방어 로직 존재 | 모든 주문 후보의 필수 통과 단계로 고정 |
| Approval Queue | 기본 CRUD 존재 | decision log, risk result, execution mode와 연결 |
| Paper/Live | 기록이 섞일 수 있음 | `execution_mode`, `portfolio_type` 기준 분리 |
| AI 모델 | fallback/휴리스틱 중심 | 모델 registry와 학습/추론 흐름 정리 |

## 설계 원칙

### 1. 환경별 DB 분리

```text
로컬 개발/테스트
  -> SQLite
  -> .runtime/trades.sqlite

클라우드 운영
  -> GCP PostgreSQL
  -> DATABASE_URL
```

DB 선택 규칙:

```text
DATABASE_URL 있음
  -> PostgreSQL 사용

DATABASE_URL 없음
  -> SQLite 사용
```

상위 로직은 SQLite/PostgreSQL을 직접 분기하지 않는다. 모든 DB 접근은 `src/db/repository.py`를 통해 수행한다.

### 2. 운영 데이터의 기준

- 로컬 실행 시 source of truth는 로컬 SQLite다.
- 클라우드 실행 시 source of truth는 GCP DB다.
- `data/trades.json`은 source of truth가 아니다.
- `git show origin/database:trades.json` 기반 조회는 운영 대시보드 경로에서 제거한다.

### 3. AI 판단 재현성

주문 후보 1건은 다음 흐름을 DB에서 복원할 수 있어야 한다.

```text
market/portfolio data
  -> features
  -> rule/model/optimizer signal
  -> risk result
  -> approval/execution route
  -> trade result
```

이를 위해 `decision_logs`는 단순 지표 저장소가 아니라 판단 스냅샷 저장소가 되어야 한다.

## 개발 대상 설계

## 1. DB Repository 개선

### 목표

SQLite와 PostgreSQL 차이를 repository 계층에서 흡수한다.

### 설계

추가 권장 함수:

```python
def get_db_backend() -> str:
    ...

def get_db_role() -> str:
    ...

def fetch_all_dicts(sql: str, params: tuple = ()) -> list[dict]:
    ...

def fetch_one_dict(sql: str, params: tuple = ()) -> dict | None:
    ...

def execute_write(sql: str, params: tuple = ()) -> None:
    ...
```

### 개발 작업

- `DBWrapper`의 row 변환 기능 보강
- PostgreSQL `DictCursor`와 SQLite row를 모두 `dict`로 변환
- 상위 코드의 `sqlite3.Row` 직접 사용 제거
- `init_db()`가 SQLite/PostgreSQL 양쪽에서 동일 스키마를 생성하도록 정리

### 완료 기준

- `DATABASE_URL` 유무만 바꿔도 동일 API가 동작한다.
- dashboard, trader, train script가 모두 repository를 통해 DB에 접근한다.

## 2. 거래 조회 및 JSON Export 분리

### 목표

대시보드 조회 중 git 명령이나 JSON 파일 조회가 실행되지 않게 한다.

### 설계

운영 조회:

```text
/api/trades
/api/performance
/api/ai-dashboard/summary
  -> repository
  -> 현재 환경 DB
```

보조 export:

```text
tools/export-trades-json
  -> 현재 환경 DB
  -> data/trades.json
```

### 개발 작업

- `fetch_cloud_trades()`를 운영 API에서 제거
- `save_trade()`에서 `data/trades.json` export 분리
- 필요 시 별도 수동 export 함수 또는 도구 추가
- `/api/trades`, `/api/performance`가 현재 환경 DB만 조회하도록 정리

### 완료 기준

- 대시보드 요청 중 `git fetch`, `git show`가 실행되지 않는다.
- 로컬은 SQLite, 클라우드는 GCP DB에서 거래 내역을 조회한다.

## 3. 신규 AI Dashboard Summary API

### 목표

`/ai-dashboard`가 정적 목업이 아니라 실제 운영 데이터를 표시하게 한다.

### API

`GET /api/ai-dashboard/summary`

응답 구조:

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
    "total_eval": 0,
    "cash": 0,
    "stock_eval": 0,
    "pending_approvals": 0,
    "decision_count_today": 0,
    "daily_loss_usage_pct": 0,
    "paper_return_pct": 0,
    "live_return_pct": 0
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

### 개발 작업

- `src/dashboard.py`에 summary endpoint 추가
- 기존 `/api/health`, `/api/risk/status`, `/api/approvals`, `/api/decisions/history`, `/api/performance` 로직을 내부 helper로 조합
- 부분 실패 시 패널별 오류 정보를 내려주는 구조 추가
- `web/static/js/ai_dashboard.js`의 정적 배열 제거
- 로딩, 빈 상태, 오류 상태 렌더링

### 완료 기준

- `/ai-dashboard` 새로고침 시 현재 환경 DB의 실제 상태가 표시된다.
- JS 문법 검사와 dashboard smoke test가 통과한다.

## 4. Decision Log 확장

### 목표

AI 판단과 주문 후보를 사후 분석할 수 있게 만든다.

### 권장 스키마

| 필드 | 설명 |
| --- | --- |
| `source` | rule, ranker, optimizer, rl, manual |
| `features_json` | 판단 당시 입력 피처 |
| `signals_json` | 전략/모델/최적화 결과 |
| `model_versions` | 사용 모델 버전 |
| `final_action` | 최종 action |
| `confidence` | 모델 또는 ensemble 신뢰도 |
| `expected_return` | 기대 수익률 |
| `risk_result` | 리스크 검사 결과 JSON |
| `route_status` | 주문 라우터 상태 |
| `approval_id` | 승인 큐 연결 |
| `status` | proposed, blocked, pending, executed 등 |

### 개발 작업

- `save_decision_log()` 입력 구조 확장
- 기존 `indicators` 기반 로그 호환 처리
- `OrderRouter`에서 decision id를 받아 approval/trade와 연결
- `/api/decisions/history` 응답을 신규 화면 구조로 변환

### 완료 기준

- 주문 후보 1건의 판단 근거, 리스크 결과, 라우팅 상태를 DB에서 복원할 수 있다.

## 5. Risk Engine 운영화

### 목표

모든 주문 후보가 리스크 엔진을 통과하도록 강제한다.

### 검사 항목

- Kill Switch 활성 여부
- 일일 손실 한도
- 현금 부족
- 최대 종목 수
- 단일 종목 최대 비중
- 현금 버퍼
- 일일 주문 금액
- 일일 주문 횟수

### 개발 작업

- `RiskEngine.evaluate_order()` 결과 구조 표준화
- risk result를 decision log에 저장
- risk blocked 상태에서는 approval/trade 생성 차단
- summary API에 전체 리스크 상태와 후보별 리스크 상태 표시

### 완료 기준

- AI 모델이 매수 신호를 내도 리스크 차단 시 주문이 생성되지 않는다.
- 화면에서 차단 사유를 확인할 수 있다.

## 6. Approval Queue 통합

### 목표

승인 큐를 단순 수동 처리 목록이 아니라 주문 라우팅의 공식 단계로 만든다.

### 설계

```text
decision_logs.id
  -> approvals.decision_id
  -> trades.decision_id / trades.approval_id
```

### 개발 작업

- `approvals`에 `decision_id`, `risk_result`, `model_version`, `execution_mode` 연결
- 신규 화면 승인/거절 버튼 연동
- 승인/거절 후 summary API 재조회
- 실패 사유와 broker response 표시

### 완료 기준

- `REQUIRE_APPROVAL=true`에서는 주문 후보가 직접 실행되지 않고 승인 큐로 이동한다.
- 승인/거절/실패 상태가 신규 화면에 반영된다.

## 7. Paper / Demo / Live 분리

### 목표

가상 성과와 실제 계좌 성과가 섞이지 않게 한다.

### 설계

단기:

- `trades.execution_mode`: `paper`, `demo`, `live`
- `trades.portfolio_type`: `PAPER`, `LIVE`

장기:

- `paper_trades`
- `live_trades`

### 개발 작업

- `save_trade()`에 execution mode 저장
- `sync_trades`는 live 계좌에만 적용
- paper ledger는 독립 장부로 관리
- `/api/performance`에서 paper/live 분리 계산

### 완료 기준

- 신규 화면에서 Paper 성과와 Live 성과를 별도로 표시한다.
- 실계좌 동기화가 Paper 기록을 변경하지 않는다.

## 8. 모델 학습/추론 DB 연동

### 목표

로컬 학습은 로컬 DB, 클라우드 운영 학습은 GCP DB를 기준으로 동작하게 한다.

### 개발 작업

- `src/train_lgbm.py`의 SQLite 직접 접근 제거
- repository를 통해 `decision_logs` 조회
- `model_runs` 테이블 추가
- 활성 모델 버전 조회 구조 정리
- 모델 부재 시 fallback mode를 화면에 표시
- 후보별 `score`, `confidence`, `top_features` 저장

### 완료 기준

- 학습 데이터, 모델 버전, 화면 표시가 같은 DB 기준으로 연결된다.
- 실제 모델이 없으면 AI처럼 과장 표시하지 않는다.

## 9. 신규 화면 개발

### 목표

현재 정적 UI를 실제 운영 관제 화면으로 전환한다.

### 개발 작업

- `ai_dashboard.js` 정적 배열 제거
- summary API fetch 추가
- 상태 패널 렌더링
- metric panel 렌더링
- decision table 렌더링
- selected decision detail 렌더링
- risk checks 렌더링
- approval list 렌더링
- performance chart 렌더링
- empty/error/loading state 추가

### 완료 기준

- 화면의 모든 주요 숫자와 목록이 API 응답에서 나온다.
- API 실패 시 화면이 깨지지 않는다.

## 구현 우선순위

### 1차 개발

1. repository helper 추가
2. `train_lgbm.py` DB 접근 수정
3. git/trades.json 운영 조회 제거
4. summary API 추가
5. 신규 화면 fetch 기반 전환

### 2차 개발

1. decision log 확장
2. risk result 저장
3. approval queue 연결
4. paper/live 분리

### 3차 개발

1. model_runs 추가
2. LightGBM 학습/추론 연동
3. 모델 버전별 성과 표시
4. 운영 안정화와 migration 정리

## 테스트 계획

### 로컬 SQLite

- `DATABASE_URL` 없는 상태로 실행
- `python -m unittest discover -s tests`
- `/api/health`
- `/api/ai-dashboard/summary`
- `/ai-dashboard`
- approval 생성/승인/거절

### GCP DB

- `DATABASE_URL` 설정 상태로 실행
- schema init 확인
- decision log 저장 확인
- trade 저장 확인
- summary API 조회 확인
- dashboard 렌더링 확인

### 프론트

- `node --check web/static/js/ai_dashboard.js`
- desktop/mobile 레이아웃 확인
- 빈 데이터 상태 확인
- API 오류 상태 확인

## 운영 주의사항

- 실전 주문 자동화보다 리스크 차단과 승인 큐를 먼저 완성한다.
- 대시보드 요청에서 긴 외부 작업을 실행하지 않는다.
- DB 장애 시 전체 화면이 죽지 않고 패널별 오류를 보여준다.
- 민감정보는 로그와 화면에 표시하지 않는다.
- 모델이 fallback 상태이면 화면에 명확히 표시한다.
- Paper/demo/live 성과를 한 지표로 섞지 않는다.

## 완료 정의

신규 개선사항 개발은 다음 조건을 만족할 때 1차 완료로 본다.

- 로컬 SQLite와 GCP DB가 같은 repository API로 동작한다.
- 신규 AI 대시보드가 summary API 기반으로 렌더링된다.
- 거래 기록 조회가 git/trades.json에 의존하지 않는다.
- decision log가 AI 판단 재현에 필요한 최소 정보를 저장한다.
- risk result와 approval queue가 주문 후보와 연결된다.
- Paper/Live 성과가 분리 표시된다.
