from src.config import config
from src.utils.logger import logger
from src.notifier.slack import slack_error

class RiskEngine:
    def __init__(self):
        self.daily_loss_halt = False
        
    def check_daily_loss(self, pnl: int) -> bool:
        if config.total_capital <= 0 or pnl >= 0:
            return False
        loss_pct = abs(pnl) / config.total_capital * 100
        if loss_pct >= config.max_daily_loss_pct:
            msg = f"Daily loss limit reached: {loss_pct:.1f}% >= {config.max_daily_loss_pct}%"
            if not self.daily_loss_halt:
                logger.info(f"[WARN] {msg}")
                slack_error(msg)
                self.daily_loss_halt = True
            return True
        return False

    def evaluate_order(self, action: str, qty: int, price: int, cash: int) -> dict:
        if self.daily_loss_halt and action == "buy":
            return {"approved": False, "reason": "Daily loss halt active"}
        
        if action == "buy":
            cost = qty * price
            if cost > cash:
                return {"approved": False, "reason": f"Not enough cash: need={cost:,}, cash={cash:,}"}
                
        return {"approved": True, "reason": "OK"}
