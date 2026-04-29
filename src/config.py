from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # KIS API Credentials
    kistock_app_key: str = ""
    kistock_app_secret: str = ""
    kistock_account: str = ""
    
    # Notifications
    slack_webhook_url: Optional[str] = ""
    
    # Trading Modes
    trading_env: str = "demo"
    dry_run: bool = True
    enable_live_trading: bool = False
    require_approval: bool = True
    
    # Strategy Params
    split_n: int = 7
    stop_loss_pct: float = -15.0
    take_profit: float = 30.0
    rsi_buy: int = 30
    rsi_sell: int = 70
    
    # Risk Management
    total_capital: float = 10000000.0
    max_positions: int = 3
    max_single_weight: float = 0.30
    cash_buffer: float = 0.20
    max_daily_loss_pct: float = 3.0
    
    # Others
    scan_universe_size: int = 50
    yfinance_timeout_seconds: int = 8
    kis_circuit_cooldown_seconds: int = 60
    trade_db_path: str = ".runtime/trades.sqlite"
    log_file: str = "logs/trader.log"
    active_model_version: str = "v1"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

config = Settings()
