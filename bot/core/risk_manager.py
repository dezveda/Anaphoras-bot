import logging
from typing import Callable, Optional, Union, Awaitable # Added Awaitable
import asyncio # Added asyncio

class BasicRiskManager:
    def __init__(self,
                 account_balance_provider_fn: Callable[[], Awaitable[Optional[float]]], # Now expects an async callable
                 default_risk_per_trade_perc: float = 0.01, # 1% default risk
                 logger_name: str = 'algo_trader_bot'):
        """
        Initializes the BasicRiskManager.

        Args:
            account_balance_provider_fn: An asynchronous function that returns the current account balance as a float.
            default_risk_per_trade_perc: Default percentage of account balance to risk per trade (e.g., 0.01 for 1%).
            logger_name: Name for the logger.
        """
        self.logger = logging.getLogger(logger_name)
        self.account_balance_provider_fn = account_balance_provider_fn

        if not (0 < default_risk_per_trade_perc < 1):
            self.logger.warning(f"Initial default_risk_per_trade_perc {default_risk_per_trade_perc*100:.2f}% is out of typical range (0-100%). Clamping to 1%.")
            self.default_risk_per_trade_perc = 0.01
        else:
            self.default_risk_per_trade_perc = default_risk_per_trade_perc

        self.logger.info(f"BasicRiskManager initialized. Default risk per trade: {self.default_risk_per_trade_perc*100:.2f}%. Balance provider type: {type(account_balance_provider_fn)}")

    async def get_current_balance(self) -> Optional[float]:
        """Gets the current account balance using the provided asynchronous function."""
        try:
            balance = await self.account_balance_provider_fn() # Await the async provider
            if isinstance(balance, (int, float)) and balance >= 0:
                return float(balance)
            self.logger.warning(f"Invalid balance received from provider: {balance} (Type: {type(balance)}). Expected float >= 0.")
            return None
        except Exception as e:
            self.logger.error(f"Error getting balance from provider: {e}", exc_info=True)
            return None

    async def calculate_position_size_usd(self, risk_per_trade_perc: Optional[float] = None) -> Optional[float]:
        """
        Calculates the maximum position size in USD based on risk percentage and current balance.
        """
        current_balance = await self.get_current_balance() # Await balance
        if current_balance is None:
            self.logger.warning("Cannot calculate position size USD: Invalid or unavailable current balance.")
            return None

        risk_perc_to_use = risk_per_trade_perc if risk_per_trade_perc is not None else self.default_risk_per_trade_perc

        if not (0 < risk_perc_to_use <= 0.5):
             self.logger.warning(f"Risk percentage {risk_perc_to_use*100:.2f}% is out of valid range (0-50%). Using default {self.default_risk_per_trade_perc*100:.2f}%.")
             risk_perc_to_use = self.default_risk_per_trade_perc

        position_size_usd = current_balance * risk_perc_to_use
        self.logger.debug(f"Calculated position size in USD: {position_size_usd:.2f} (Balance: {current_balance:.2f}, RiskPerc: {risk_perc_to_use*100:.2f}%)")
        return position_size_usd

    def calculate_quantity_from_risk_usd(self,
                                         position_size_usd: Optional[float],
                                         entry_price: float,
                                         stop_loss_price: float,
                                         quantity_precision: int = 3,
                                         min_quantity: float = 0.001,
                                         price_precision: int = 2) -> Optional[float]:
        # This method itself doesn't need to be async if position_size_usd is already calculated
        if position_size_usd is None or position_size_usd <= 1e-8:
            self.logger.warning(f"Invalid position_size_usd ({position_size_usd}) for quantity calculation.")
            return None

        if entry_price <= 1e-8 or stop_loss_price <= 1e-8:
            self.logger.warning(f"Cannot calculate quantity: Entry ({entry_price:.{price_precision}f}) or SL price ({stop_loss_price:.{price_precision}f}) is zero or negative.")
            return None

        risk_per_unit_asset = abs(entry_price - stop_loss_price)
        if risk_per_unit_asset < 1e-8:
            self.logger.warning(f"Cannot calculate quantity: Entry price ({entry_price:.{price_precision}f}) and SL price ({stop_loss_price:.{price_precision}f}) are too close or the same.")
            return None

        quantity_asset = position_size_usd / risk_per_unit_asset
        rounded_quantity = round(quantity_asset, quantity_precision)

        if rounded_quantity < min_quantity:
             self.logger.warning(f"Calculated quantity {rounded_quantity} is less than min_quantity {min_quantity}. Consider adjusting risk or SL distance.")
             return None

        self.logger.debug(f"Calculated quantity (asset): {rounded_quantity} (RiskUSD: {position_size_usd:.2f}, Entry: {entry_price:.{price_precision}f}, SL: {stop_loss_price:.{price_precision}f})")
        return rounded_quantity

    async def validate_order_risk(self,
                                  quantity_asset: float,
                                  entry_price: float,
                                  stop_loss_price: float,
                                  max_allowed_risk_perc_of_balance: Optional[float] = None) -> bool:
        """
        Validates if the proposed trade (quantity, entry, SL) fits within the max allowed risk percentage.
        """
        current_balance = await self.get_current_balance() # Await balance
        if current_balance is None:
            self.logger.warning("Cannot validate order risk: Invalid or unavailable current balance.")
            return False

        max_risk_perc = max_allowed_risk_perc_of_balance if max_allowed_risk_perc_of_balance is not None \
                        else self.default_risk_per_trade_perc

        if not (0 < max_risk_perc <= 0.5):
            self.logger.warning(f"Max allowed risk percentage {max_risk_perc*100:.2f}% is out of valid range (0-50%). Using default {self.default_risk_per_trade_perc*100:.2f}%.")
            max_risk_perc = self.default_risk_per_trade_perc

        proposed_risk_per_unit = abs(entry_price - stop_loss_price)
        if proposed_risk_per_unit < 1e-8:
            self.logger.warning("Risk validation: Entry and SL are too close.")
            return False

        proposed_total_risk_usd = proposed_risk_per_unit * quantity_asset
        allowed_total_risk_usd = current_balance * max_risk_perc

        if proposed_total_risk_usd > allowed_total_risk_usd:
            self.logger.warning(
                f"Order risk validation FAILED. "
                f"Proposed Risk USD: {proposed_total_risk_usd:.2f} "
                f"exceeds Allowed Risk USD: {allowed_total_risk_usd:.2f}."
            )
            return False

        self.logger.debug(
            f"Order risk validation PASSED. "
            f"Proposed Risk USD: {proposed_total_risk_usd:.2f}, "
            f"Allowed Risk USD: {allowed_total_risk_usd:.2f}."
        )
        return True


async def main_test_async_risk_manager(): # Renamed for clarity
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s')
    logger = logging.getLogger('algo_trader_bot') # Ensure logger name matches

    async def async_dummy_balance_provider_success() -> Optional[float]:
        logger.debug("Async dummy balance provider called (success)")
        await asyncio.sleep(0.01) # Simulate async call
        return 10000.0

    async def async_dummy_balance_provider_fail() -> Optional[float]:
        logger.debug("Async dummy balance provider called (failure)")
        await asyncio.sleep(0.01)
        return None

    risk_manager_async_ok = BasicRiskManager(account_balance_provider_fn=async_dummy_balance_provider_success, default_risk_per_trade_perc=0.02)

    logger.info("\n--- Testing with ASYNC successful balance provider (10000 USD, 2% risk) ---")
    balance = await risk_manager_async_ok.get_current_balance()
    logger.info(f"Async Get Current Balance: {balance}")

    pos_size_usd = await risk_manager_async_ok.calculate_position_size_usd()
    logger.info(f"Async Calculate Position Size USD (default 2%): {pos_size_usd}")

    qty1 = risk_manager_async_ok.calculate_quantity_from_risk_usd(pos_size_usd, 50000, 49500) # This method is sync
    logger.info(f"Async Calculate Quantity (Risk:{pos_size_usd}, Entry:50k, SL:49.5k): {qty1}")

    valid1 = await risk_manager_async_ok.validate_order_risk(0.002, 50000, 49500)
    logger.info(f"Async Validate Order Risk (Proposed: 100 USD vs Allowed: {pos_size_usd}): {valid1}")

    risk_manager_async_fail = BasicRiskManager(account_balance_provider_fn=async_dummy_balance_provider_fail)
    logger.info("\n--- Testing with ASYNC failing balance provider ---")
    balance_fail = await risk_manager_async_fail.get_current_balance()
    logger.info(f"Async Get Current Balance (expect None): {balance_fail}")
    pos_size_usd_fail = await risk_manager_async_fail.calculate_position_size_usd()
    logger.info(f"Async Calculate Position Size USD (expect None): {pos_size_usd_fail}")


if __name__ == '__main__':
    asyncio.run(main_test_async_risk_manager())
```
