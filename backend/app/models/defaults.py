"""Tally's predefined groups and the default classification allow-lists (D-001, SRS 18.2).

Allow-list defaults live here, not in company_settings: that table is per company and holds
only overrides; the settings registry (P2) falls back to these values (D-031).
"""

from typing import Final

from app.models.enums import Nature

# Primary group -> (nature, predefined sub-groups under it). Verify against a live export
# (G13, G32). Reserved names equal these default display names (D-001).
PREDEFINED_GROUPS: Final[dict[str, tuple[Nature, tuple[str, ...]]]] = {
    "Capital Account": (Nature.LIABILITY, ("Reserves & Surplus",)),
    "Loans (Liability)": (Nature.LIABILITY, ("Bank OD A/c", "Secured Loans", "Unsecured Loans")),
    "Current Liabilities": (Nature.LIABILITY, ("Duties & Taxes", "Provisions", "Sundry Creditors")),
    "Branch / Divisions": (Nature.LIABILITY, ()),
    "Suspense A/c": (Nature.LIABILITY, ()),
    "Fixed Assets": (Nature.ASSET, ()),
    "Investments": (Nature.ASSET, ()),
    "Current Assets": (
        Nature.ASSET,
        (
            "Bank Accounts",
            "Cash-in-Hand",
            "Deposits (Asset)",
            "Loans & Advances (Asset)",
            "Stock-in-Hand",
            "Sundry Debtors",
        ),
    ),
    "Misc. Expenses (ASSET)": (Nature.ASSET, ()),
    "Sales Accounts": (Nature.INCOME, ()),
    "Direct Incomes": (Nature.INCOME, ()),
    "Indirect Incomes": (Nature.INCOME, ()),
    "Purchase Accounts": (Nature.EXPENSE, ()),
    "Direct Expenses": (Nature.EXPENSE, ()),
    "Indirect Expenses": (Nature.EXPENSE, ()),
}

PREDEFINED_GROUP_NAMES: Final[frozenset[str]] = frozenset(
    name for primary, (_, subs) in PREDEFINED_GROUPS.items() for name in (primary, *subs)
)


def _predefined(*reserved_names: str) -> list[dict[str, str]]:
    return [{"type": "PREDEFINED", "reserved_name": name} for name in reserved_names]


DEFAULT_CLASSIFICATION_ALLOW_LISTS: Final[dict[str, list[dict[str, str]]]] = {
    "classification.sales_groups": _predefined("Sales Accounts"),
    "classification.purchase_groups": _predefined("Purchase Accounts"),
    "classification.expense_groups": _predefined("Direct Expenses", "Indirect Expenses"),
    "classification.cash_bank_groups": _predefined("Cash-in-Hand", "Bank Accounts"),
    "classification.tax_groups": _predefined("Duties & Taxes"),
}
