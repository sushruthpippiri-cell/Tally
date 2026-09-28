"""P8.1: ledger classes from the allow-lists (ACC-7.3, 7.6, D-001, D-044 #3)."""

from app.analytics.classification import load_classes
from app.models.enums import Nature, SettingDataType
from tests.analytics.books import Books


async def test_default_lists_and_customer_supplier_anchors(books: Books) -> None:
    g = books.groups
    classes = await load_classes(books.session, books.company.company_id)
    assert classes.sales == {g["Sales Accounts"].group_id}
    assert classes.purchase == {g["Purchase Accounts"].group_id}
    assert classes.expense == {g["Direct Expenses"].group_id, g["Indirect Expenses"].group_id}
    assert classes.cash_bank == {g["Cash-in-Hand"].group_id, g["Bank Accounts"].group_id}
    assert classes.tax == {g["Duties & Taxes"].group_id}
    assert classes.customer == {g["Sundry Debtors"].group_id}
    assert classes.supplier == {g["Sundry Creditors"].group_id}
    assert g["Bank OD A/c"].group_id not in classes.cash_bank


async def test_a_company_group_entry_is_matched_by_guid(books: Books) -> None:
    online = await books.group("Online Revenue", None, nature=Nature.INCOME)
    await books.setting(
        "classification.sales_groups",
        [
            {"type": "PREDEFINED", "reserved_name": "Sales Accounts"},
            {"type": "COMPANY_GROUP", "tally_guid": online.tally_guid},
        ],
        SettingDataType.JSON,
    )
    classes = await load_classes(books.session, books.company.company_id)
    assert classes.sales == {books.groups["Sales Accounts"].group_id, online.group_id}


async def test_another_companys_groups_never_count(books: Books) -> None:
    from tests.analytics.books import make_books

    other = await make_books(books.session, name="Other Co")
    classes = await load_classes(books.session, books.company.company_id)
    assert other.groups["Sales Accounts"].group_id not in classes.sales
