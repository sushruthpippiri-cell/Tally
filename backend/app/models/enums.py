"""Every enum column's allowed values, defined once. `base.enum_check` turns each into a CHECK."""

from enum import StrEnum


class RoleName(StrEnum):
    OWNER = "OWNER"
    ACCOUNTANT = "ACCOUNTANT"
    ADMIN = "ADMIN"


class AgentStatus(StrEnum):
    REGISTERING = "REGISTERING"
    ACTIVE = "ACTIVE"
    OFFLINE = "OFFLINE"
    INCOMPATIBLE = "INCOMPATIBLE"
    REVOKED = "REVOKED"


class TallyStatus(StrEnum):
    """Agent-reported Tally state (D-025)."""

    OK = "OK"
    TALLY_UNREACHABLE = "TALLY_UNREACHABLE"
    TALLY_SERVER_DISABLED = "TALLY_SERVER_DISABLED"
    TDL_NOT_LOADED = "TDL_NOT_LOADED"
    COMPANY_NOT_LOADED = "COMPANY_NOT_LOADED"
    COMPANY_MISMATCH = "COMPANY_MISMATCH"


class CommandType(StrEnum):
    RUN_SYNC = "RUN_SYNC"


class SyncMode(StrEnum):
    FULL = "FULL"
    INCREMENTAL = "INCREMENTAL"
    DATE_RANGE = "DATE_RANGE"
    RECONCILIATION = "RECONCILIATION"


class CommandStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    FAILED_AGENT_LOST = "FAILED_AGENT_LOST"


class MasterStatus(StrEnum):
    ACTIVE = "ACTIVE"
    MISSING_IN_TALLY = "MISSING_IN_TALLY"
    INACTIVE = "INACTIVE"


class VoucherStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    MISSING_IN_TALLY = "MISSING_IN_TALLY"


class GroupResolution(StrEnum):
    """D-001: only a broken chain (missing parent or loop) is UNRESOLVED_GROUP."""

    RESOLVED = "RESOLVED"
    UNRESOLVED_GROUP = "UNRESOLVED_GROUP"


class VoucherTypeResolution(StrEnum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


class Nature(StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class BaseVoucherType(StrEnum):
    SALES = "SALES"
    PURCHASE = "PURCHASE"
    RECEIPT = "RECEIPT"
    PAYMENT = "PAYMENT"
    CONTRA = "CONTRA"
    JOURNAL = "JOURNAL"
    CREDIT_NOTE = "CREDIT_NOTE"
    DEBIT_NOTE = "DEBIT_NOTE"
    OTHER = "OTHER"


class AccountingDirection(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AllocationType(StrEnum):
    """Normalized bill allocation type (D-004)."""

    NEW_REF = "NEW_REF"
    AGST_REF = "AGST_REF"
    ADVANCE = "ADVANCE"
    ON_ACCOUNT = "ON_ACCOUNT"
    UNSUPPORTED = "UNSUPPORTED"


class CollectionType(StrEnum):
    COMPANY = "COMPANY"
    GROUP = "GROUP"
    LEDGER = "LEDGER"
    VOUCHER_TYPE = "VOUCHER_TYPE"
    STOCK_ITEM = "STOCK_ITEM"
    COST_CENTRE = "COST_CENTRE"
    VOUCHER = "VOUCHER"


class WatermarkStatus(StrEnum):
    """Not in SRS 5.9, which names the column but no values (D-031)."""

    NEVER_SYNCED = "NEVER_SYNCED"
    OK = "OK"
    FAILED = "FAILED"


class SyncRunStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class ReconResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class SettingDataType(StrEnum):
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    JSON = "JSON"


class ExplanationStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PENDING = "PENDING"


class ToolCallStatus(StrEnum):
    """ai_tool_log.status. Not in SRS 5.10, which names the column but no values (D-031)."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
