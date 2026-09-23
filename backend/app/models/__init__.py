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
from app.models.config import (
    AiToolLog,
    AnomalyFlag,
    AuditLog,
    CompanySetting,
    CustomFieldMapping,
    FeatureConfig,
)
from app.models.masters import CostCentre, Group, Ledger, StockItem, VoucherType
from app.models.sync import (
    ReconciliationResult,
    SyncBatch,
    SyncError,
    SyncRun,
    SyncWatermark,
)
from app.models.vouchers import (
    BillAllocation,
    CostCentreAllocation,
    Voucher,
    VoucherEntry,
    VoucherItem,
)

__all__ = [
    "AiToolLog",
    "AnomalyFlag",
    "AuditLog",
    "Agent",
    "AgentCommand",
    "AgentRegistrationToken",
    "Base",
    "BillAllocation",
    "Company",
    "CompanySetting",
    "CostCentre",
    "CostCentreAllocation",
    "CustomFieldMapping",
    "FeatureConfig",
    "Group",
    "Ledger",
    "LedgerOpeningBalance",
    "OpeningBillAllocation",
    "ReconciliationResult",
    "Role",
    "StockItem",
    "StockOpeningBalance",
    "StockSnapshot",
    "SyncBatch",
    "SyncError",
    "SyncRun",
    "SyncSchedule",
    "SyncWatermark",
    "User",
    "UserRole",
    "Voucher",
    "VoucherEntry",
    "VoucherItem",
    "VoucherType",
]
