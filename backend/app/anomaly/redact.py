"""What may leave this system (SEC-1.12, D-055 #6, #8).

One function decides it, and both the MCP tool and the disclosure endpoint call that function, so
the disclosure cannot drift from what is actually sent.

Only two kinds of thing go out: **numbers the application computed**, and **our own constants**
(the rule name, the currency, the placeholder labels). Party and ledger names are typed into
TallyPrime by people — they may be individuals' names, and they could carry text written to
steer the explanation — so they never leave; neither do voucher numbers, voucher type names,
narration, dates, GUIDs, the company name or anything about the user.

The consequence is worth stating plainly: because no human-typed text reaches the prompt at all,
prompt injection through a Tally name is not *filtered* here, it is impossible. Real names are
put back locally, for display only.

The labels carry **no digits** (D-055 #8): "Voucher 1" and "Voucher 2" would have put 1 and 2
into every duplicate explanation, and the FR-3.6 number check would then have discarded it unless
those digits happened to be in the evidence — destroying exactly the explanations the check
exists to protect.
"""

from decimal import Decimal
from typing import Any

PARTY = "Party A"
VOUCHER = "Voucher A"
OTHER_VOUCHER = "Voucher B"
CURRENCY = "INR"

#: Every key the tool may return. The disclosure endpoint publishes this list, and a test holds
#: it against what `evidence()` actually produces.
FIELDS = (
    "rule",
    "currency",
    "party",
    "voucher",
    "other_voucher",
    "transaction_amount",
    "historical_average",
    "historical_maximum",
    "deviation_percent",
)


def _money(value: Decimal | None) -> str | None:
    """A figure as the database holds it, as a string (CLAUDE.md rule 10). Never a float."""
    return None if value is None else format(value, "f")


def evidence(
    *,
    rule: str,
    transaction_amount: Decimal | None,
    historical_average: Decimal | None = None,
    historical_max: Decimal | None = None,
    deviation_percent: Decimal | None = None,
    has_duplicate: bool = False,
) -> dict[str, Any]:
    """The redacted evidence for one anomaly — exactly the figures FR-3.4 stores, the rule, the
    currency and the placeholders. Keys whose value is absent are left out, so the payload never
    carries a null for a rule that has no such figure."""
    out: dict[str, Any] = {
        "rule": rule,
        "currency": CURRENCY,
        "party": PARTY,
        "voucher": VOUCHER,
        "transaction_amount": _money(transaction_amount),
    }
    if has_duplicate:
        out["other_voucher"] = OTHER_VOUCHER
    for key, value in (
        ("historical_average", historical_average),
        ("historical_maximum", historical_max),
        ("deviation_percent", deviation_percent),
    ):
        if value is not None:
            out[key] = _money(value)
    return {k: v for k, v in out.items() if v is not None}
