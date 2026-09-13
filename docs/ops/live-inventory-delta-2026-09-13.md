# Live inventory vs YAML pin (measured 2026-09-13)

Source of truth remains **`configs/commodities/*.yaml`**, pinned at **52** by
`tests/quality/test_profiles_quality.py` (22 commodities + 30 VN30 equities).
Do **not** invent YAML to match production.

## Counts

| Surface | Profiles | Instruments | Fact rows |
|---|---|---|---|
| Repo YAML + quality pin | 52 | (see load tests: 52 baseline + extra instruments) | n/a |
| Docs snapshot 2026-09-03 (`PLAN.md` §2) | 52 | 100 | n/a |
| Live `GET /stats` 2026-09-13 | **66** | **114** | **464 056** |

Live API: https://cqp-api-402296591988.asia-northeast1.run.app/stats

Every YAML `commodity_code` is present in live `GET /profiles`. The extra **14**
live registry rows have **no matching YAML in this repo**:

| `commodity_code` | claimed `source_path` |
|---|---|
| CTD_VN | `ctd_vn.yaml` |
| DGC_VN | `dgc_vn.yaml` |
| GEX_VN | `gex_vn.yaml` |
| HAG_VN | `hag_vn.yaml` |
| HBC_VN | `hbc_vn.yaml` |
| KBC_VN | `kbc_vn.yaml` |
| KCB_VN | `kcb_vn.yaml` |
| KSB_VN | `ksb_vn.yaml` |
| NKG_VN | `nkg_vn.yaml` |
| NSH_VN | `nsh_vn.yaml` |
| NVL_VN | `nvl_vn.yaml` |
| PET_VN | `pet_vn.yaml` |
| TCL_VN | `tcl_vn.yaml` |
| VCG_VN | `vcg_vn.yaml` |

These are leftover VN equity dimension/registry rows from owner load sessions
2026-07-13→07-17 (`PLAN.md` §5: “all 44 equity tickers already carry full history”).
30 current VN30 YAML + 14 orphans = 44 equities; + 22 commodity YAML = **66**.
Instrument delta (+14 vs the 100-instrument docs snapshot) matches one extra
equity instrument per orphan ticker.

## What not to do

- Do not add those 14 YAML files just to close the count.
- Do not bump the quality pin from 52 to 66.
- Do not delete live rows without a separate, owner-approved prune pack.

## Optional later (owner)

1. Re-onboard a ticker by adding a real YAML profile + `make db-load`.
2. Or prune the 14 orphans from `dim_commodity` / registry after a read-only
   check that no ingest source still writes them.
