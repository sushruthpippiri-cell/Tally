/** Analytics answers for the page tests: long names and wide amounts, so the 360 px checks have
 * something to overflow. Amounts are decimal strings, as the API sends them. */

const LONG_PARTY = "Sri Lakshmi Venkateswara Rice, Pulses and General Provision Wholesale Traders";
const BIG = "123456789012.34";

const applied = {
  date_from: "2025-04-01",
  date_to: "2026-03-16",
  granularity: "month",
  group_by: "ledger",
  include_cancelled: false,
  include_missing: false,
  by: [],
  not_applicable: [],
};

const figure = (amount: string | null, direction: string | null = null) => ({
  amount,
  direction,
  available: amount !== null,
  unavailable_count: 0,
  unavailable_ledgers: [],
});

const MONTHS = ["04", "05", "06", "07", "08", "09", "10", "11", "12", "01", "02", "03"];
export const SERIES = MONTHS.map((m, i) => {
  const year = i < 9 ? 2025 : 2026;
  return { period: `${year}-${m}`, start: `${year}-${m}-01`, amount: `${(i + 1) * 1234567}.89` };
});

export function metric(name: string, extra: Record<string, unknown> = {}) {
  return {
    metric: name,
    filters_applied: applied,
    company_timezone: "Asia/Kolkata",
    label: name === "product-difference" ? "Product Attribution Difference" : null,
    summary: figure(BIG),
    series: SERIES,
    breakdown: [
      { key: "l-1", label: LONG_PARTY, figure: figure(BIG) },
      { key: null, label: null, figure: figure("4500.00") },
    ],
    notes: ["Until the return-link gate (G26) passes, no credit or debit note is subtracted."],
    ...extra,
  };
}

const drillRow = (n: number) => ({
  voucher_id: "v-1",
  voucher_date: "2025-05-02",
  voucher_number: `SI/2025-26/${String(n).padStart(5, "0")}`,
  voucher_type_name: "Sales - Wholesale GST Invoice",
  base_voucher_type: "SALES",
  ledger_id: "l-1",
  ledger_name: LONG_PARTY,
  amount: BIG,
  dimensions: { party_id: "l-1", party_name: LONG_PARTY },
  custom_fields: { salesman: "Venkataramanan Subramaniam" },
});

const ranking = (kind: string) => ({
  ranking: kind,
  rank_by: "revenue",
  label: "Top 10",
  is_top_n: true,
  n: 10,
  total_count: 140,
  filters_applied: applied,
  company_timezone: "Asia/Kolkata",
  rows: [1, 2, 3].map((rank) => ({ rank, id: `l-${rank}`, name: LONG_PARTY, amount: BIG })),
  unattributed:
    kind === "products" ? null : { label: "Unattributed Customer Revenue", amount: BIG },
  product_attributed:
    kind === "products" ? { label: "Product-attributed Revenue", amount: BIG } : null,
  difference:
    kind === "products" ? { label: "Product Attribution Difference", amount: "4500.00" } : null,
  reference_total: { label: "Total Sales Revenue", amount: BIG },
  notes: ["The listed rows are not meant to add up to the total."],
});

const agingRow = (id: string | null, name: string | null) => ({
  ledger_id: id,
  ledger_name: name,
  buckets: {
    "0-30": BIG,
    "31-60": BIG,
    "61-90": BIG,
    "90+": BIG,
    NOT_YET_DUE: BIG,
    NO_DUE_DATE: "0",
  },
  bucket_total: BIG,
  credit: "0",
  unadjusted_advances: "10000.00",
  on_account: "0",
  unmatched_settlements: "0",
  net_exposure: BIG,
});

const at = "2026-03-16T06:30:00Z";
const metricNames = [
  "sales",
  "purchases",
  "cash-flow",
  "cash-bank-position",
  "receivables",
  "payables",
  "ledger-balances",
  "expenses",
  "unclassified-adjustments",
  "product-revenue",
  "product-difference",
  "customer-revenue",
  "supplier-purchases",
];

export const ANALYTICS: Record<string, unknown> = {
  ...Object.fromEntries(metricNames.map((m) => [`GET /companies/c-1/analytics/${m}`, metric(m)])),
  ...Object.fromEntries(
    metricNames.map((m) => [
      `GET /companies/c-1/analytics/${m}/drilldown`,
      {
        metric: m,
        filters_applied: applied,
        total: BIG,
        total_rows: 120,
        page: 1,
        page_size: 50,
        rows: [1, 2, 3].map(drillRow),
      },
    ]),
  ),
  "GET /companies/c-1/analytics/customers": ranking("customers"),
  "GET /companies/c-1/analytics/suppliers": ranking("suppliers"),
  "GET /companies/c-1/analytics/products": ranking("products"),
  "GET /companies/c-1/analytics/payment-behaviour": {
    available: false,
    reason: "Awaiting Tally validation (G25)",
    unverified_gates: ["G25"],
  },
  "GET /companies/c-1/analytics/aging": {
    side: "receivable",
    as_of: "2026-03-16",
    company_timezone: "Asia/Kolkata",
    bucket_order: [
      { key: "0-30", label: "Overdue 0-30 days" },
      { key: "31-60", label: "Overdue 31-60 days" },
      { key: "61-90", label: "Overdue 61-90 days" },
      { key: "90+", label: "Overdue 90+ days" },
      { key: "NOT_YET_DUE", label: "Not yet due" },
      { key: "NO_DUE_DATE", label: "Due date unavailable" },
    ],
    total: agingRow(null, null),
    parties: [agingRow("l-1", LONG_PARTY)],
    no_bill_details: [
      {
        ledger_id: "l-9",
        ledger_name: LONG_PARTY,
        balance: figure(BIG, "Dr"),
        note: "bill details not available",
      },
    ],
    unverified_gates: ["G25", "G31"],
  },
  "GET /companies/c-1/analytics/stock": {
    today: "2026-03-16",
    books_from: "2025-04-01",
    period_days: 90,
    period_from: "2025-12-17",
    period_to: "2026-03-16",
    basis: "value",
    fast_percentile: 75,
    fast_threshold: "1000.00",
    classes: [
      { key: "FAST", label: "Fast-moving", count: 3 },
      { key: "NEVER_SOLD", label: "No sale since 1 Apr 2025", count: 1 },
      { key: "NOT_CLASSIFIED", label: "Not classified", count: 1 },
    ],
    total_items: 1,
    items: [
      {
        stock_item_id: "s-1",
        name: "Premium Aged Basmati Rice Extra Long Grain 25 kg Jute Bag (Export Quality)",
        movement_class: "FAST",
        label: "Fast-moving",
        note: null,
        stock: "123456.000000",
        stock_unit: "Bag",
        snapshot_date: "2026-03-10",
        last_sale_date: "2026-03-15",
        days_since_last_sale: 1,
        period_sales_value: BIG,
        period_quantities: [
          { unit: "Bag", quantity: "1200.000000" },
          { unit: "Box", quantity: "35.000000" },
        ],
        multi_unit: true,
      },
    ],
    snapshot_dates: { oldest: "2026-03-10", newest: "2026-03-10" },
    warnings: ["The newest stock snapshot is from 10 Mar 2026, older than 2 days."],
    notes: [],
    limitations: ["Quantities are in each item's own unit and are never added across units."],
    unverified_gates: ["G18", "G27"],
  },
  "GET /companies/c-1/masters/options": [{ id: "l-1", name: LONG_PARTY }],
  "GET /companies/c-1/vouchers/v-1": {
    voucher_id: "v-1",
    tally_guid: "g-1",
    alter_id: 7,
    voucher_number: "SI/2025-26/00001",
    voucher_date: "2025-05-02",
    voucher_type_name: "Sales - Wholesale GST Invoice",
    base_voucher_type: "SALES",
    status: "ACTIVE",
    narration: "Diwali stock order delivered to the Secunderabad godown in two lots",
    last_synced_at: at,
    entries: [
      {
        line: 1,
        ledger_id: "l-1",
        ledger_name: LONG_PARTY,
        direction: "Dr",
        amount: BIG,
        bills: [
          {
            allocation_type: "NEW_REF",
            reference_name: "SI/2025-26/00001",
            due_date: "2025-06-01",
            amount: BIG,
            direction: "Dr",
          },
        ],
        cost_centres: [{ cost_centre_id: "cc-1", cost_centre_name: "Head Office", amount: BIG }],
      },
    ],
    items: [
      {
        stock_item_id: "s-1",
        stock_item_name: "Premium Aged Basmati Rice Extra Long Grain 25 kg Jute Bag",
        quantity: "1200.000000",
        unit: "Bag",
        rate: "1850.00",
        amount: BIG,
        custom_fields: null,
      },
    ],
    custom_fields: [{ field_key: "salesman", tally_field: "TA_Salesman", value: "Ravi" }],
  },
  "GET /companies/c-1/audit": [
    {
      id: 1,
      created_at: at,
      user_id: null,
      action: "VOUCHER_MODIFIED",
      entity_type: "voucher",
      entity_id: "v-1",
      before: { status: "ACTIVE" },
      after: { alter_id: 7, narration: "Diwali stock order delivered to the Secunderabad godown" },
      data_range: null,
      result: "SUCCESS",
    },
  ],
};
