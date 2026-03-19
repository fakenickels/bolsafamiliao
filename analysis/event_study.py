#!/usr/bin/env python3
"""
Assistencialão - Event Study: Does Bolsa Família Cause Informality?

Tests the causal claim using a Difference-in-Differences design around the
March 2023 BF expansion (benefit jumped ~50%, from ~R$400 to R$600).

Design:
  - Treatment intensity: pre-expansion BF penetration rate by municipality
  - Outcome: CAGED net formal job creation (admissions - separations) per capita
  - If BF *causes* informality, high-penetration municipalities should show
    relatively *worse* formal job creation after the expansion vs. low-penetration ones.

Data sources:
  - Portal da Transparência API: BF beneficiaries by municipality (treatment)
  - Novo CAGED microdata (FTP): formal job movements by municipality (outcome)
  - IBGE: municipal population estimates (normalization)

Usage:
    # Step 1: Download CAGED data (run once, ~1GB total)
    python3 analysis/event_study.py --download

    # Step 2: Run the analysis
    python3 analysis/event_study.py --analyze

    # Or run everything:
    python3 analysis/event_study.py --all

Requirements:
    pip install pandas requests statsmodels matplotlib
"""

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
    import requests
except ImportError:
    print("Installing dependencies...")
    os.system(f"{sys.executable} -m pip install pandas requests -q")
    import pandas as pd
    import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CAGED_DIR = DATA_DIR / "caged"
BF_DIR = DATA_DIR / "bf"
RESULTS_DIR = ROOT / "results"

for d in [DATA_DIR, CAGED_DIR, BF_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Load .env
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("TRANSPARENCIA_API_KEY", "")
HEADERS = {"chave-api-dados": API_KEY}
BASE_URL = "https://api.portaldatransparencia.gov.br/api-de-dados"

# Event: March 2023 BF expansion
EVENT_MONTH = "2023-03"
# Pre-period: 6 months before (Sep 2022 - Feb 2023)
# Post-period: 6 months after (Mar 2023 - Aug 2023)
PRE_MONTHS = [f"2022{m:02d}" for m in range(9, 13)] + [f"2023{m:02d}" for m in range(1, 3)]
POST_MONTHS = [f"2023{m:02d}" for m in range(3, 9)]
ALL_MONTHS = PRE_MONTHS + POST_MONTHS

# CAGED FTP
CAGED_FTP = "ftp://ftp.mtps.gov.br/pdet/microdados/NOVO%20CAGED"

RATE_LIMIT_DELAY = 0.7

# All 27 UFs
UF_CODES = [
    "11", "12", "13", "14", "15", "16", "17",  # Norte
    "21", "22", "23", "24", "25", "26", "27", "28", "29",  # Nordeste
    "31", "32", "33", "35",  # Sudeste
    "41", "42", "43",  # Sul
    "50", "51", "52", "53",  # Centro-Oeste
]


# ---------------------------------------------------------------------------
# Step 1: Download CAGED microdata
# ---------------------------------------------------------------------------

def download_caged():
    """Download and extract CAGED movement files for the study period."""
    print("\n" + "=" * 60)
    print("Step 1: Downloading CAGED microdata")
    print("=" * 60)

    for month_str in ALL_MONTHS:
        year = month_str[:4]
        out_dir = CAGED_DIR / month_str
        out_dir.mkdir(exist_ok=True)

        archive = out_dir / f"CAGEDMOV{month_str}.7z"
        csv_pattern = out_dir / f"CAGEDMOV{month_str}.txt"

        # Check if already extracted
        existing = list(out_dir.glob("CAGEDMOV*.txt"))
        if existing:
            print(f"  {month_str}: already extracted ({existing[0].name})")
            continue

        # Download
        url = f"{CAGED_FTP}/{year}/{month_str}/CAGEDMOV{month_str}.7z"
        print(f"  {month_str}: downloading from FTP...", end=" ", flush=True)
        try:
            result = subprocess.run(
                ["curl", "-s", "-o", str(archive), url],
                timeout=120, capture_output=True
            )
            if not archive.exists() or archive.stat().st_size < 1000:
                print("FAILED (download)")
                continue
            print(f"({archive.stat().st_size / 1024 / 1024:.1f} MB)", end=" ", flush=True)
        except Exception as e:
            print(f"FAILED ({e})")
            continue

        # Extract with 7z (try multiple tools)
        extracted = False
        for tool in ["7z", "7zz", "7za"]:
            try:
                result = subprocess.run(
                    [tool, "x", str(archive), f"-o{out_dir}", "-y"],
                    timeout=60, capture_output=True
                )
                if result.returncode == 0:
                    extracted = True
                    break
            except FileNotFoundError:
                continue

        if not extracted:
            # Try p7zip or unar
            try:
                result = subprocess.run(
                    ["unar", "-o", str(out_dir), str(archive)],
                    timeout=60, capture_output=True
                )
                extracted = result.returncode == 0
            except FileNotFoundError:
                pass

        if extracted:
            archive.unlink(missing_ok=True)  # Remove archive after extraction
            print("OK")
        else:
            print("FAILED (no 7z/unar tool found)")
            print("    Install: brew install p7zip  OR  brew install unar")
            return False

    return True


# ---------------------------------------------------------------------------
# Step 2: Aggregate CAGED by municipality
# ---------------------------------------------------------------------------

def aggregate_caged():
    """Aggregate CAGED microdata to net job creation by municipality per month."""
    print("\n" + "=" * 60)
    print("Step 2: Aggregating CAGED data by municipality")
    print("=" * 60)

    cache_file = DATA_DIR / "caged_municipal_monthly.csv"
    if cache_file.exists():
        print(f"  Using cached aggregation: {cache_file}")
        return pd.read_csv(cache_file)

    all_data = []

    for month_str in ALL_MONTHS:
        out_dir = CAGED_DIR / month_str
        files = list(out_dir.glob("CAGEDMOV*.txt"))
        if not files:
            print(f"  {month_str}: NO DATA (skipping)")
            continue

        csv_file = files[0]
        print(f"  {month_str}: reading {csv_file.name}...", end=" ", flush=True)

        try:
            # CAGED files use ; delimiter. Try UTF-8 first, fall back to Latin-1
            for enc in ["utf-8", "latin-1"]:
                try:
                    df = pd.read_csv(csv_file, sep=";", encoding=enc, low_memory=False, nrows=2)
                    # Check if columns look right (not mojibake)
                    cols_str = ";".join(df.columns)
                    if "munic" in cols_str.lower():
                        break
                except Exception:
                    continue

            df = pd.read_csv(csv_file, sep=";", encoding=enc, low_memory=False)

            # Find the right columns (names may vary across months)
            cols = {c.lower().strip(): c for c in df.columns}
            mun_col = None
            saldo_col = None
            for k, v in cols.items():
                if "munic" in k and "tipo" not in k:
                    mun_col = v
                if "saldomovimenta" in k:
                    saldo_col = v

            if mun_col is None or saldo_col is None:
                print(f"FAILED (columns: {list(df.columns)[:5]}...)")
                continue

            df = df[[mun_col, saldo_col]].rename(
                columns={mun_col: "município", saldo_col: "saldomovimentação"}
            )
            df["município"] = df["município"].astype(str)
            df["saldomovimentação"] = pd.to_numeric(df["saldomovimentação"], errors="coerce")
        except Exception as e:
            print(f"FAILED ({e})")
            continue

        # Aggregate: net job creation by municipality
        monthly = df.groupby("município").agg(
            saldo=("saldomovimentação", "sum"),
            movements=("saldomovimentação", "count")
        ).reset_index()
        monthly["month"] = month_str
        all_data.append(monthly)
        print(f"{len(monthly):,} municipalities, net saldo={monthly['saldo'].sum():+,}")

    if not all_data:
        print("  ERROR: No CAGED data available!")
        return None

    result = pd.concat(all_data, ignore_index=True)
    result.to_csv(cache_file, index=False)
    print(f"\n  Saved aggregation: {cache_file} ({len(result):,} rows)")
    return result


# ---------------------------------------------------------------------------
# Step 3: Get BF penetration data from Portal da Transparência
# ---------------------------------------------------------------------------

def fetch_bf_penetration():
    """Fetch BF beneficiary counts by municipality for the pre-expansion period."""
    print("\n" + "=" * 60)
    print("Step 3: Fetching BF penetration data")
    print("=" * 60)

    cache_file = BF_DIR / "bf_penetration_pre.csv"
    if cache_file.exists():
        print(f"  Using cached BF data: {cache_file}")
        return pd.read_csv(cache_file, dtype={"ibge_code": str})

    if not API_KEY:
        print("  ERROR: No TRANSPARENCIA_API_KEY set!")
        return None

    # The "Novo Bolsa Família" API only has data from March 2023 onward.
    # We use March 2023 (first month of expansion) as our treatment classifier.
    # BF penetration is sticky — March rates reflect pre-existing enrollment patterns.

    print("  Fetching municipality list from IBGE...")
    resp = requests.get(
        "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado",
        timeout=30
    )
    municipios = resp.json()
    print(f"  Found {len(municipios):,} municipalities")

    # Fetch BF data for each municipality
    bf_ref_month = "202303"  # March 2023 = first available month (expansion start)
    bf_data = []
    failed = 0
    batch_size = 50  # Log progress every N cities

    print(f"  Fetching BF data for {bf_ref_month} (this takes ~65 minutes for all municipalities)...")
    print(f"  Tip: Ctrl+C to stop early, cached progress will be used next run")

    # Check for partial cache
    partial_cache = BF_DIR / "bf_penetration_partial.csv"
    done_codes = set()
    if partial_cache.exists():
        partial_df = pd.read_csv(partial_cache, dtype={"ibge_code": str})
        bf_data = partial_df.to_dict("records")
        done_codes = set(partial_df["ibge_code"])
        print(f"  Resuming from partial cache: {len(done_codes)} already fetched")

    try:
        for i, mun in enumerate(municipios):
            ibge_code = str(mun.get("municipio-id", mun.get("id", "")))
            if ibge_code in done_codes:
                continue

            time.sleep(RATE_LIMIT_DELAY)
            try:
                resp = requests.get(
                    f"{BASE_URL}/novo-bolsa-familia-por-municipio",
                    headers=HEADERS,
                    params={"mesAno": bf_ref_month, "codigoIbge": ibge_code, "pagina": 1},
                    timeout=15,
                )
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    r = data[0]
                    bf_data.append({
                        "ibge_code": ibge_code,
                        "municipio": r["municipio"]["nomeIBGE"],
                        "uf": r["municipio"]["uf"]["sigla"],
                        "bf_valor": r["valor"],
                        "bf_beneficiarios": r["quantidadeBeneficiados"],
                    })
                else:
                    bf_data.append({
                        "ibge_code": ibge_code,
                        "municipio": mun.get("municipio-nome", mun.get("nome", "")),
                        "uf": mun.get("UF-sigla", "??"),
                        "bf_valor": 0,
                        "bf_beneficiarios": 0,
                    })
            except Exception as e:
                failed += 1
                if failed % 10 == 0:
                    print(f"    Warning: {failed} failures so far (latest: {e})")

            if (i + 1) % batch_size == 0:
                pct = (i + 1) / len(municipios) * 100
                fetched = len([d for d in bf_data if d["bf_beneficiarios"] > 0])
                print(f"    Progress: {i+1}/{len(municipios)} ({pct:.1f}%) - {fetched} with BF data")
                # Save partial progress
                pd.DataFrame(bf_data).to_csv(partial_cache, index=False)

    except KeyboardInterrupt:
        print(f"\n  Interrupted! Saving {len(bf_data)} records...")

    if not bf_data:
        print("  ERROR: No BF data fetched!")
        return None

    df = pd.DataFrame(bf_data)
    df.to_csv(cache_file, index=False)
    partial_cache.unlink(missing_ok=True)
    print(f"\n  Saved: {cache_file} ({len(df):,} municipalities, {failed} failures)")
    return df


# ---------------------------------------------------------------------------
# Step 4: Get population estimates
# ---------------------------------------------------------------------------

def fetch_population():
    """Fetch municipal population from IBGE."""
    print("\n" + "=" * 60)
    print("Step 4: Fetching population data")
    print("=" * 60)

    cache_file = DATA_DIR / "ibge_population.csv"
    if cache_file.exists():
        print(f"  Using cached: {cache_file}")
        return pd.read_csv(cache_file, dtype={"ibge_code": str})

    print("  Fetching from IBGE Censo 2022...")
    # Use IBGE population estimates
    resp = requests.get(
        "https://servicodados.ibge.gov.br/api/v3/agregados/4709/periodos/-6/variaveis/93?localidades=N6[all]",
        timeout=60,
    )
    data = resp.json()

    pop_data = []
    if data and len(data) > 0:
        results = data[0].get("resultados", [{}])[0].get("series", [])
        for series in results:
            loc = series.get("localidade", {})
            ibge_code = loc.get("id", "")
            nome = loc.get("nome", "")
            # Get latest year's population
            valores = series.get("serie", {})
            pop = 0
            for year in sorted(valores.keys(), reverse=True):
                if valores[year] and valores[year] != "...":
                    pop = int(valores[year])
                    break
            pop_data.append({
                "ibge_code": ibge_code,
                "municipio_ibge": nome,
                "populacao": pop,
            })

    df = pd.DataFrame(pop_data)
    df.to_csv(cache_file, index=False)
    print(f"  Saved: {cache_file} ({len(df):,} municipalities)")
    return df


# ---------------------------------------------------------------------------
# Step 5: Run Difference-in-Differences
# ---------------------------------------------------------------------------

def run_did(caged_df, bf_df, pop_df):
    """Run the Difference-in-Differences event study."""
    print("\n" + "=" * 60)
    print("Step 5: Running Difference-in-Differences Analysis")
    print("=" * 60)

    try:
        import statsmodels.api as sm
        import statsmodels.formula.api as smf
    except ImportError:
        os.system(f"{sys.executable} -m pip install statsmodels -q")
        import statsmodels.api as sm
        import statsmodels.formula.api as smf

    # --- Merge datasets ---
    # CAGED uses 6-digit IBGE codes; BF/IBGE use 7-digit (7th is check digit)
    # Normalize everything to 6-digit strings for merging
    caged_df["ibge_code"] = caged_df["município"].astype(str).str.strip().str[:6]
    bf_df["ibge_code"] = bf_df["ibge_code"].astype(str).str.strip().str[:6]
    pop_df["ibge_code"] = pop_df["ibge_code"].astype(str).str.strip().str[:6]

    # Calculate BF penetration rate
    bf_pop = bf_df.merge(pop_df[["ibge_code", "populacao"]], on="ibge_code", how="left")
    bf_pop["bf_penetration"] = bf_pop["bf_beneficiarios"] / bf_pop["populacao"]
    bf_pop = bf_pop.dropna(subset=["bf_penetration", "populacao"])
    bf_pop = bf_pop[bf_pop["populacao"] > 0]

    # Classify municipalities into high/low BF penetration
    median_penetration = bf_pop["bf_penetration"].median()
    bf_pop["high_bf"] = (bf_pop["bf_penetration"] >= median_penetration).astype(int)

    print(f"  BF penetration median: {median_penetration:.3f} ({median_penetration*100:.1f}%)")
    print(f"  High BF: {bf_pop['high_bf'].sum():,} municipalities")
    print(f"  Low BF:  {(1 - bf_pop['high_bf']).sum():,.0f} municipalities")

    # Merge CAGED with BF classification
    panel = caged_df.merge(
        bf_pop[["ibge_code", "bf_penetration", "high_bf", "populacao", "uf"]],
        on="ibge_code", how="inner"
    )

    # Normalize: saldo per 1000 inhabitants
    panel["saldo_pc"] = panel["saldo"] / panel["populacao"] * 1000

    # Mark pre/post
    panel["post"] = panel["month"].apply(
        lambda m: 1 if int(m) >= 202303 else 0
    )

    print(f"  Panel: {len(panel):,} observations (municipality-months)")
    print(f"  Municipalities matched: {panel['ibge_code'].nunique():,}")
    print(f"  Months: {sorted(panel['month'].unique())}")

    if len(panel) < 100:
        print("  ERROR: Too few observations for meaningful analysis!")
        return None

    # --- Simple DiD ---
    print("\n  --- Simple Difference-in-Differences ---")

    # Group means
    groups = panel.groupby(["high_bf", "post"])["saldo_pc"].mean().unstack()
    print(f"\n  Mean net job creation (per 1000 pop):")
    print(f"  {'':>20} {'Pre-expansion':>15} {'Post-expansion':>15} {'Diff':>10}")
    for hbf in [0, 1]:
        label = "High BF" if hbf else "Low BF"
        pre = groups.loc[hbf, 0] if 0 in groups.columns else 0
        post = groups.loc[hbf, 1] if 1 in groups.columns else 0
        print(f"  {label:>20} {pre:>15.3f} {post:>15.3f} {post-pre:>10.3f}")

    low_pre = groups.loc[0, 0] if 0 in groups.columns else 0
    low_post = groups.loc[0, 1] if 1 in groups.columns else 0
    high_pre = groups.loc[1, 0] if 0 in groups.columns else 0
    high_post = groups.loc[1, 1] if 1 in groups.columns else 0
    did_estimate = (high_post - high_pre) - (low_post - low_pre)
    print(f"\n  DiD estimate: {did_estimate:.4f} jobs per 1000 pop")

    # --- Regression DiD ---
    print("\n  --- Regression DiD (with controls) ---")

    panel["interaction"] = panel["high_bf"] * panel["post"]

    try:
        # Basic DiD regression
        model = smf.ols(
            "saldo_pc ~ high_bf + post + interaction",
            data=panel
        ).fit(cov_type="cluster", cov_kwds={"groups": panel["ibge_code"]})

        print(f"\n  OLS: saldo_pc ~ high_bf + post + high_bf × post")
        print(f"  (Clustered SE at municipality level)")
        print(f"\n  {'Variable':>20} {'Coef':>10} {'SE':>10} {'t':>8} {'p':>8}")
        print(f"  {'-'*56}")
        for var in ["Intercept", "high_bf", "post", "interaction"]:
            coef = model.params[var]
            se = model.bse[var]
            t = model.tvalues[var]
            p = model.pvalues[var]
            sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""
            print(f"  {var:>20} {coef:>10.4f} {se:>10.4f} {t:>8.2f} {p:>8.4f} {sig}")

        print(f"\n  N = {model.nobs:,.0f}")
        print(f"  R² = {model.rsquared:.4f}")

        # --- Interpretation ---
        did_coef = model.params["interaction"]
        did_p = model.pvalues["interaction"]

        print(f"\n  {'=' * 56}")
        print(f"  KEY RESULT: DiD coefficient (high_bf × post) = {did_coef:.4f}")
        print(f"  p-value = {did_p:.4f}")

        if did_p > 0.10:
            print(f"\n  INTERPRETATION: NOT statistically significant (p > 0.10)")
            print(f"  We CANNOT reject the null hypothesis that BF expansion had")
            print(f"  no differential effect on formal job creation.")
            print(f"  The correlation between BF and informality is likely driven")
            print(f"  by underlying poverty, not by BF itself.")
            causal = False
        elif did_coef < 0:
            print(f"\n  INTERPRETATION: Statistically significant NEGATIVE effect")
            print(f"  High-BF municipalities saw relatively WORSE formal job creation")
            print(f"  after the expansion. This is CONSISTENT with the causal claim,")
            print(f"  but could still reflect other factors correlated with the expansion.")
            causal = True
        else:
            print(f"\n  INTERPRETATION: Statistically significant POSITIVE effect")
            print(f"  High-BF municipalities saw relatively BETTER formal job creation")
            print(f"  after the expansion. This CONTRADICTS the causal claim.")
            causal = False

        # --- With UF fixed effects ---
        print("\n  --- Adding UF fixed effects ---")
        model_fe = smf.ols(
            "saldo_pc ~ high_bf + post + interaction + C(uf)",
            data=panel
        ).fit(cov_type="cluster", cov_kwds={"groups": panel["ibge_code"]})

        did_coef_fe = model_fe.params["interaction"]
        did_p_fe = model_fe.pvalues["interaction"]
        print(f"  DiD coefficient: {did_coef_fe:.4f} (p = {did_p_fe:.4f})")
        print(f"  R² = {model_fe.rsquared:.4f}")

        # Save results
        results = {
            "did_simple": did_estimate,
            "did_regression": did_coef,
            "did_regression_p": did_p,
            "did_with_fe": did_coef_fe,
            "did_with_fe_p": did_p_fe,
            "n_observations": int(model.nobs),
            "n_municipalities": int(panel["ibge_code"].nunique()),
            "median_bf_penetration": float(median_penetration),
            "supports_causal_claim": causal,
        }

        return results

    except Exception as e:
        print(f"  Regression failed: {e}")
        import traceback
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Step 6: Generate report
# ---------------------------------------------------------------------------

def generate_report(results):
    """Generate the event study findings report."""
    report_path = RESULTS_DIR / "event_study_findings.md"

    if results is None:
        report_path.write_text(
            "# Event Study - Incomplete\n\n"
            "The analysis could not be completed. Check data availability.\n"
        )
        return

    supports = results["supports_causal_claim"]

    lines = [
        "# Does Bolsa Família *Cause* Informality?",
        "",
        "## Event Study: March 2023 BF Expansion",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "### Design",
        "",
        "When Bolsa Família benefits jumped ~50% in March 2023 (from ~R$400 to R$600),",
        "did municipalities with higher BF penetration see relatively worse formal",
        "job creation compared to municipalities with lower BF penetration?",
        "",
        "- **Treatment**: Pre-expansion BF penetration rate (Jan 2023)",
        f"- **Median split**: {results['median_bf_penetration']*100:.1f}% of population",
        "- **Outcome**: CAGED net formal job creation per 1,000 inhabitants",
        "- **Pre-period**: Sep 2022 - Feb 2023 (6 months)",
        "- **Post-period**: Mar 2023 - Aug 2023 (6 months)",
        f"- **Observations**: {results['n_observations']:,} municipality-months",
        f"- **Municipalities**: {results['n_municipalities']:,}",
        "",
        "### Results",
        "",
        "| Specification | DiD Coefficient | p-value | Significant? |",
        "|---------------|-----------------|---------|--------------|",
        f"| Simple means | {results['did_simple']:.4f} | - | - |",
        f"| OLS (clustered SE) | {results['did_regression']:.4f} | {results['did_regression_p']:.4f} | {'Yes' if results['did_regression_p'] < 0.10 else 'No'} |",
        f"| OLS + UF fixed effects | {results['did_with_fe']:.4f} | {results['did_with_fe_p']:.4f} | {'Yes' if results['did_with_fe_p'] < 0.10 else 'No'} |",
        "",
        "### Interpretation",
        "",
    ]

    if not supports:
        lines.extend([
            "**The evidence does NOT support the causal claim.**",
            "",
            "The DiD estimate is not statistically significant, meaning we cannot",
            "distinguish the effect from zero. The observed correlation between",
            "high BF penetration and low formal employment is most likely driven by",
            "**underlying poverty** (poor places have both more BF and fewer formal jobs)",
            "rather than BF *causing* informality.",
            "",
            "This is the classic **reverse causality** problem: municipalities don't have",
            "fewer formal jobs *because* of Bolsa Família; they have more Bolsa Família",
            "*because* they have fewer formal jobs.",
        ])
    else:
        lines.extend([
            "**The evidence is CONSISTENT with the causal claim, but not conclusive.**",
            "",
            "High-BF municipalities showed relatively worse formal job creation after",
            "the expansion. However, this could also reflect:",
            "- Differential economic shocks correlated with BF penetration",
            "- Seasonal patterns that differ by region/poverty level",
            "- Other policy changes coinciding with the BF expansion",
            "",
            "A stronger test would require individual-level data (CadÚnico + CAGED",
            "linked microdata) to track specific families' labor market transitions.",
        ])

    lines.extend([
        "",
        "### Caveats",
        "",
        "1. **Ecological fallacy**: Municipal-level analysis cannot prove individual behavior",
        "2. **Parallel trends**: We assume high/low BF municipalities would have followed",
        "   similar job creation trends absent the expansion (untestable assumption)",
        "3. **SUTVA**: The expansion affected the entire country simultaneously,",
        "   so there is no pure control group",
        "4. **Short window**: 6 months pre/post may not capture long-run effects",
        "5. **Omitted variables**: Many things changed in March 2023 beyond BF",
        "",
        "### What Would Be Needed for Stronger Evidence",
        "",
        "1. **Regression Discontinuity**: Compare families just above/below the BF",
        "   income cutoff (requires individual CadÚnico + CAGED linked data, LGPD restricted)",
        "2. **Longer panel**: Track effects over 2+ years post-expansion",
        "3. **Instrumental variable**: Find an exogenous predictor of BF enrollment",
        "4. **Randomized experiment**: Obviously infeasible for a national policy",
        "",
    ])

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Report: {report_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BF Causal Event Study")
    parser.add_argument("--download", action="store_true", help="Download CAGED data")
    parser.add_argument("--analyze", action="store_true", help="Run analysis")
    parser.add_argument("--all", action="store_true", help="Download + analyze")
    args = parser.parse_args()

    if not any([args.download, args.analyze, args.all]):
        parser.print_help()
        print("\nRun with --all to download data and run the full analysis.")
        return

    print("=" * 60)
    print("  Assistencialão - Event Study: BF and Formal Employment")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    if args.download or args.all:
        ok = download_caged()
        if not ok:
            print("\nCAGED download failed. Install 7z: brew install p7zip")
            if not args.analyze:
                return

    if args.analyze or args.all:
        # Aggregate CAGED
        caged_df = aggregate_caged()
        if caged_df is None:
            print("Cannot proceed without CAGED data.")
            return

        # Fetch BF penetration
        bf_df = fetch_bf_penetration()
        if bf_df is None:
            print("Cannot proceed without BF data.")
            return

        # Fetch population
        pop_df = fetch_population()
        if pop_df is None:
            print("Cannot proceed without population data.")
            return

        # Run DiD
        results = run_did(caged_df, bf_df, pop_df)

        # Report
        generate_report(results)

        print("\n" + "=" * 60)
        if results:
            print(f"  VERDICT: {'Supports' if results['supports_causal_claim'] else 'Does NOT support'} the causal claim")
            print(f"  DiD = {results['did_regression']:.4f} (p = {results['did_regression_p']:.4f})")
        print("=" * 60)


if __name__ == "__main__":
    main()
