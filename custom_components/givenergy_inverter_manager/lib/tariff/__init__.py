"""Tariff model, energy and cost accumulation, and bill maths. No knowledge of Home Assistant."""

from .accumulator import CounterMemory, EnergyAccumulator
from .bands import band_at, export_band_at, export_by_band, no_holidays
from .billing import BillBreakdown, money
from .compile import Locale, definition_from_config
from .config import TariffConfig, cheapest_period
from .definition import SCHEMA_VERSION, DefinitionError, TariffDefinition
from .definition_parse import load_definition, parse_definition
from .engine import BillInputs, CheckFailed, Line, PricedBill, price_bill, verify_checks
from .index import (
    ChecksumMismatch,
    StaticSource,
    TariffIndex,
    TariffSource,
    build_index,
    checksum_of,
    find_tariff,
    load_revision,
    parse_index,
    revision_in_force,
)
from .period_bill import (
    PeriodBill,
    PeriodRules,
    bill_period_bounds,
    months_of,
    price_period,
    start_day_of,
    start_month_of,
)
from .periods import RatePeriod
from .price_curve import MarginalPrices, PriceSlot, marginal_prices, price_curve
from .reprice import BillPeriod, Repriced, Rounding, import_by_band, reprice
from .savings import Battery, Savings, savings
from .slot_history import SlotHistory
from .slots import DEFAULT_LOADS, FLOWS, SlotDay, SlotEnergy, StoredSlotDay
from .stored_energy import StoredEnergy, stored_energy_change, value_per_stored_kwh
from .windows import Window, WindowSearch, find_window

__all__ = [
    "SCHEMA_VERSION",
    "ChecksumMismatch",
    "StaticSource",
    "TariffIndex",
    "TariffSource",
    "build_index",
    "checksum_of",
    "find_tariff",
    "load_revision",
    "parse_index",
    "revision_in_force",
    "Locale",
    "definition_from_config",
    "band_at",
    "export_band_at",
    "export_by_band",
    "no_holidays",
    "PeriodBill",
    "PeriodRules",
    "bill_period_bounds",
    "price_period",
    "start_day_of",
    "months_of",
    "start_month_of",
    "BillInputs",
    "CheckFailed",
    "Line",
    "PricedBill",
    "price_bill",
    "verify_checks",
    "BillPeriod",
    "DefinitionError",
    "TariffDefinition",
    "load_definition",
    "parse_definition",
    "MarginalPrices",
    "PriceSlot",
    "marginal_prices",
    "price_curve",
    "Battery",
    "Savings",
    "savings",
    "Window",
    "WindowSearch",
    "find_window",
    "Repriced",
    "Rounding",
    "import_by_band",
    "reprice",
    "BillBreakdown",
    "CounterMemory",
    "EnergyAccumulator",
    "DEFAULT_LOADS",
    "FLOWS",
    "RatePeriod",
    "SlotDay",
    "SlotEnergy",
    "SlotHistory",
    "StoredSlotDay",
    "StoredEnergy",
    "TariffConfig",
    "cheapest_period",
    "money",
    "stored_energy_change",
    "value_per_stored_kwh",
]
