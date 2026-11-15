"""
International Cost of Capital App
---------------------------------
Compares a project's cost of equity, cost of debt and WACC in USD and in the
currency of a selected country.

Data sources (fetched live, cached, refreshable):
  * Industry unlevered betas ........ Aswath Damodaran (betas.xls)
  * Baa2/BBB USD borrowing spread ... Aswath Damodaran (ratings.html, large non-financial firms)
  * Corporate tax rates ............. OECD (combined statutory CIT rate)
  * 10-year government bond yields .. Trading Economics (/bonds)

Run locally:  streamlit run app.py
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
BETAS_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
RATINGS_URLS = [
    "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html",
    "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html",
]
OECD_REPORT_URL = (
    "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/"
    "full-report/statutory-corporate-income-tax-rates_440f9286.html"
)
OECD_API_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,/all"
    "?startPeriod=2022&dimensionAtObservation=AllDimensions&format=csvfilewithlabels"
)
TE_BONDS_URL = "https://tradingeconomics.com/bonds"
TE_COUNTRY_URL = "https://tradingeconomics.com/{slug}/government-bond-yield"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 25

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "United States"
DEFAULT_ERP = 6.5          # %
DEFAULT_DEBT_SHARE = 30.0  # %

# --- Offline fallbacks (used ONLY if a live fetch fails; always flagged in the UI) ---
FALLBACK_BBB_SPREAD = 1.11  # %, Damodaran ratings table, January 2026 update
FALLBACK_BBB_DATE = "January 2026 (embedded snapshot)"
FALLBACK_US_YIELD = 4.25    # %, PLACEHOLDER - not a market quote
FALLBACK_BETA = 1.00        # PLACEHOLDER - not Damodaran's estimate

# Combined (central + sub-central) statutory corporate income tax rates, %.
# Approximate embedded snapshot of OECD figures (2025). Used only if OECD fetch fails.
FALLBACK_TAX = {
    "Australia": 30.0, "Austria": 23.0, "Belgium": 25.0, "Brazil": 34.0,
    "Bulgaria": 10.0, "Canada": 26.1, "Chile": 27.0, "China": 25.0,
    "Colombia": 35.0, "Croatia": 18.0, "Czech Republic": 21.0, "Denmark": 22.0,
    "Egypt": 22.5, "Finland": 20.0, "France": 36.13, "Germany": 29.93,
    "Greece": 22.0, "Hong Kong": 16.5, "Hungary": 9.0, "Iceland": 20.0,
    "India": 30.0, "Indonesia": 22.0, "Ireland": 12.5, "Israel": 23.0,
    "Italy": 27.81, "Japan": 29.74, "Kazakhstan": 20.0, "Kenya": 30.0,
    "Latvia": 20.0, "Lithuania": 16.0, "Luxembourg": 23.87, "Malaysia": 24.0,
    "Mexico": 30.0, "Netherlands": 25.8, "New Zealand": 28.0, "Nigeria": 30.0,
    "Norway": 22.0, "Pakistan": 29.0, "Peru": 29.5, "Philippines": 25.0,
    "Poland": 19.0, "Portugal": 30.5, "Romania": 16.0, "Russia": 25.0,
    "Saudi Arabia": 20.0, "Serbia": 15.0, "Singapore": 17.0, "Slovakia": 21.0,
    "Slovenia": 22.0, "South Africa": 27.0, "South Korea": 26.4, "Spain": 25.0,
    "Sweden": 20.6, "Switzerland": 19.6, "Thailand": 20.0, "Turkey": 25.0,
    "United Kingdom": 25.0, "United States": 25.6, "Vietnam": 20.0,
}

# OECD naming -> the naming used by Trading Economics (canonical names in this app)
COUNTRY_ALIASES = {
    "korea": "South Korea", "korea, republic of": "South Korea",
    "republic of korea": "South Korea",
    "türkiye": "Turkey", "turkiye": "Turkey",
    "china (people's republic of)": "China", "china (people’s republic of)": "China",
    "people's republic of china": "China",
    "slovak republic": "Slovakia", "czechia": "Czech Republic",
    "hong kong, china": "Hong Kong", "hong kong (china)": "Hong Kong",
    "viet nam": "Vietnam", "russian federation": "Russia",
    "united states of america": "United States", "usa": "United States",
    "united kingdom of great britain and northern ireland": "United Kingdom",
}

CURRENCY = {
    "United States": "USD", "United Kingdom": "GBP", "Japan": "JPY", "Germany": "EUR",
    "France": "EUR", "Italy": "EUR", "Spain": "EUR", "Netherlands": "EUR",
    "Belgium": "EUR", "Austria": "EUR", "Portugal": "EUR", "Greece": "EUR",
    "Ireland": "EUR", "Finland": "EUR", "Slovakia": "EUR", "Slovenia": "EUR",
    "Lithuania": "EUR", "Latvia": "EUR", "Croatia": "EUR", "Luxembourg": "EUR",
    "Canada": "CAD", "Australia": "AUD", "New Zealand": "NZD", "Switzerland": "CHF",
    "Sweden": "SEK", "Norway": "NOK", "Denmark": "DKK", "Poland": "PLN",
    "Czech Republic": "CZK", "Hungary": "HUF", "Romania": "RON", "Bulgaria": "BGN",
    "Turkey": "TRY", "Russia": "RUB", "China": "CNY", "India": "INR",
    "South Korea": "KRW", "Indonesia": "IDR", "Malaysia": "MYR", "Thailand": "THB",
    "Philippines": "PHP", "Vietnam": "VND", "Singapore": "SGD", "Hong Kong": "HKD",
    "Taiwan": "TWD", "Pakistan": "PKR", "Brazil": "BRL", "Mexico": "MXN",
    "Chile": "CLP", "Colombia": "COP", "Peru": "PEN", "South Africa": "ZAR",
    "Egypt": "EGP", "Nigeria": "NGN", "Kenya": "KES", "Israel": "ILS",
    "Saudi Arabia": "SAR", "Iceland": "ISK", "Kazakhstan": "KZT", "Serbia": "RSD",
}


# --------------------------------------------------------------------------- #
# Finance: the ONLY place the formulas live (all inputs/outputs are decimals)
# --------------------------------------------------------------------------- #
def compute(beta_u, tax, debt_share, erp, y_us, y_fc, spread_usd, spread_fc_override=None):
    """Cost of equity, cost of debt and WACC in USD and in the foreign currency.

    beta_u may be a scalar or a pandas Series / numpy array (all-industry table).
    """
    d_e = debt_share / (1.0 - debt_share)                 # D/E from D/V
    beta_l = beta_u * (1.0 + (1.0 - tax) * d_e)           # relever (Hamada)

    # --- USD ---
    re_usd = y_us + beta_l * erp                          # CAPM
    rd_usd = y_us + spread_usd                            # BBB borrower
    wacc_usd = (1 - debt_share) * re_usd + debt_share * rd_usd * (1 - tax)

    # --- Foreign currency ---
    # Auto spread: translate the USD borrowing cost at the government-yield
    # differential:  (1+rd_fc) = (1+rd_usd)(1+y_fc)/(1+y_us)
    #            =>  spread_fc = spread_usd * (1+y_fc)/(1+y_us)
    spread_fc_auto = spread_usd * (1.0 + y_fc) / (1.0 + y_us)
    spread_fc = spread_fc_auto if spread_fc_override is None else spread_fc_override
    re_fc = y_fc + beta_l * erp                           # same beta, same ERP
    rd_fc = y_fc + spread_fc
    wacc_fc = (1 - debt_share) * re_fc + debt_share * rd_fc * (1 - tax)

    return {
        "d_e": d_e, "beta_l": beta_l,
        "re_usd": re_usd, "rd_usd": rd_usd, "rd_usd_at": rd_usd * (1 - tax), "wacc_usd": wacc_usd,
        "spread_fc_auto": spread_fc_auto, "spread_fc": spread_fc,
        "re_fc": re_fc, "rd_fc": rd_fc, "rd_fc_at": rd_fc * (1 - tax), "wacc_fc": wacc_fc,
    }


# --------------------------------------------------------------------------- #
# Parsing helpers (pure functions - no network, easy to test)
# --------------------------------------------------------------------------- #
def canon(name: str) -> str:
    """Map a country name from any source onto one canonical spelling."""
    n = re.sub(r"\s+", " ", str(name)).strip()
    return COUNTRY_ALIASES.get(n.lower(), n)


def _fmt_date(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float)) and 20000 < v < 80000:      # Excel serial date
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).strftime("%Y-%m-%d")
    return str(v).strip() or None


def parse_betas_sheet(raw: pd.DataFrame):
    """raw = sheet read with header=None. Returns (DataFrame[Industry, Unlevered beta], date)."""
    norm = lambda x: re.sub(r"\s+", " ", str(x)).strip().lower()
    header_idx = None
    for i in range(min(len(raw), 40)):
        if any(norm(c) == "industry name" for c in raw.iloc[i].tolist()):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("'Industry Name' header not found")
    cols = [norm(c) for c in raw.iloc[header_idx].tolist()]
    i_name = cols.index("industry name")
    if "unlevered beta" not in cols:
        raise ValueError("'Unlevered beta' column not found")
    i_beta = cols.index("unlevered beta")          # NOT the cash-corrected column
    body = raw.iloc[header_idx + 1:, [i_name, i_beta]].copy()
    body.columns = ["Industry", "Unlevered beta"]
    body["Industry"] = body["Industry"].astype(str).str.strip()
    body["Unlevered beta"] = pd.to_numeric(body["Unlevered beta"], errors="coerce")
    body = body.dropna(subset=["Unlevered beta"])
    body = body[~body["Industry"].str.lower().isin(["nan", ""])].reset_index(drop=True)

    date = None
    for i in range(header_idx):
        row = raw.iloc[i].tolist()
        for j, c in enumerate(row):
            if "date updated" in norm(c):
                for nxt in row[j + 1:]:
                    date = _fmt_date(nxt)
                    if date and date.lower() != "nan":
                        break
                    date = None
        if date:
            break
    return body, date


def parse_bbb_spread(html: str):
    """First Baa2/BBB row of the page = table for large non-financial service firms."""
    soup = BeautifulSoup(html, "html.parser")
    spread = None
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        for i, c in enumerate(cells):
            if re.sub(r"\s", "", c) == "Baa2/BBB":
                for nxt in cells[i + 1:]:
                    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", nxt.strip())
                    if m:
                        spread = float(m.group(1))
                        break
                break
        if spread is not None:
            break
    if spread is None:
        raise ValueError("Baa2/BBB row not found")
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Date of Analysis:\s*(.{0,60}?(?:19|20)\d{2})", text)
    date = m.group(1).strip() if m else None
    return spread, date


def slug_to_country(slug: str) -> str:
    return canon(slug.replace("-", " ").title())


def country_to_slug(country: str) -> str:
    return country.lower().replace(" ", "-")


def parse_te_bonds(html: str) -> pd.DataFrame:
    """Parse the 10Y table(s) on tradingeconomics.com/bonds -> Country, Yield (%), Date."""
    soup = BeautifulSoup(html, "html.parser")
    rows = {}
    link_re = re.compile(r"/([a-z-]+)/government-bond-yield", re.I)
    links = soup.find_all("a", href=link_re)
    for a in links:
        tr = a.find_parent("tr")
        if tr is None:
            continue
        slug = link_re.search(a["href"]).group(1).lower()
        if slug in ("country-list", "bonds", "forecast"):
            continue
        country = slug_to_country(slug)
        tds = tr.find_all("td")
        val = None
        p = tr.find("td", id="p")
        candidates = ([p] if p else []) + tds
        for td in candidates:
            txt = td.get_text(strip=True).replace(",", "")
            if re.fullmatch(r"-?\d+(?:\.\d+)?", txt):
                val = float(txt)
                break
        if val is None:
            continue
        d = tr.find("td", id="date")
        date = d.get_text(strip=True) if d else ""
        rows.setdefault(country, {"Country": country, "Yield": val, "Date": date})
    if not rows:
        title = soup.title.get_text(strip=True)[:60] if soup.title else "none"
        raise ValueError(
            f"no bond rows found [diagnostic: {len(html)} chars, title '{title}', "
            f"{len(links)} bond links, {len(soup.find_all('tr'))} table rows, "
            f"{len(soup.find_all('script'))} scripts]")
    return pd.DataFrame(rows.values()).sort_values("Country").reset_index(drop=True)


def parse_te_country_page(html: str):
    """Fallback: read yield + date from a country page's meta description."""
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"})
    text = (meta.get("content", "") if meta else "") or soup.get_text(" ", strip=True)[:3000]
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:%|percent)", text)
    if not m:
        raise ValueError("yield not found on country page")
    d = re.search(r"on\s+([A-Z][a-z]+ \d{1,2},? \d{4})", text)
    return float(m.group(1)), (d.group(1) if d else "")


def parse_oecd_csv(csv_text: str):
    """OECD SDMX csv (with labels) -> ({country: rate %}, 'year(s)')."""
    df = pd.read_csv(io.StringIO(csv_text))
    measure_col = next((c for c in df.columns if c.strip().lower() == "measure" and c != "MEASURE"), None)
    area_col = next((c for c in df.columns if c.strip().lower() == "reference area"), None)
    if not (measure_col and area_col and "OBS_VALUE" in df and "TIME_PERIOD" in df):
        raise ValueError("unexpected OECD CSV layout")
    lab = df[measure_col].astype(str).str.lower()
    mask = lab.str.contains("combined") & ~lab.str.contains("small|targeted")
    sub = df[mask].copy()
    if sub.empty:
        raise ValueError("combined CIT rate measure not found")
    sub["OBS_VALUE"] = pd.to_numeric(sub["OBS_VALUE"], errors="coerce")
    sub = sub.dropna(subset=["OBS_VALUE"]).sort_values("TIME_PERIOD")
    latest = sub.groupby(area_col).tail(1)
    rates = {canon(r[area_col]): float(r["OBS_VALUE"]) for _, r in latest.iterrows()}
    us = rates.get("United States")
    if us is None or not 15 <= us <= 45:
        raise ValueError("OECD data failed sanity check")
    return rates, str(latest["TIME_PERIOD"].max())


def parse_oecd_report_html(html: str):
    """Try to find a jurisdiction/rate table in the OECD report page."""
    for t in pd.read_html(io.StringIO(html)):
        t.columns = [str(c) for c in t.columns]
        first = t.iloc[:, 0].astype(str)
        if first.str.contains("United States").any():
            for c in t.columns[1:][::-1]:
                vals = pd.to_numeric(t[c].astype(str).str.replace("%", ""), errors="coerce")
                if vals.notna().sum() > 20:
                    rates = {canon(k): float(v) for k, v in zip(first, vals) if pd.notna(v)}
                    return rates, "2024"
    raise ValueError("no rate table in OECD report page")


# --------------------------------------------------------------------------- #
# Fetchers (cached; "Refresh data" clears the cache)
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r


@st.cache_data(ttl=3600, show_spinner="Fetching Damodaran industry betas…")
def fetch_betas():
    try:
        r = _get(BETAS_URL)
        sheets = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
        err = None
        for name in sorted(sheets, key=lambda s: 0 if "industry" in s.lower() else 1):
            try:
                df, date = parse_betas_sheet(sheets[name])
                date = date or r.headers.get("Last-Modified", "n/a")
                return {"data": df, "date": date, "fetched": _now(), "live": True, "error": None}
            except Exception as e:  # try next sheet
                err = e
        raise err or ValueError("no usable sheet")
    except Exception as e:
        df = pd.DataFrame({"Industry": [DEFAULT_INDUSTRY], "Unlevered beta": [FALLBACK_BETA]})
        return {"data": df, "date": "PLACEHOLDER (fetch failed)", "fetched": _now(),
                "live": False, "error": str(e)}


@st.cache_data(ttl=3600, show_spinner="Fetching Damodaran BBB spread…")
def fetch_bbb():
    err = None
    for url in RATINGS_URLS:
        try:
            r = _get(url)
            spread, date = parse_bbb_spread(r.text)
            return {"data": spread, "date": date or r.headers.get("Last-Modified", "n/a"),
                    "fetched": _now(), "live": True, "error": None, "url": url}
        except Exception as e:
            err = e
    return {"data": FALLBACK_BBB_SPREAD, "date": FALLBACK_BBB_DATE, "fetched": _now(),
            "live": False, "error": str(err), "url": RATINGS_URLS[0]}


@st.cache_data(ttl=3600, show_spinner="Fetching OECD corporate tax rates…")
def fetch_tax():
    errors = []
    try:  # 1) OECD Data Explorer API - latest year available
        rates, year = parse_oecd_csv(_get(OECD_API_URL).text)
        return {"data": rates, "date": f"latest year per country (up to {year})",
                "fetched": _now(), "live": True, "error": None,
                "source": "OECD Data Explorer – Corporate income tax statutory rates (combined)",
                "url": OECD_API_URL}
    except Exception as e:
        errors.append(f"API: {e}")
    try:  # 2) the OECD Corporate Tax Statistics report page
        rates, year = parse_oecd_report_html(_get(OECD_REPORT_URL).text)
        return {"data": rates, "date": year, "fetched": _now(), "live": True, "error": None,
                "source": "OECD Corporate Tax Statistics 2024 (report page)", "url": OECD_REPORT_URL}
    except Exception as e:
        errors.append(f"report page: {e}")
    return {"data": dict(FALLBACK_TAX), "date": "2025 (embedded approximate snapshot)",
            "fetched": _now(), "live": False, "error": "; ".join(errors),
            "source": "OECD combined statutory CIT rates – embedded snapshot", "url": OECD_REPORT_URL}


@st.cache_data(ttl=3600, show_spinner="Fetching Trading Economics 10Y yields…")
def fetch_yields():
    try:
        df = parse_te_bonds(_get(TE_BONDS_URL).text)
        if DEFAULT_COUNTRY not in set(df["Country"]):
            raise ValueError("United States missing from table")
        return {"data": df, "fetched": _now(), "live": True, "error": None}
    except Exception as e:
        return {"data": pd.DataFrame(columns=["Country", "Yield", "Date"]),
                "fetched": _now(), "live": False, "error": str(e)}


@st.cache_data(ttl=3600, show_spinner="Fetching country yield…")
def fetch_country_yield(country: str):
    """Fallback when the /bonds table is unavailable: scrape the country's own page."""
    url = TE_COUNTRY_URL.format(slug=country_to_slug(country))
    try:
        y, date = parse_te_country_page(_get(url).text)
        return {"data": y, "date": date, "fetched": _now(), "live": True, "error": None, "url": url}
    except Exception as e:
        return {"data": None, "date": "", "fetched": _now(), "live": False, "error": str(e), "url": url}


# --------------------------------------------------------------------------- #
# UI helpers
# --------------------------------------------------------------------------- #
def pct(x: float, d: int = 2) -> str:
    return f"{x * 100:.{d}f}%"


def overridable(label, fetched, key, step=0.01, fmt="%.2f", placeholder=0.0, help=None):
    """Toggle + number input. Returns (value, is_manual). `fetched` None => manual required."""
    if fetched is None:
        st.caption(f"⚠️ {label}: no fetched value – enter manually.")
        v = st.number_input(label, value=float(placeholder), step=step, format=fmt,
                            key=f"{key}_forced", help=help)
        return v, True
    on = st.toggle(f"Override {label}", key=f"{key}_on", help=help)
    if on:
        # start from the value exactly as displayed, so what you see is what is used
        v = st.number_input(label, value=round(float(fetched), int(fmt[2])), step=step,
                            format=fmt, key=f"{key}_val")
        return v, True
    st.caption(f"{label}: **{fetched:{fmt[1:]}}** (fetched)")
    return float(fetched), False


def lookup_yield(country: str, ydata: dict):
    """Returns (yield % or None, date string, source url, live flag)."""
    df = ydata["data"]
    hit = df[df["Country"] == country]
    if not hit.empty:
        return float(hit.iloc[0]["Yield"]), f"{hit.iloc[0]['Date']} (fetched {ydata['fetched']})", TE_BONDS_URL, True
    one = fetch_country_yield(country)
    if one["data"] is not None:
        return one["data"], f"{one['date']} (fetched {one['fetched']})", one["url"], True
    return None, "not available", one["url"], False


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
def main():
    st.set_page_config(page_title="International Cost of Capital", page_icon="🌍", layout="wide")
    st.title("🌍 International Cost of Capital")
    st.caption("Cost of equity, cost of debt and WACC for the same project, in USD and in the "
               "currency of a selected country.")

    # ---------------- data ----------------
    with st.sidebar:
        st.header("Data")
        if st.button("🔄 Refresh data", use_container_width=True,
                     help="Clear the cache and fetch all four sources again"):
            st.cache_data.clear()
            st.rerun()

    betas, bbb, tax, yields = fetch_betas(), fetch_bbb(), fetch_tax(), fetch_yields()
    beta_df = betas["data"]
    if not yields["live"]:
        us_try = fetch_country_yield(DEFAULT_COUNTRY)
        if us_try["data"] is not None:
            st.info("Trading Economics: the all-country table could not be read, so yields are "
                    "taken live from each country's own Trading Economics page instead. "
                    f"({yields['error']})")
        else:
            st.warning("**Trading Economics yields: live fetch failed** – enter the two 10Y yields "
                       f"under Manual overrides. Table: {yields['error']} | "
                       f"Country page: {us_try['error']}")
    for name, src in [("Damodaran betas", betas), ("Damodaran BBB spread", bbb),
                      ("OECD tax rates", tax)]:
        if not src["live"]:
            st.warning(f"**{name}: live fetch failed** – using fallback/placeholder values or "
                       f"per-country lookup. Use manual overrides if needed. ({src['error']})")

    # Countries with a 10Y yield on Trading Economics; if the table could not be read,
    # offer a built-in list and look each country up on its own page.
    base = set(yields["data"]["Country"]) if yields["live"] else set(FALLBACK_TAX)
    countries = sorted(base | {DEFAULT_COUNTRY})
    industries = beta_df["Industry"].tolist()

    # ---------------- sidebar inputs ----------------
    with st.sidebar:
        st.header("Project")
        industry = st.selectbox(
            "Industry", industries,
            index=industries.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in industries else 0)
        country = st.selectbox("Target country", countries, index=countries.index(DEFAULT_COUNTRY))
        erp = st.number_input("Equity risk premium (%)", 0.0, 30.0, DEFAULT_ERP, 0.1, format="%.2f")
        debt_share = st.slider("Target debt share D/(D+E) (%)", 0.0, 95.0, DEFAULT_DEBT_SHARE, 1.0)
        tax_choice = st.radio("Project tax rate", ["U.S.", "Selected country"], horizontal=True,
                              help="The same tax rate is used for relevering beta and for the "
                                   "debt tax shield in both currencies.")

        fetched_beta = float(beta_df.loc[beta_df["Industry"] == industry, "Unlevered beta"].iloc[0])
        y_us_f, y_us_date, y_us_url, _ = lookup_yield(DEFAULT_COUNTRY, yields)
        if country == DEFAULT_COUNTRY:
            y_fc_f, y_fc_date, y_fc_url = y_us_f, y_us_date, y_us_url
        else:
            y_fc_f, y_fc_date, y_fc_url, _ = lookup_yield(country, yields)
        tax_us_f = tax["data"].get(DEFAULT_COUNTRY)
        tax_fc_f = tax["data"].get(country)

        st.header("Manual overrides")
        with st.expander("Overwrite fetched data", expanded=False):
            beta_u, m_beta = overridable("Unlevered beta", fetched_beta, "beta", fmt="%.4f", placeholder=1.0)
            tax_us, m_tus = overridable("U.S. corporate tax rate (%)", tax_us_f, "tus", 0.1, placeholder=25.0)
            if country == DEFAULT_COUNTRY and not m_tus:
                tax_fc, m_tfc = tax_us, False
                st.caption("Selected country = U.S. → same tax rate.")
            elif country == DEFAULT_COUNTRY:
                tax_fc, m_tfc = tax_us, True
            else:
                tax_fc, m_tfc = overridable(f"{country} corporate tax rate (%)", tax_fc_f, "tfc", 0.1,
                                            placeholder=25.0)
            s_usd, m_s = overridable("USD BBB spread (%)", bbb["data"], "susd")
            y_us, m_yus = overridable("U.S. 10Y government yield (%)", y_us_f, "yus",
                                      placeholder=FALLBACK_US_YIELD)
            if country == DEFAULT_COUNTRY:
                y_fc, m_yfc = y_us, m_yus
                st.caption("Selected country = U.S. → same yield.")
            else:
                y_fc, m_yfc = overridable(f"{country} 10Y government yield (%)", y_fc_f, "yfc",
                                          placeholder=y_us)
            s_fc_auto_pct = s_usd * (1 + y_fc / 100) / (1 + y_us / 100)
            s_fc_on = st.toggle("Override foreign-currency BBB spread", key="sfc_on")
            if s_fc_on:
                s_fc_manual = st.number_input("Foreign-currency BBB spread (%)", value=float(round(s_fc_auto_pct, 2)),
                                              step=0.01, format="%.2f", key="sfc_val")
            else:
                s_fc_manual = None
                st.caption(f"Foreign-currency BBB spread: **{s_fc_auto_pct:.2f}** (auto-calculated)")

    # ---------------- calculation ----------------
    tax_used = tax_us if tax_choice == "U.S." else tax_fc
    args = dict(tax=tax_used / 100, debt_share=debt_share / 100, erp=erp / 100,
                y_us=y_us / 100, y_fc=y_fc / 100, spread_usd=s_usd / 100,
                spread_fc_override=None if s_fc_manual is None else s_fc_manual / 100)
    res = compute(beta_u, **args)
    ccy = CURRENCY.get(country, "local currency")
    fc_label = f"{country} ({ccy})"

    # ---------------- results ----------------
    st.subheader(f"{industry} · {country} · tax rate: {tax_choice} ({tax_used:.2f}%)")
    c1, c2 = st.columns(2)
    for col, title, k in [(c1, "🇺🇸 USD", "usd"), (c2, f"🌐 {fc_label}", "fc")]:
        with col:
            st.markdown(f"### {title}")
            a, b, c = st.columns(3)
            a.metric("Cost of equity", pct(res[f"re_{k}"]))
            b.metric("Pre-tax cost of debt", pct(res[f"rd_{k}"]))
            c.metric("WACC", pct(res[f"wacc_{k}"]))

    summary = pd.DataFrame(
        {
            "USD": [y_us / 100, s_usd / 100, res["re_usd"], res["rd_usd"], res["rd_usd_at"], res["wacc_usd"]],
            fc_label: [y_fc / 100, res["spread_fc"], res["re_fc"], res["rd_fc"], res["rd_fc_at"], res["wacc_fc"]],
        },
        index=["10Y government yield", "BBB spread", "Cost of equity", "Pre-tax cost of debt",
               "After-tax cost of debt", "WACC"],
    )
    summary["Difference"] = summary[fc_label] - summary["USD"]
    st.dataframe(summary.style.format("{:.2%}"), use_container_width=True)

    shared = pd.DataFrame(
        {"Value": [f"{beta_u:.4f}", f"{res['d_e']:.4f}", f"{res['beta_l']:.4f}", f"{erp:.2f}%",
                   f"{debt_share:.1f}%", f"{tax_used:.2f}% ({tax_choice})",
                   "manual override" if s_fc_manual is not None else "auto-calculated"]},
        index=["Unlevered beta", "D/E", "Relevered beta", "Equity risk premium", "Debt share",
               "Project tax rate", "Foreign-currency BBB spread"],
    )
    with st.expander("Shared parameters (same in both currencies)", expanded=True):
        st.table(shared)

    # ---------------- assumptions ----------------
    with st.expander("📐 Formulas and main assumptions", expanded=False):
        st.markdown("**Shared across currencies:** unlevered beta, debt share, equity risk premium, "
                    "and one project tax rate (U.S. or selected country).")
        st.latex(r"\beta_L=\beta_U\left[1+(1-t)\tfrac{D}{E}\right],\qquad \tfrac{D}{E}=\tfrac{w_D}{1-w_D}")
        st.latex(r"r_E^{c}=y^{c}_{10Y}+\beta_L\times ERP \qquad r_D^{c}=y^{c}_{10Y}+s^{c}_{BBB}")
        st.latex(r"WACC^{c}=(1-w_D)\,r_E^{c}+w_D\,r_D^{c}\,(1-t)")
        st.latex(r"s^{FC}_{BBB}=s^{USD}_{BBB}\times\frac{1+y^{FC}_{10Y}}{1+y^{US}_{10Y}}\quad"
                 r"\text{(auto, unless overridden)}")
        st.markdown(
            "- The 10-year government bond yield in each currency is the risk-free rate for that currency; "
            "the yield gap is read as expected inflation/currency depreciation, so differences between the "
            "two columns are a **currency** effect, not a country-risk premium.\n"
            "- The project is a BBB-rated borrower. The auto foreign spread converts the USD borrowing cost "
            "at the yield differential, i.e. (1+r_D^FC) = (1+r_D^USD)(1+y^FC)/(1+y^US).\n"
            "- Beta is Damodaran's U.S. industry **unlevered beta** (not cash-corrected), relevered at the "
            "target debt share with the project tax rate.\n"
            "- Tax rates are OECD combined (central + sub-central) statutory corporate income tax rates.\n"
            "- If the selected country is the U.S., or the two yields are equal and the foreign spread "
            "override is off, both columns are identical.")

    # ---------------- all-industry comparison ----------------
    st.subheader("All-industry comparison")
    st.caption("Fetched unlevered beta for every industry; all other inputs as set in the sidebar.")
    allr = compute(beta_df["Unlevered beta"], **args)
    all_df = pd.DataFrame({
        "Industry": beta_df["Industry"],
        "Unlevered beta": beta_df["Unlevered beta"],
        "Relevered beta": allr["beta_l"],
        "Cost of equity USD": allr["re_usd"], "WACC USD": allr["wacc_usd"],
        f"Cost of equity {ccy}": allr["re_fc"], f"WACC {ccy}": allr["wacc_fc"],
    }).sort_values("WACC USD", ascending=False).reset_index(drop=True)
    pct_cols = [c for c in all_df.columns if c.startswith(("Cost", "WACC"))]
    st.dataframe(
        all_df.style.format({**{c: "{:.2%}" for c in pct_cols},
                             "Unlevered beta": "{:.4f}", "Relevered beta": "{:.4f}"}),
        use_container_width=True, hide_index=True, height=380)
    chart_cols = ["WACC USD"] + ([f"WACC {ccy}"] if f"WACC {ccy}" != "WACC USD" else [])
    st.bar_chart((all_df.set_index("Industry")[chart_cols] * 100), height=420, stack=False,
                 y_label="WACC (%)")

    # ---------------- sources ----------------
    st.subheader("Sources and dates")

    def status(live, manual):
        return "manual override" if manual else ("live" if live else "FALLBACK / placeholder")

    sources = pd.DataFrame([
        ["Unlevered beta", f"{beta_u:.4f}", "Damodaran – betas.xls (U.S. industry averages)",
         betas["date"], betas["fetched"], status(betas["live"], m_beta), BETAS_URL],
        ["USD BBB spread", f"{s_usd:.2f}%", "Damodaran – ratings table, Baa2/BBB, large non-financial firms",
         bbb["date"], bbb["fetched"], status(bbb["live"], m_s), bbb["url"]],
        ["U.S. corporate tax rate", f"{tax_us:.2f}%", tax["source"], tax["date"], tax["fetched"],
         status(tax["live"] and tax_us_f is not None, m_tus), tax["url"]],
        [f"{country} corporate tax rate", f"{tax_fc:.2f}%", tax["source"], tax["date"], tax["fetched"],
         status(tax["live"] and tax_fc_f is not None, m_tfc), tax["url"]],
        ["U.S. 10Y yield", f"{y_us:.2f}%", "Trading Economics", y_us_date, yields["fetched"],
         status(y_us_f is not None, m_yus), y_us_url],
        [f"{country} 10Y yield", f"{y_fc:.2f}%", "Trading Economics", y_fc_date, yields["fetched"],
         status(y_fc_f is not None, m_yfc), y_fc_url],
    ], columns=["Input", "Value used", "Source", "Data date", "Fetched at", "Status", "URL"])
    st.dataframe(sources, use_container_width=True, hide_index=True,
                 column_config={"URL": st.column_config.LinkColumn("URL", display_text="link")})

    # ---------------- downloads ----------------
    st.subheader("Download")
    out = summary.reset_index().rename(columns={"index": "Item"})
    out.insert(0, "Section", "Results")
    extra = shared.reset_index().rename(columns={"index": "Item", "Value": "USD"})
    extra.insert(0, "Section", "Shared parameters")
    meta = pd.DataFrame({"Section": "Selection", "Item": ["Industry", "Country", "Generated"],
                         "USD": [industry, country, _now()]})
    src = sources.rename(columns={"Input": "Item", "Value used": "USD"})[["Item", "USD", "Source", "Data date", "Status", "URL"]]
    src.insert(0, "Section", "Sources")
    results_csv = pd.concat([meta, out, extra, src], ignore_index=True).to_csv(index=False)
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Results (CSV)", results_csv, "cost_of_capital_results.csv", "text/csv",
                       use_container_width=True)
    d2.download_button("⬇️ All-industry comparison (CSV)", all_df.to_csv(index=False),
                       "all_industry_comparison.csv", "text/csv", use_container_width=True)


if __name__ == "__main__":
    main()
