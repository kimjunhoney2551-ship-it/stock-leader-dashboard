# COMP and F-score calculation policy

User-selected on 2026-10-12 (Korea time).

- Price snapshot: 2026-10-09 US close. Latest financial statements and ownership disclosures are permitted; this is not a point-in-time backtest.
- Base universe: US-listed common shares/ADRs with known market cap ≥ KRW 10 billion, 10-day average dollar volume ≥ USD 5 million and beta ≤ 2.
- Rank momentum (40): for each 4/12/25/52-week return horizon, use the most recent 12 Friday week-ending observations. Compute the cross-sectional midrank percentile each week, then weight × max(0, min(1, mean percentile − population standard deviation)). Weights 8/12/12/8. The current base universe is held fixed. Subtracting SPY's return leaves each weekly cross-sectional rank unchanged. All 12 observations are required; IPO history is not imputed.
- Price momentum (25): 1-week, 1-month, 3-month return and 52-week-high proximity percentiles, 6.25 each.
- Smart money (20): CMF20 percentile × 7, relative dollar volume percentile × 5, comparable institutional shares × 5, 13D/G × 3. The institution calculation uses the same tracked managers with positive positions in both latest consecutive quarters, excluding new and exited positions. It is not total institutional ownership.
- Institutional points: change ≥5%:5; ≥2%:4; ≥0%:3; ≥−2%:2; >−5%:1; otherwise:0.
- 13D/G: recent 90 calendar days by filing date. Maximum qualifying 13D 3 / 13G 2 / no verified qualifying event 0. Latest filing per filer controls. An initial positive report qualifies when at least 5% where the percentage is available. Amendments require a verified increase in shares without a known percentage decrease; a later decrease or exit does not qualify. Inconclusive amendments get no event credit. A failed/unavailable search remains missing. Zero is an observation-based score, not an assertion that no other SEC filing exists.
- Valuation (15): ROE, inverse forward PE, operating-income change percentiles, 5 each. Use available observations in the base universe and disclose coverage. Nonpositive forward PE receives zero. Operating-income change uses (current − previous)/abs(previous), including loss reduction; zero prior income remains undefined. ROE falls back to annual net income divided by average equity when the primary field is missing, with input values retained.
- F-score (4, distinct from Piotroski 9): revenue growth >0; gross margin change >0; SG&A/revenue change <0; asset turnover change >0. Turnover uses average opening/closing assets for each year. All four tests use a consistent pair of consecutive fiscal years. Missing statements are never treated as failed tests.
- Composite (100): F/4 ×40 + 1-month return percentile ×30 + 3-month return percentile ×20 + gross margin change percentile ×10.
- Exact COMP means all 15 components have data. Exact F means all four tests have data. Complete scores may still fail the selection thresholds. Missing components retain lower/upper bounds.
- Preserve COMP ≥80 names; F4 names qualify for selection, other known F values are shadows. Up to ten by composite; combined oil/refining/tanker exposure capped at 30%.

Audit inputs: `data/weekly_ranks.json`, `data/financial_latest.json`, `data/ownership_verified.json`, `data/filing_scores.json`. Source prices: Yahoo Finance adjusted closes; current fundamentals: TradingView and Yahoo annual statements; ownership and event evidence: SEC EDGAR compiled by TradeFilings. See each row's dates and source links.
