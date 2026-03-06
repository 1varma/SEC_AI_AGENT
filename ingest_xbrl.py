import time
import requests
import psycopg2
from psycopg2.extras import execute_values
from datetime import date
from tqdm import tqdm

# ─── Configuration ────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}

EDGAR_HEADERS = {
    "User-Agent": "FinSightAI/1.0 (financial-research; contact@finsight.ai)",
    "Accept-Encoding": "gzip, deflate",
}

REQUEST_DELAY   = 0.15     # ~6–7 req/sec (EDGAR cap: 10/sec)
ANNUAL_FORMS    = {"10-K"}
QUARTERLY_FORMS = {"10-Q"}
ANNUAL_FPS      = {"FY"}
QUARTERLY_FPS   = {"Q1", "Q2", "Q3", "Q4"}

# ─── XBRL tag priority lists ───────────────────────────────────────────────────
# Companies use different tags across time/standard; first tag with data wins.
METRIC_TAGS = {
    "revenue": (
        [
            "RevenueFromContractWithCustomerExcludingAssessedTax",  # ASC 606 (post-2018)
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueGoodsNet",
        ],
        "USD",
    ),
    "gross_profit":        (["GrossProfit"],                                                        "USD"),
    "operating_income":    (["OperatingIncomeLoss"],                                                "USD"),
    "net_income":          (["NetIncomeLoss"],                                                      "USD"),
    "eps_basic":           (["EarningsPerShareBasic"],                                              "USD/shares"),
    "eps_diluted":         (["EarningsPerShareDiluted"],                                            "USD/shares"),
    "rd_expense":          (["ResearchAndDevelopmentExpense"],                                      "USD"),
    "total_assets":        (["Assets"],                                                             "USD"),
    "total_liabilities":   (["Liabilities"],                                                        "USD"),
    "stockholders_equity": (
        [
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ],
        "USD",
    ),
    "cash": (
        [
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsAndShortTermInvestments",
        ],
        "USD",
    ),
    "long_term_debt":      (["LongTermDebtNoncurrent", "LongTermDebt"],                            "USD"),
    "operating_cash_flow": (["NetCashProvidedByUsedInOperatingActivities"],                        "USD"),
    "capex":               (["PaymentsToAcquirePropertyPlantAndEquipment"],                        "USD"),
}


# ─── Helpers ──────────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def fetch_cik_map():
    """Download SEC company_tickers.json → {TICKER: zero-padded-cik-str}."""
    print("Fetching CIK map from SEC EDGAR...")
    resp = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=EDGAR_HEADERS, timeout=30
    )
    resp.raise_for_status()
    return {
        entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
        for entry in resp.json().values()
    }


def fetch_company_facts(cik: str):
    """Download EDGAR company facts JSON for a CIK. Returns None on 404."""
    url  = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    resp = requests.get(url, headers=EDGAR_HEADERS, timeout=60)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def extract_metric(facts_gaap, tags, unit, target_forms, target_fps):
    """
    Try each tag in order; return the first one with data as:
      {(form, end_date_str, fy, fp): value}
    For duration facts (with 'start'), filters by expected period length
    to skip cumulative YTD figures (e.g. 9-month Q3 instead of 3-month Q3).
    For overlapping filings/amendments, keeps the most recently filed entry.
    """
    for tag in tags:
        if tag not in facts_gaap:
            continue
        entries = facts_gaap[tag].get("units", {}).get(unit, [])
        if not entries:
            continue

        period_data = {}  # (form, end, fy, fp) -> (value, filed_date_str)
        for e in entries:
            form  = e.get("form",  "")
            fp    = e.get("fp",    "")
            end   = e.get("end",   "")
            fy    = e.get("fy")
            filed = e.get("filed", "")

            if form not in target_forms or fp not in target_fps:
                continue

            # Duration concept: filter out cumulative/off-period values
            if "start" in e:
                try:
                    days = (
                        date.fromisoformat(end) - date.fromisoformat(e["start"])
                    ).days
                    if fp == "FY" and not (270 <= days <= 400):
                        continue
                    if fp in QUARTERLY_FPS and not (60 <= days <= 120):
                        continue
                except ValueError:
                    pass

            key = (form, end, fy, fp)
            existing = period_data.get(key)
            if existing is None or filed > existing[1]:
                period_data[key] = (e["val"], filed)

        if period_data:
            return {k: v[0] for k, v in period_data.items()}

    return {}


def build_rows(ticker: str, cik: str, facts_json: dict):
    """Parse company facts JSON → list of row dicts for the financials table."""
    gaap = facts_json.get("facts", {}).get("us-gaap", {})
    if not gaap:
        return []

    periods = {}  # (form, end, fy, fp) -> {metric: value}

    for metric, (tags, unit) in METRIC_TAGS.items():
        for form_set, fp_set in [
            (ANNUAL_FORMS, ANNUAL_FPS),
            (QUARTERLY_FORMS, QUARTERLY_FPS),
        ]:
            vals = extract_metric(gaap, tags, unit, form_set, fp_set)
            for key, val in vals.items():
                if key not in periods:
                    periods[key] = {}
                periods[key][metric] = val

    rows = []
    for (form, end, fy, fp), m in periods.items():
        if not any(v is not None for v in m.values()):
            continue

        period_type = "annual" if fp == "FY" else "quarterly"
        fq          = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}.get(fp)

        rev   = m.get("revenue")
        gp    = m.get("gross_profit")
        oi    = m.get("operating_income")
        ni    = m.get("net_income")
        ocf   = m.get("operating_cash_flow")
        capex = m.get("capex")

        gross_margin     = round(gp / rev, 4) if gp and rev else None
        operating_margin = round(oi / rev, 4) if oi and rev else None
        net_margin       = round(ni / rev, 4) if ni and rev else None
        fcf              = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None

        rows.append({
            "ticker":              ticker,
            "cik":                 cik,
            "period_end":          end,
            "period_type":         period_type,
            "fiscal_year":         fy,
            "fiscal_quarter":      fq,
            "revenue":             rev,
            "gross_profit":        gp,
            "operating_income":    oi,
            "net_income":          ni,
            "eps_basic":           m.get("eps_basic"),
            "eps_diluted":         m.get("eps_diluted"),
            "rd_expense":          m.get("rd_expense"),
            "total_assets":        m.get("total_assets"),
            "total_liabilities":   m.get("total_liabilities"),
            "stockholders_equity": m.get("stockholders_equity"),
            "cash":                m.get("cash"),
            "long_term_debt":      m.get("long_term_debt"),
            "operating_cash_flow": ocf,
            "capex":               capex,
            "free_cash_flow":      fcf,
            "gross_margin":        gross_margin,
            "operating_margin":    operating_margin,
            "net_margin":          net_margin,
            "form_type":           form,
        })

    return rows


def insert_rows(conn, rows):
    if not rows:
        return 0
    cur = conn.cursor()
    execute_values(cur, """
        INSERT INTO financials (
            ticker, cik, period_end, period_type, fiscal_year, fiscal_quarter,
            revenue, gross_profit, operating_income, net_income,
            eps_basic, eps_diluted, rd_expense,
            total_assets, total_liabilities, stockholders_equity,
            cash, long_term_debt,
            operating_cash_flow, capex, free_cash_flow,
            gross_margin, operating_margin, net_margin,
            form_type
        ) VALUES %s
        ON CONFLICT (ticker, period_end, period_type) DO NOTHING;
    """, [
        (
            r["ticker"], r["cik"], r["period_end"], r["period_type"],
            r["fiscal_year"], r["fiscal_quarter"],
            r["revenue"], r["gross_profit"], r["operating_income"], r["net_income"],
            r["eps_basic"], r["eps_diluted"], r["rd_expense"],
            r["total_assets"], r["total_liabilities"], r["stockholders_equity"],
            r["cash"], r["long_term_debt"],
            r["operating_cash_flow"], r["capex"], r["free_cash_flow"],
            r["gross_margin"], r["operating_margin"], r["net_margin"],
            r["form_type"],
        )
        for r in rows
    ])
    count = cur.rowcount
    conn.commit()
    cur.close()
    return count


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Phase 7 — Ingest EDGAR XBRL Financial Data")
    print("=" * 60)

    # Load our 473 tickers from the stock_prices table
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT DISTINCT ticker FROM stock_prices ORDER BY ticker;")
    tickers = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    print(f"\nTickers to process: {len(tickers)}")

    # CIK map
    cik_map   = fetch_cik_map()
    time.sleep(REQUEST_DELAY)

    matched   = [(t, cik_map[t]) for t in tickers if t in cik_map]
    unmatched = [t for t in tickers if t not in cik_map]
    print(f"CIK matched : {len(matched)} / {len(tickers)}")
    if unmatched:
        print(f"No CIK found: {unmatched}")

    total_inserted = 0
    errors         = []
    conn           = get_conn()

    for ticker, cik in tqdm(matched, desc="Ingesting XBRL", unit="ticker"):
        try:
            facts = fetch_company_facts(cik)
            time.sleep(REQUEST_DELAY)
            if not facts:
                continue

            rows     = build_rows(ticker, cik, facts)
            inserted = insert_rows(conn, rows)
            total_inserted += inserted

        except Exception as e:
            errors.append((ticker, str(e)))
            continue

    conn.close()

    print(f"\nTotal rows inserted : {total_inserted:,}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for ticker, err in errors:
            print(f"  {ticker}: {err}")

    print('=' * 60)
    print("Next step: restart FastAPI — get_financials tool is now live")
    print('=' * 60)


if __name__ == "__main__":
    main()
