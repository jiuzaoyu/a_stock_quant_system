from src.risk.manager import RiskManager


def test_stop_loss():
    rm = RiskManager(stop_loss_pct=0.1)
    assert rm.hit_stop_loss(100, 89) is True
    assert rm.hit_stop_loss(100, 95) is False
