"""风控模块"""

from typing import Optional


class RiskManager:
    """仓位与止损等基础风控规则。"""

    def __init__(
        self,
        max_position_pct: float = 0.95,
        stop_loss_pct: float = 0.08,
    ):
        self.max_position_pct = max_position_pct
        self.stop_loss_pct = stop_loss_pct

    def position_size(self, cash: float, price: float) -> int:
        """按最大仓位比例计算可买股数（整百股）。"""
        if price <= 0:
            return 0
        max_shares = int(cash * self.max_position_pct / price)
        return max_shares // 100 * 100

    def hit_stop_loss(self, entry_price: float, current_price: float) -> bool:
        if entry_price <= 0:
            return False
        return (entry_price - current_price) / entry_price >= self.stop_loss_pct

    def check_order(
        self,
        side: str,
        quantity: int,
        cash: float,
        price: float,
    ) -> tuple[bool, Optional[str]]:
        if quantity <= 0:
            return False, "数量必须大于 0"
        if side == "buy" and quantity * price > cash:
            return False, "资金不足"
        return True, None
