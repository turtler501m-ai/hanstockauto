import math
from src.config import config
from src.utils.logger import logger

class PortfolioAllocator:
    def __init__(self):
        self.max_single_weight = config.max_single_weight
        self.cash_buffer = config.cash_buffer

    def allocate(self, candidates: list[dict], cash: int, total_capital: int) -> list[dict]:
        """
        후보 종목들의 점수(score)와 변동성(volatility)을 고려하여
        포트폴리오 비중을 계산하고 최종 주문 수량을 결정합니다.
        """
        if not candidates:
            return []
            
        deployable = total_capital * (1 - self.cash_buffer)
        
        # Softmax 또는 가중평균을 위한 전체 점수 합산
        score_sum = sum(max(0.1, c.get("score", 0)) for c in candidates)
        if score_sum <= 0:
            score_sum = 1.0

        orders = []
        for c in candidates:
            price = c.get("limit_price", 0)
            if price <= 0:
                continue
                
            score = max(0.1, c.get("score", 0))
            
            # AI 예측 점수 비례 가중치 (리스크 최소화 전략 적용 가능)
            target_weight = min(self.max_single_weight, (score / score_sum) * (1 - self.cash_buffer))
            
            # 비용 적용 및 수량 계산
            per_position = deployable * target_weight
            cost_mult = 1.001
            qty = math.floor(per_position / (price * cost_mult))
            
            if qty > 0:
                orders.append({
                    "ticker": c["ticker"],
                    "quantity": qty,
                    "limit_price": price,
                    "estimated_cost": qty * price * cost_mult,
                    "score": c.get("score", 0),
                    "reasons": c.get("reasons", [])
                })

        # 예산 초과 방지
        total_cost = sum(o["estimated_cost"] for o in orders)
        budget = min(deployable, cash)
        if total_cost > budget and budget > 0:
            scale = budget / total_cost
            for o in orders:
                o["quantity"] = math.floor(o["quantity"] * scale)
                o["estimated_cost"] = o["quantity"] * o["limit_price"] * cost_mult
                
        return [o for o in orders if o["quantity"] > 0]
