"""Every enum column's allowed values, defined once. `base.enum_check` turns each into a CHECK."""

from enum import StrEnum

# Defined in the shared contract so the Agent, parser and database agree (P4.1).
from tally_contract.enums import AccountingDirection as AccountingDirection
from tally_contract.enums import AllocationType as AllocationType
from tally_contract.enums import CollectionType as CollectionType


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


class KeyListStatus(StrEnum):
    """D-041: a key list is staged while RECEIVING, then evaluated once."""

    RECEIVING = "RECEIVING"
    APPLIED = "APPLIED"
    SUSPICIOUS = "SUSPICIOUS"  # the D-007 guard fired; nothing was marked missing
    CONFIRMED = "CONFIRMED"  # an Owner/Admin waived the guard for the next list
    ABANDONED = "ABANDONED"  # its run closed before the last chunk arrived


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


class ReconOverall(StrEnum):
    """A reconciliation run as a whole (D-048 #8)."""

    PASS = "PASS"
    FAIL = "FAIL"  # a comparison failed, or something that must match could not be compared
    INCOMPLETE = "INCOMPLETE"  # nothing failed, but the run did not bring everything (PARTIAL)


class TallyValueKind(StrEnum):
    """What a staged Tally reconciliation value is (D-048)."""

    TOTAL = "TOTAL"  # debit/credit sums per (ledger, voucher type, period), GATE-G36
    LEDGER_CLOSING = "LEDGER_CLOSING"  # a ledger's closing balance, Dr +, GATE-G19
    STOCK_CLOSING = "STOCK_CLOSING"  # an item's closing quantity, GATE-G18


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
    """ai_tool_log.status. Not in SRS 5.10, which names the column but no values (D-032)."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class AnomalyRule(StrEnum):
    """anomaly_flags.rule_triggered. Free text until P15 (D-032); now checked."""

    # amount > mean + anomaly.deviation_sd x SD AND amount >= anomaly.min_average_multiple x mean
    # (FR-3.2 as amended by D-015 / D-055 #1)
    UNUSUALLY_LARGE_SD = "UNUSUALLY_LARGE_SD"
    # amount > previous maximum x anomaly.max_multiplier; inactive until that is set (FR-3.2)
    UNUSUALLY_LARGE_MULTIPLE = "UNUSUALLY_LARGE_MULTIPLE"
    # same party, amount, base voucher type, within anomaly.duplicate_window_days (D-055 #2)
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"


class ExplanationUnavailableReason(StrEnum):
    """Why an explanation is UNAVAILABLE (D-055 #12). Shown to the owner, and counted by
    `GET .../anomalies/explanation-health` so the model choice can be revisited with data."""

    NOT_CONFIGURED = "NOT_CONFIGURED"  # no API key or no model id in the environment
    CLAUDE_UNREACHABLE = "CLAUDE_UNREACHABLE"  # connection or API error (AC-58)
    TIMEOUT = "TIMEOUT"
    REFUSED = "REFUSED"  # stop_reason "refusal"
    NUMBER_NOT_IN_EVIDENCE = "NUMBER_NOT_IN_EVIDENCE"  # FR-3.6: discarded by the number check
