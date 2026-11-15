# International Cost of Capital App

A Streamlit app that compares a project's **cost of equity, cost of debt and WACC in USD and in the currency of a selected country**, using the same industry beta, debt share, equity risk premium and project tax rate in both currencies.

## Defaults on opening

| Setting | Default |
|---|---|
| Industry | Software (System & Application) |
| Target country | United States |
| Project tax rate | U.S. |
| Equity risk premium | 6.5% |
| Debt share D/(D+E) | 30% |

With the U.S. as the selected country, both columns are identical.

## Data sources

| Input | Source | How it is read |
|---|---|---|
| Industry unlevered betas | Damodaran, `betas.xls` | "Unlevered beta" column (not cash-corrected); date from the sheet's "Date updated" cell |
| USD BBB spread | Damodaran, `ratings.html` | Baa2/BBB row of the table for large non-financial service firms; "Date of Analysis" line |
| Corporate tax rates | OECD | Combined (central + sub-central) statutory CIT rate. Tries the OECD Data Explorer API (latest year), then the Corporate Tax Statistics report page, then an embedded snapshot |
| 10Y government yields | Trading Economics, `/bonds` | Scraped table (no API key); if the table cannot be read, the country's own bond-yield page |

Every value's source, data date, fetch time and status (**live / manual override / fallback**) is shown in the "Sources and dates" table. **Refresh data** in the sidebar clears the cache and re-fetches everything. If a fetch fails the app shows a warning and uses a clearly labelled fallback or placeholder, which you should replace with a manual override.

## Formulas

All inputs are shared across the two currencies except the 10Y government yield and the BBB spread.

```
D/E        = w_D / (1 - w_D)
beta_L     = beta_U * [1 + (1 - t) * D/E]

Cost of equity (currency c)   r_E = y_c + beta_L * ERP
Cost of debt   (currency c)   r_D = y_c + s_c
WACC           (currency c)   = (1 - w_D) * r_E + w_D * r_D * (1 - t)

Foreign BBB spread (auto)     s_FC = s_USD * (1 + y_FC) / (1 + y_US)
```

The auto foreign spread converts the USD borrowing cost at the government-yield differential: `(1 + r_D_FC) = (1 + r_D_USD) * (1 + y_FC) / (1 + y_US)`. It can be replaced by a manual value.

All formulas live in one function, `compute()` in `app.py`.

## Controls

- Industry, target country, equity risk premium, target debt share
- Project tax rate switch: U.S. or selected country
- Manual overrides: unlevered beta, both tax rates, USD BBB spread, both government yields, and the foreign-currency BBB spread (auto-calculated when the override is off)

## Outputs

- Side-by-side USD vs. local-currency results and the difference
- Shared parameters, formulas and assumptions
- All-industry comparison (table + chart)
- CSV downloads: results (with inputs and sources) and the all-industry table

## Verification checks

1. **Hand example** (override inputs: beta_U 1.20, tax 25.63%, debt 30%, ERP 6.5%, U.S. yield 4.00%, foreign yield 8.00%, USD spread 1.11%)
   - D/E = 0.428571; beta_L = 1.20 × (1 + 0.7437 × 0.428571) = 1.5825
   - USD: r_E = 14.29%, r_D = 5.11%, WACC = 0.7 × 14.2861% + 0.3 × 5.11% × 0.7437 = **11.14%**
   - Foreign: s_FC = 1.11% × 1.08/1.04 = 1.1527%; r_E = 18.29%, r_D = 9.15%, WACC = **14.84%**
2. Equal government yields (spread override off) → identical results in both columns.
3. Debt share 0% → WACC = cost of equity in both currencies.
4. Overriding the foreign-currency spread changes only the foreign cost of debt and WACC; USD results do not move.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Create a GitHub repository and upload `app.py`, `requirements.txt` and `README.md`.
2. Go to share.streamlit.io → **New app** → pick the repository, branch `main`, main file `app.py` → **Deploy**.
