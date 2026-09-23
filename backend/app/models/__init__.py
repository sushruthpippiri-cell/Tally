"""SQLAlchemy models. Importing this package registers every table on `Base.metadata`."""

from app.models.agents import Agent, AgentCommand, AgentRegistrationToken, SyncSchedule
from app.models.balances import (
    LedgerOpeningBalance,
    OpeningBillAllocation,
    StockOpeningBalance,
    StockSnapshot,
)
from app.models.base import Base
from app.models.company import Company, Role, User, UserRole
from app.models.masters import CostCentre, Group, Ledger, StockItem, VoucherType
from app.models.vouchers import (
    BillAllocation,
    CostCentreAllocation,
    Voucher,
    VoucherEntry,
    VoucherItem,
)

__all__ = [
    "Agent",
    "AgentCommand",
    "AgentRegistrationToken",
    "Base",
    "BillAllocation",
    "Company",
    "CostCentre",
    "CostCentreAllocation",
    "Group",
    "Ledger",
    "LedgerOpeningBalance",
    "OpeningBillAllocation",
    "Role",
    "StockItem",
    "StockOpeningBalance",
    "StockSnapshot",
    "SyncSchedule",
    "User",
    "UserRole",
    "Voucher",
    "VoucherEntry",
    "VoucherItem",
    "VoucherType",
]
