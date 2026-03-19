# Does Bolsa Família *Cause* Informality?

## Event Study: March 2023 BF Expansion

**Generated:** 2026-03-19 18:06

### Design

When Bolsa Família benefits jumped ~50% in March 2023 (from ~R$400 to R$600),
did municipalities with higher BF penetration see relatively worse formal
job creation compared to municipalities with lower BF penetration?

- **Treatment**: Pre-expansion BF penetration rate (Jan 2023)
- **Median split**: 11.0% of population
- **Outcome**: CAGED net formal job creation per 1,000 inhabitants
- **Pre-period**: Sep 2022 - Feb 2023 (6 months)
- **Post-period**: Mar 2023 - Aug 2023 (6 months)
- **Observations**: 65,117 municipality-months
- **Municipalities**: 5,560

### Results

| Specification | DiD Coefficient | p-value | Significant? |
|---------------|-----------------|---------|--------------|
| Simple means | -0.5269 | - | - |
| OLS (clustered SE) | -0.5269 | 0.0000 | Yes |
| OLS + UF fixed effects | -0.5263 | 0.0000 | Yes |

### Interpretation

**The evidence is CONSISTENT with the causal claim, but not conclusive.**

High-BF municipalities showed relatively worse formal job creation after
the expansion. However, this could also reflect:
- Differential economic shocks correlated with BF penetration
- Seasonal patterns that differ by region/poverty level
- Other policy changes coinciding with the BF expansion

A stronger test would require individual-level data (CadÚnico + CAGED
linked microdata) to track specific families' labor market transitions.

### Caveats

1. **Ecological fallacy**: Municipal-level analysis cannot prove individual behavior
2. **Parallel trends**: We assume high/low BF municipalities would have followed
   similar job creation trends absent the expansion (untestable assumption)
3. **SUTVA**: The expansion affected the entire country simultaneously,
   so there is no pure control group
4. **Short window**: 6 months pre/post may not capture long-run effects
5. **Omitted variables**: Many things changed in March 2023 beyond BF

### What Would Be Needed for Stronger Evidence

1. **Regression Discontinuity**: Compare families just above/below the BF
   income cutoff (requires individual CadÚnico + CAGED linked data, LGPD restricted)
2. **Longer panel**: Track effects over 2+ years post-expansion
3. **Instrumental variable**: Find an exogenous predictor of BF enrollment
4. **Randomized experiment**: Obviously infeasible for a national policy
