# PLAN.md

## Objective
Build a yield-curve regime classification system and duration-based bond allocation strategy.

## Day 1 – Data Layer
- Collect US Treasury yields (3M,2Y,5Y,10Y,30Y)
- Collect ETF prices (TLT, IEF, SHY)
- Store raw data in MongoDB
- Normalize and upsert structured data into PostgreSQL
- Validate date continuity

## Day 2 – Modeling
- Compute Level/Slope/Curvature
- Perform PCA or spread-based decomposition
- Apply clustering (KMeans/GMM)
- Store regime labels

## Day 3 – Strategy
- Map regime → duration bucket
- Apply daily rebalance (shifted signal)
- Include transaction cost (5–10 bps)
- Compute CAGR, Sharpe, MDD, Turnover
- Store backtest results