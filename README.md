# Seven Split Auto Trading

KIS Open API based auto-trading bot for Korean stocks. It manages current holdings with split-order rules, scans watchlist candidates with technical indicators, stores trade history in SQLite, and exposes a FastAPI dashboard.

## Features

- KIS Open API token caching
- Balance, quote, daily chart, and cash order API calls
- RSI, SMA, and Bollinger Band signals
- Split buy/sell, stop-loss, and take-profit rules
- Position sizing, cash buffer, and daily loss guard
- SQLite trade history
- Slack notifications
- FastAPI dashboard
- GitHub Actions scheduled runs

## Schedule

GitHub Actions cron uses UTC.

| KST | Task |
| --- | --- |
| 08:50 | Pre-market scan |
| 10:00 | Morning market check |
| 13:00 | Afternoon market check |
| 15:00 | Pre-close market check |

## Environment

Copy `.env.example` to `.env` for local use, or configure the same values in GitHub Actions Secrets and Variables.

Required secrets:

| Name | Description |
| --- | --- |
| `KISTOCK_APP_KEY` | KIS Open API app key |
| `KISTOCK_APP_SECRET` | KIS Open API app secret |
| `KISTOCK_ACCOUNT` | Account number plus product code, for example `1234567801` |

Optional secret:

| Name | Description |
| --- | --- |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |

Main variables:

| Name | Default | Description |
| --- | --- | --- |
| `TRADING_ENV` | `demo` | `demo` or `real` |
| `DRY_RUN` | `true` | Blocks real orders when true |
| `ENABLE_LIVE_TRADING` | `false` | Final live-trading switch |
| `SPLIT_N` | `7` | Split-order divisor |
| `STOP_LOSS_PCT` | `-15` | Stop-loss return percent |
| `TAKE_PROFIT` | `30` | Take-profit return percent |
| `RSI_BUY` | `30` | RSI buy threshold |
| `RSI_SELL` | `70` | RSI sell threshold |
| `TOTAL_CAPITAL` | `10000000` | Reference capital |
| `MAX_POSITIONS` | `3` | Maximum number of holdings |
| `MAX_SINGLE_WEIGHT` | `0.30` | Maximum weight per symbol |
| `CASH_BUFFER` | `0.20` | Cash reserve ratio |
| `MAX_DAILY_LOSS_PCT` | `3.0` | Daily loss halt threshold |

## Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Run the trading engine:

```powershell
python src\trader.py
```

Run the dashboard:

```powershell
uvicorn src.dashboard:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

Run local checks:

```powershell
powershell -ExecutionPolicy Bypass -File tools\verify-local.ps1
```

## Order Guard

Real orders are submitted only when all three conditions are true:

- `DRY_RUN=false`
- `TRADING_ENV=real`
- `ENABLE_LIVE_TRADING=true`

Demo API orders are submitted when `TRADING_ENV=demo` and `DRY_RUN=false`. If `DRY_RUN=true`, every order is logged without API order submission.

## Disclaimer

This project is an implementation template. API failures, network delays, bad market data, logic bugs, and fast market moves can cause losses. Validate in demo trading before using real capital.
