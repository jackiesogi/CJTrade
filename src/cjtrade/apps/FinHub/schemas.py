"""Request and response shapes.

Only the inbound ones are strict. Anything FinHub proxies from the engine or
the broker is passed through as-is rather than re-modelled: a Pydantic mirror
of the engine's `/status` would have to be edited every time the engine adds a
monitor field, and the field would silently vanish from the UI until it was.
"""
from datetime import datetime
from typing import List
from typing import Optional

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import EmailStr
from pydantic import Field
from pydantic import field_validator


# ── Identity ──────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str = Field(min_length=8)


class UserSchema(BaseModel):
    id: int
    username: str
    email: str

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


# ── Runs ──────────────────────────────────────────────────────────────────────

class RunCreate(BaseModel):
    """A run request from the New Run form.

    Loosely typed on purpose: `RunConfig.parse` does the real validation and
    bounding, so the rules live in one place rather than being half here and
    half there. This only keeps obvious nonsense out of the function.
    """
    symbols: List[str] = Field(default_factory=list)
    mode: str = "backtest"
    days: int = 20
    fund: float = 1_000_000.0
    speed: float = 1.0
    start_date: str = ""
    interval: str = "1m"          # 1m|5m|15m|30m|1h|1d — what one bar is


class RunSchema(BaseModel):
    id: int
    session_id: Optional[str] = None
    broker: str
    mode: str
    symbols: str
    days: int
    fund: float
    speed: float
    start_date: Optional[str] = None
    # Defaulted rather than required: rows written before the column existed
    # have no value, and they were all 1m because that was the only thing the
    # engine ran.
    interval: Optional[str] = "1m"
    status: str
    exit_code: Optional[int] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    bars_served: Optional[int] = None
    final_equity: Optional[float] = None
    pnl: Optional[float] = None
    fills: Optional[int] = None
    round_trips: Optional[int] = None
    win_rate: Optional[float] = None
    halt_reason: Optional[str] = None

    class Config:
        from_attributes = True


# ── Manual trading ────────────────────────────────────────────────────────────

class OrderCreate(BaseModel):
    """A manual order.

    `odd_lot` rather than a lot name because that is the only choice the
    broker's buy/sell path actually offers: it picks IntraDayOdd or Common from
    this one flag and always sends a limit ROD order. Exposing a free-text lot
    would imply options that do not exist.

    No price-tick or lot-size rounding is applied, here or anywhere in CJTrade.
    The price goes to the broker as typed and the broker decides.
    """
    symbol: str = Field(min_length=3, max_length=8)
    action: str = Field(pattern="^(BUY|SELL)$")
    quantity: int = Field(gt=0, le=10_000_000)
    price: float = Field(gt=0, le=1_000_000)
    odd_lot: bool = True
    confirm: bool = Field(
        default=False,
        description="Must be true. A manual order bypasses the engine's risk "
                    "gate, so it is not something to send by accident.")


class ManualOrderSchema(BaseModel):
    id: int
    order_id: str
    symbol: str
    action: str
    quantity: int
    price: float
    order_lot: str
    status: str
    message: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Audit ─────────────────────────────────────────────────────────────────────

class AuditLogSchema(BaseModel):
    id: int
    action: str
    target: str
    details: str
    timestamp: datetime

    class Config:
        from_attributes = True


# ── Strategies ────────────────────────────────────────────────────────────────

# Trimmed before the pattern is applied, so " 0050 " from a form field is a
# symbol rather than a 422. The pattern still rejects a symbol with a space
# *inside* it, which is two symbols in one field.
#
# Field by field rather than `str_strip_whitespace` on the model, because that
# setting is model-wide and would also strip `source` -- silently deleting the
# trailing newline from every file anybody saves.
def _trim(value):
    return value.strip() if isinstance(value, str) else value


class StrategyCreate(BaseModel):
    """A new strategy. `source` is optional — left out, the server fills in a
    working starter strategy with the name and symbol already in it, because a
    blank editor is the worst place to learn an API from."""
    name: str = Field(min_length=1, max_length=80)
    symbol: str = Field(min_length=1, max_length=12,
                        pattern=r"^[A-Za-z0-9._-]+$")
    source: Optional[str] = None

    _trim_text = field_validator("name", "symbol",
                                 mode="before")(_trim)


class StrategyUpdate(BaseModel):
    """Every field optional, so saving the editor does not have to resend the
    name and symbol, and renaming does not have to resend the source."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    symbol: Optional[str] = Field(default=None, min_length=1, max_length=12,
                                  pattern=r"^[A-Za-z0-9._-]+$")
    source: Optional[str] = None
    enabled: Optional[bool] = None

    _trim_text = field_validator("name", "symbol",
                                 mode="before")(_trim)


class StrategySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    symbol: str
    source: str
    enabled: bool = True
    seeded_from: Optional[str] = None
    last_check_ok: Optional[int] = None
    last_check_error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StrategySummary(BaseModel):
    """The list view. Without `source`, because a list of twenty strategies is
    otherwise a list of twenty files."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    symbol: str
    enabled: bool = True
    seeded_from: Optional[str] = None
    last_check_ok: Optional[int] = None
    last_check_error: Optional[str] = None
    updated_at: Optional[datetime] = None


class StrategyCheckRequest(BaseModel):
    """Check source that may not be saved yet, which is the normal case — the
    editor validates what is on screen."""
    source: str = Field(max_length=256_000)


class EnabledPatch(BaseModel):
    """Switch a strategy on or off. A body rather than two routes, so the UI
    can send the state it wants instead of having to know the current one."""
    enabled: bool


class StrategyCreateFrom(StrategyCreate):
    """StrategyCreate plus which template to start from."""
    kind: Optional[str] = Field(default=None, pattern=r"^[a-z]{2,10}$")
