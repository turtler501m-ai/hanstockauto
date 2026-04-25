# 세븐스플릿 자동매매 🤖

> 박성현의 **세븐스플릿(7분할 매매)** 전략 + **Claude AI** + **KIStock API** 기반 GitHub Actions 완전 자동화 트레이딩 시스템

---

## 실행 스케줄

| 시각 (KST) | 내용 |
|---|---|
| 08:50 | 장 시작 전 — 포트폴리오 분석 및 예약 주문 |
| 10:00 | 오전 시장 체크 |
| 13:00 | 오후 시장 체크 |
| 15:00 | 장 마감 전 최종 체크 |

---

## 세팅 방법

### 1. Secrets 등록
`Settings → Secrets and variables → Actions → Secrets`

| Secret 이름 | 설명 |
|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/keys) 에서 발급 |
| `KISTOCK_APP_KEY` | 한국투자증권 OpenAPI 앱키 |
| `KISTOCK_APP_SECRET` | 한국투자증권 OpenAPI 시크릿 |
| `KISTOCK_ACCOUNT` | 계좌번호 (예: `5012345601`) |
| `KAKAO_TOKEN` | 카카오 알림 토큰 (선택) |

### 2. Variables 등록 (선택 — 기본값 있음)
`Settings → Secrets and variables → Actions → Variables`

| Variable | 기본값 | 설명 |
|---|---|---|
| `SPLIT_N` | `7` | 분할 횟수 |
| `STOP_LOSS_PCT` | `-15` | 손절 기준 % |
| `TAKE_PROFIT` | `30` | 목표 수익 % |
| `RSI_BUY` | `30` | RSI 매수 기준 |
| `RSI_SELL` | `70` | RSI 매도 기준 |

### 3. 실제 주문 활성화
`DRY_RUN` 기본값은 `true` (모의 실행).  
실제 주문 실행하려면 워크플로우 수동 실행 시 `dry_run = false` 선택.

---

## 전략 로직

```
1. 잔고/보유종목 조회 (KIStock API)
2. 종목별 기술지표 계산
   - RSI(14), SMA20/60, 볼린저밴드(20, 2σ)
3. 세븐스플릿 신호 생성
   - 손절: 수익률 ≤ -15% → 전량 매도
   - 분할매도: 수익률 ≥ 200% + RSI ≥ 70 → 1/7 매도
   - 목표달성: 수익률 ≥ 30% + RSI ≥ 70 → 1/7 매도
   - 분할매수: 수익률 ≤ -10% + RSI ≤ 30 + BB하단 → 1/7 매수
   - 골든크로스: SMA20 > SMA60 + 손실구간 → 1/7 매수
4. 주문 실행 (DRY_RUN=false 시)
5. 카카오 알림 전송
```

---

## 수동 실행

`Actions → 세븐스플릿 자동매매 → Run workflow`

- `dry_run = true`: 분석만 (주문 없음)
- `dry_run = false`: 실제 주문 실행 ⚠️

---

## ⚠️ 주의사항

- 이 시스템은 **투자 참고용**입니다. 실제 투자 손익에 대한 책임은 본인에게 있습니다.
- 처음에는 반드시 `DRY_RUN=true` 로 충분히 테스트 후 실거래 전환하세요.
- KIStock API 실거래 신청은 한국투자증권 홈페이지에서 별도 신청 필요합니다.
