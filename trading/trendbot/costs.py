from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """국내 주식 매매 비용.

    기본값은 어림값이니 실제 증권사 수수료·당해 거래세율로 바꿔 쓸 것.
    - commission_rate: 증권사 수수료 (매수·매도 각각)
    - sell_tax_rate: 매도 시 증권거래세(+농특세). 시장·연도마다 다름
    - slippage_rate: 주문가 대비 체결가가 불리하게 밀리는 정도
    """

    commission_rate: float = 0.00015
    min_commission: float = 0.0
    sell_tax_rate: float = 0.0020
    slippage_rate: float = 0.0005

    def buy_price(self, price: float) -> float:
        return price * (1 + self.slippage_rate)

    def sell_price(self, price: float) -> float:
        return price * (1 - self.slippage_rate)

    def commission(self, gross: float) -> float:
        return max(gross * self.commission_rate, self.min_commission)

    def tax(self, gross: float) -> float:
        return gross * self.sell_tax_rate

    def round_trip_rate(self) -> float:
        """사고 팔 때 드는 총 비용 비율(수수료 2번 + 세금 + 슬리피지 2번)."""
        return 2 * self.commission_rate + self.sell_tax_rate + 2 * self.slippage_rate
