from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Venue(str, Enum):
    BINANCE = "binance"
    WALLET = "wallet"  # On-chain wallet (DEX venue)


@dataclass
class Balance:
    venue: Venue
    asset: str
    free: Decimal = Decimal("0")
    locked: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.free + self.locked


class InventoryTracker:
    """
    Tracks positions across CEX and DEX venues.
    Single source of truth for where your money is.
    """

    def __init__(self, venues: list[Venue] = None):
        """Initialize tracker for given venues."""
        self.venues = venues or [Venue.BINANCE, Venue.WALLET]
        self._balances: dict[Venue, dict[str, Balance]] = {v: {} for v in self.venues}
        self.last_update = datetime.now(timezone.utc)

    def _get_balance(self, venue: Venue, asset: str) -> Balance:
        if asset not in self._balances[venue]:
            self._balances[venue][asset] = Balance(venue, asset)
        return self._balances[venue][asset]

    def update_from_cex(self, venue: Venue, balances: dict[str, dict[str, Decimal]]):
        """
        Update balances from ExchangeClient.fetch_balance().
        Replaces previous snapshot for this venue.

        Args:
            venue: Which CEX venue
            balances: {asset: {free, locked, total}} from ExchangeClient
        """
        for asset, data in balances.items():
            bal = self._get_balance(venue, asset)
            bal.free = data.get("free", Decimal("0"))
            bal.locked = data.get("locked", Decimal("0"))
        self.last_update = datetime.now(timezone.utc)

    def update_from_wallet(self, venue: Venue, balances: dict[str, Decimal]):
        """
        Update balances from on-chain wallet query.

        Args:
            venue: Wallet venue
            balances: {asset: amount} from chain/ module
        """
        for asset, amount in balances.items():
            bal = self._get_balance(venue, asset)
            bal.free = amount
            bal.locked = Decimal("0")
        self.last_update = datetime.now(timezone.utc)

    def snapshot(self, prices: Optional[dict[str, Decimal]] = None) -> dict:
        """
        Full portfolio snapshot at current time.

        Returns:
        {
            'timestamp': datetime,
            'venues': {
                'binance': {'ETH': {'free': ..., 'locked': ..., 'total': ...}, ...},
                'wallet':  {'ETH': {'free': ..., 'locked': ..., 'total': ...}, ...},
            },
            'totals': {
                'ETH':  Decimal('20.0'),
                'USDT': Decimal('40000.0'),
            },
            'total_usd': Decimal('80200.0'),  # requires price feed
        }
        """
        venus_data = {}
        totals = {}

        for venue in self.venues:
            v_data = {}
            for asset, bal in self._balances[venue].items():
                v_data[asset] = {
                    "free": bal.free,
                    "locked": bal.locked,
                    "total": bal.total,
                }
                totals[asset] = totals.get(asset, Decimal("0")) + bal.total
            venus_data[venue.value] = v_data

        total_usd = Decimal("0")
        if prices:
            for asset, amount in totals.items():
                price = prices.get(asset, Decimal("0"))
                total_usd += price * amount

        return {
            "timestamp": datetime.now(timezone.utc),
            "venues": venus_data,
            "total": totals,
            "total_usd": total_usd,
        }

    def get_available(self, venue: Venue, asset: str) -> Decimal:
        """
        How much of `asset` is available to trade at `venue`.
        Returns free balance only (not locked in orders).
        """
        if asset not in self._balances:
            return Decimal("0")
        return self._balances[venue][asset].free

    def can_execute(
        self,
        buy_venue: Venue,
        buy_asset: str,  # What you're spending (e.g., "USDT")
        buy_amount: Decimal,  # How much you're spending
        sell_venue: Venue,
        sell_asset: str,  # What you're selling (e.g., "ETH")
        sell_amount: Decimal,  # How much you're selling
    ) -> dict:
        """
        Pre-flight check: can we execute both legs of an arb?

        Returns:
        {
            'can_execute': bool,
            'buy_venue_available': Decimal,
            'buy_venue_needed': Decimal,
            'sell_venue_available': Decimal,
            'sell_venue_needed': Decimal,
            'reason': str or None,  # Why not, if can_execute=False
        }
        """
        buy_avail = self.get_available(buy_venue, buy_asset)
        sell_avail = self.get_available(sell_venue, sell_asset)

        buy_ok = buy_avail >= buy_amount
        sell_ok = sell_avail >= sell_amount

        reason = None
        if not buy_ok:
            reason = (
                f"Insufficient {buy_asset} on {buy_venue.value}."
                f" Have {buy_avail}, need {buy_amount}"
            )
        elif not sell_ok:
            reason = (
                f"Insufficient {sell_asset} on {sell_venue.value}."
                f" Have {sell_avail}, need {sell_amount}"
            )

        return {
            "can_execute": buy_ok or sell_ok,
            "buy_venue_available": buy_avail,
            "buy_venue_needed": buy_amount,
            "sell_venue_available": sell_avail,
            "sell_venue_needed": sell_amount,
            "reason": reason,
        }

    def record_trade(
        self,
        venue: Venue,
        side: str,  # "buy" or "sell"
        base_asset: str,
        quote_asset: str,
        base_amount: Decimal,
        quote_amount: Decimal,
        fee: Decimal,
        fee_asset: str,
    ):
        """
        Update internal balances after a trade executes.
        Must handle: buy increases base / decreases quote,
                     sell decreases base / increases quote,
                     fee deducted from fee_asset.
        """
        base_bal = self._get_balance(venue, base_asset)
        quote_bal = self._get_balance(venue, quote_asset)
        fee_bal = self._get_balance(venue, fee_asset)

        if side == "buy":
            base_bal.free -= base_amount
            quote_bal.free += quote_amount
        elif side == "sell":
            base_bal.free += base_amount
            quote_bal.free += quote_amount
        fee_bal.free -= fee

    def skew(self, asset: str) -> dict:
        """
        Calculate distribution skew for an asset across venues.

        Returns:
        {
            'asset': str,
            'total': Decimal,
            'venues': {
                'binance': {'amount': Decimal, 'pct': float, 'deviation_pct': float},
                'wallet':  {'amount': Decimal, 'pct': float, 'deviation_pct': float},
            },
            'max_deviation_pct': float,
            'needs_rebalance': bool,  # True if max_deviation > 30%
        }
        """
        total = Decimal("0")
        venue_totals = {}

        for venue in self.venues:
            amount = self._balances[venue].get(asset, Balance(venue, asset)).total
            venue_totals[venue] = amount
            total += amount

        venue_res = {}
        max_dev = 0.0

        if total > 0:
            for venue, amount in venue_totals.items():
                pct = float(amount / total) * 100
                deviation = pct - 50

                if abs(deviation) > max_dev:
                    max_dev = abs(deviation)

                venue_res[venue.value] = {
                    "amount": amount,
                    "pct": pct,
                    "deviation": deviation,
                }
        else:
            for venue in self.venues:
                venue_res[venue.value] = {
                    "amount": Decimal("0"),
                    "pct": 0.0,
                    "deviation_pct": 0.0,
                }

        return {
            "asset": asset,
            "total": total,
            "venues": venue_res,
            "max_deviation_pct": max_dev,
            "needs_rebalance": max_dev > 30.0,
        }
