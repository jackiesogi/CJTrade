from .broker_base import BrokerInterface, Position, Quote, OrderResult
from typing import List, Dict, Any
import shioaji as sj
from datetime import datetime

class SinopacBroker(BrokerInterface):
    def __init__(self, **config: Any):
        super().__init__(**config)

        # Check required config parameters
        required_params = ['api_key', 'secret_key', 'ca_path', 'ca_passwd']
        for param in required_params:
            if param not in config:
                raise ValueError(f"SinopacBroker needs: {param}")

        self.api_key = config['api_key']
        self.secret_key = config['secret_key']
        self.ca_path = config['ca_path']
        self.ca_password = config['ca_passwd']
        self.simulation = config.get('simulation', True)

        self.api = sj.Shioaji(simulation=self.simulation)

    def connect(self) -> bool:
        try:
            self.api.login(
                api_key=self.api_key,
                secret_key=self.secret_key,
                # ca_path=self.ca_path,
                # ca_passwd=self.ca_password
            )
            self.api.activate_ca(
                ca_path=self.ca_path,
                ca_passwd=self.ca_password,
            )
            self._connected = True
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._connected:
            try:
                self.api.logout()
            except:
                pass
            finally:
                self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_positions(self) -> List[Position]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            # Get position (inventory) via shioaji api with stock_account
            positions = self.api.list_positions()
            result = []

            for pos in positions:
                # Convert to standard Position format
                position = Position(
                    symbol=pos.code,
                    quantity=pos.quantity,
                    avg_cost=pos.price,
                    current_price=pos.last_price,  # This comes from the position data
                    market_value=pos.quantity * pos.last_price,
                    unrealized_pnl=pos.pnl  # Unrealized P&L from shioaji
                )
                result.append(position)

            return result
        except Exception as e:
            print(f"Failed to get positions: {e}")
            return []

    def get_balance(self) -> float:
        """Get account balance"""
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            settlements = self.api.settlements
            if settlements:
                return settlements[0].available_balance
            return 0.0
        except Exception as e:
            print(f"Failed to get balance: {e}")
            return 0.0

    def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        result = {}
        try:
            for symbol in symbols:
                contract = self.api.Contracts.Stocks[symbol]
                snapshot = self.api.snapshots([contract])

                if snapshot and len(snapshot) > 0:
                    snap = snapshot[0]
                    quote = Quote(
                        symbol=symbol,
                        price=snap.close,
                        volume=snap.volume,
                        timestamp=datetime.now().isoformat()
                    )
                    result[symbol] = quote
        except Exception as e:
            print(f"Failed to get quotes: {e}")

        return result

    def place_order(self, symbol: str, action: str, quantity: int, price: float) -> OrderResult:
        """Place order"""
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            contract = self.api.Contracts.Stocks[symbol]

            order = self.api.Order(
                price=price,
                quantity=quantity,
                action=sj.constant.Action.Buy if action.upper() == 'BUY' else sj.constant.Action.Sell,
                price_type=sj.constant.StockPriceType.LMT,
                order_type=sj.constant.OrderType.ROD,
                account=self.api.stock_account
            )

            trade = self.api.place_order(contract, order)

            return OrderResult(
                order_id=trade.order.id,
                status="SUBMITTED",
                message="Order submitted"
            )
        except Exception as e:
            return OrderResult(
                order_id="",
                status="ERROR",
                message=f"Order failed: {e}"
            )

    def get_broker_name(self) -> str:
        return "sinopac"