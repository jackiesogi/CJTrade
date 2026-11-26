"""FinHub's side of the CJTrade boundary.

THE BROWSER NEVER TALKS TO CJTRADE
----------------------------------
Every call into the engine or the broker happens here, server-side, and the
page only ever talks to FinHub. That is a deliberate reversal of how this
started: `static/cjtrade_extension.js` used to `fetch('http://localhost:8899')`
straight from the page.

Why the reversal:

1. **CORS stops being a question.** Those two APIs can stay on loopback with
   no `Access-Control-Allow-Origin` header at all. A wildcard there would let
   any page the user happens to have open read their balance and positions,
   and a loopback bind does nothing about that, because the request comes from
   the user's own browser.
2. **One place knows the contract.** When ArenaX renames a field, one Python
   module breaks instead of three JS files.
3. **The engine's API is GET-only.** Trading goes to the broker, and that call
   needs an API key FinHub holds and the browser must not.

Three pieces:

* `EngineClient` -- the engine's read-only status API (`:8898`). Reports on a
  run in flight: progress, equity, risk state, per-bot monitors.
* `ArenaXClient` -- the broker (`:8802`). Account, orders, market data, and
  the only write path: placing and cancelling orders.
* `RunSupervisor` -- starts and stops the broker server and the engine as
  child processes, so a run's lifetime is tied to FinHub's.
"""
from .arenax_client import ArenaXClient
from .arenax_client import BrokerError
from .engine_client import EngineClient
from .engine_client import EngineUnavailable
from .strategy_tool import StrategyTool
from .strategy_tool import StrategyToolError
from .supervisor import RunConfig
from .supervisor import RunSupervisor
from .supervisor import SupervisorError

__all__ = [
    "ArenaXClient",
    "BrokerError",
    "EngineClient",
    "EngineUnavailable",
    "RunConfig",
    "RunSupervisor",
    "StrategyTool",
    "StrategyToolError",
    "SupervisorError",
]
