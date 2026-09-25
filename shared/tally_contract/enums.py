"""Enums shared by the Agent, the backend and the parser. The backend's models import these,
so the contract and the database CHECK constraints can never disagree."""

from enum import StrEnum


class CollectionType(StrEnum):
    COMPANY = "COMPANY"
    GROUP = "GROUP"
    LEDGER = "LEDGER"
    VOUCHER_TYPE = "VOUCHER_TYPE"
    STOCK_ITEM = "STOCK_ITEM"
    COST_CENTRE = "COST_CENTRE"
    VOUCHER = "VOUCHER"


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
