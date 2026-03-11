# Bolsa Familia x Emprego Formal - Research Agent Prompt

Use this file as a prompt for an AI agent (Claude, GPT, etc.) to independently verify, correct, and expand the data used in this analysis. The goal is full reproducibility and open scrutiny.

---

## Your Mission

You are a research agent tasked with verifying and correcting the claims made in the analysis at `index.html` in this repository. Your job is to:

1. **Download raw data** from official Brazilian government sources
2. **Verify every number** cited in the presentation
3. **Flag any errors** or misleading claims with corrections
4. **Produce reproducible analysis** (Python or R scripts) that anyone can re-run
5. **Output a corrections report** (`CORRECTIONS.md`) documenting what was right, wrong, or unverifiable

---

## Data Sources to Download

### 1. Bolsa Familia Payments (Municipal Level)

**Source:** Portal da Transparencia - Download de Dados
**URL:** https://portaltransparencia.gov.br/download-de-dados/bolsa-familia-pagamentos
**Format:** CSV, monthly files by state
**Fields needed:** Municipio (IBGE code), Valor Parcela, Mes/Ano Referencia, Quantidade Beneficiarios
**Period:** 2019-2024 (monthly)

**API alternative:**
```
GET https://api.portaltransparencia.gov.br/api-de-dados/bolsa-familia-por-municipio
Headers: chave-api-dados: {YOUR_FREE_API_KEY}
Params: mesAno=202401&codigoIbge=3550308&pagina=1
```
Register for free API key at: https://portaltransparencia.gov.br/api-de-dados/registrar-email

### 2. Formal Employment (CAGED)

**Source:** Novo CAGED - Microdados
**URL:** https://bi.mte.gov.br/bgcaged/
**Format:** CSV (compressed), monthly
**Fields needed:** municipio, saldomovimentacao, categoria, graudeinstrucao, salario
**Period:** 2019-2024 (monthly)

Also available via PDET/MTE FTP server for bulk download.

### 3. RAIS (Annual Formal Employment Stock)

**Source:** RAIS - Microdados
**URL:** https://bi.mte.gov.br/bgcaged/login.php
**Format:** Fixed-width text files, annual
**Fields needed:** municipio, qtd_vinculos_ativos, cnae_2, faixa_remuneracao
**Period:** 2019-2023

### 4. Labor Market (PNAD Continua)

**Source:** IBGE - Microdados PNAD Continua
**URL:** https://www.ibge.gov.br/estatisticas/sociais/trabalho/17270-pnad-continua.html?=&t=microdados
**Format:** Fixed-width text + dictionary file
**Fields needed:** UF, taxa_participacao, taxa_desocupacao, posicao_ocupacao (com/sem carteira)
**Period:** 2019-2024 (quarterly)

**Easier alternative - SIDRA API:**
```
# Table 4093 - Employment by type (com/sem carteira)
https://apisidra.ibge.gov.br/values/t/4093/n1/all/v/1641/p/all/c11913/allxt

# Table 6403 - Unemployment, participation rate
https://apisidra.ibge.gov.br/values/t/6403/n1/all/v/4099/p/all
```

### 5. Municipal Demographics (IBGE)

**Source:** IBGE Cidades / Censo 2022
**URL:** https://servicodados.ibge.gov.br/api/docs
**API examples:**
```
# Population by municipality
https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/-6/variaveis/9324?localidades=N6[all]

# GDP per capita by municipality
https://servicodados.ibge.gov.br/api/v3/agregados/5938/periodos/-6/variaveis/37?localidades=N6[all]
```

### 6. CadUnico / Homeless Population

**Source:** CECAD - Consulta CadUnico
**URL:** https://cecad.cidadania.gov.br/painel03.php
**Also:** VIS DATA III: https://aplicacoes.mds.gov.br/sagi/vis/data3/
**Fields needed:** familias_cadastradas, pessoas_situacao_rua, municipio

### 7. Social Security (INSS/RGPS)

**Source:** Secretaria de Previdencia Social
**URL:** https://www.gov.br/previdencia/pt-br/assuntos/previdencia-social/dados-estatisticos
**Fields needed:** arrecadacao_liquida, despesa_beneficios, por ano
**Period:** 2018-2024

### 8. Municipal Tax Revenue

**Source:** SICONFI / Tesouro Nacional
**URL:** https://siconfi.tesouro.gov.br/siconfi/pages/public/consulta_finbra/finbra_list.jsf
**Fields needed:** ISS arrecadado, ICMS transferido, por municipio
**Period:** 2019-2024 (needed to test the multiplier claim)

---

## Claims to Verify

### Claim 1: "21.5 million families receive BF (2024)"
- Source to check: Portal da Transparencia monthly data
- Download latest month and count distinct families

### Claim 2: "Average benefit is R$681/family"
- Source to check: Portal da Transparencia
- Calculate: sum(valor_parcela) / count(distinct familias)

### Claim 3: "Monthly program cost is R$14.2 billion"
- Source to check: Portal da Transparencia
- Calculate: sum(valor_parcela) for a recent month

### Claim 4: "~36% of population is in CadUnico"
- Source to check: CECAD dashboard
- Calculate: total_cadastrados / populacao_brasil (Censo 2022)

### Claim 5: "BF benefit went from ~R$95 (2003) to R$681 (2024)"
- Source to check: Historical MDS reports, IPEA data
- Verify each value in the timeline

### Claim 6: "Net gain from formal work is only ~R$90/month"
- Source to check: Calculate using current minimum wage, INSS rates, average transport/food costs
- Current minimum wage: verify at gov.br
- INSS discount rate: verify at receita.federal.gov.br

### Claim 7: "CAGED saldo acumulado values for 2019-2024"
- Source to check: Novo CAGED microdados
- Calculate annual net balance (admissoes - desligamentos)

### Claim 8: "Labor force participation rate data points"
- Source to check: SIDRA Table 6403 or PNAD Continua microdados
- Extract quarterly participation rates

### Claim 9: "Informality rate ~38-41%"
- Source to check: SIDRA Table 4093
- Calculate: (sem_carteira + conta_propria_sem_cnpj) / total_ocupados

### Claim 10: "228 thousand homeless in CadUnico (2023)"
- Source to check: CECAD with filter "situacao de rua"
- Cross-reference with IPEA studies on homeless population

### Claim 11: "IPEA 2008 multiplier of 1.78"
- Source to check: IPEA Nota Tecnica n.6 "Gastos Sociais: Focalizar x Universalizar"
- Verify original methodology and whether it says PIB or arrecadacao

### Claim 12: "INSS revenue vs expenditure gap"
- Source to check: RGPS annual reports from Secretaria de Previdencia
- Extract arrecadacao_liquida and despesa_beneficiarios by year

---

## Analysis Scripts to Produce

### Script 1: `verify_claims.py`
Download all datasets and verify each numerical claim above. Output a markdown table with:
| Claim | Our Value | Verified Value | Source | Status (correct/wrong/close/unverifiable) |

### Script 2: `municipal_correlation.py`
For all ~5,500 municipalities:
1. Get BF beneficiaries / population (from Portal da Transparencia + IBGE)
2. Get formal employment / PIA (from CAGED + IBGE)
3. Run OLS regression: formal_rate ~ bf_rate + controls
4. Produce scatter plot by region
5. Report coefficient and p-value

### Script 3: `event_study.py`
1. Split municipalities into high/low BF penetration (above/below median)
2. Index CAGED saldo to month -6 of March 2023
3. Plot both groups over time
4. Run DiD regression with municipality and time fixed effects

### Script 4: `multiplier_test.py`
Test if BF spending correlates with local tax revenue:
1. Get BF spending by municipality (Portal Transparencia)
2. Get ISS + ICMS revenue by municipality (SICONFI)
3. Regress: tax_revenue_pc ~ bf_spending_pc + controls
4. If beta <= 0, the multiplier doesn't generate fiscal return

### Script 5: `street_population.py`
1. Get historical homeless counts from CECAD
2. Plot against BF value changes over time
3. Correlate at municipal level if data available

---

## Output Files

After running all analyses, produce:

1. **`CORRECTIONS.md`** - What was right, what was wrong, with correct values
2. **`data/`** - All raw downloaded datasets (or scripts to download them)
3. **`analysis/`** - All Python/R scripts
4. **`results/`** - Output charts and regression tables
5. **`FINDINGS.md`** - Summary of what the data actually shows (may differ from our thesis!)

---

## Important Notes

- **Be honest.** If the data contradicts our thesis, report that. The goal is truth, not confirmation bias.
- **Use only government sources.** No blog posts, opinion articles, or secondary sources for data.
- **Document everything.** Every number should be traceable to a specific download, table, and calculation.
- **Prefer APIs when available.** Direct API calls are more reproducible than manual downloads.
- **Pin dates.** Always record the exact date you downloaded each dataset.
- **Handle IBGE municipality codes.** Use the 7-digit IBGE code as the join key across all datasets.
- **Adjust for inflation** when comparing values across years (use IPCA from IBGE SIDRA).

---

## Quick Start

```bash
# 1. Clone this repo
git clone <repo-url>
cd bolsafamiliao

# 2. Install dependencies
pip install pandas requests matplotlib statsmodels geopandas

# 3. Get your free API key
# Register at: https://portaltransparencia.gov.br/api-de-dados/registrar-email

# 4. Set your API key
export TRANSPARENCIA_API_KEY="your-key-here"

# 5. Run verification
python analysis/verify_claims.py

# 6. Run full analysis
python analysis/municipal_correlation.py
python analysis/event_study.py
python analysis/multiplier_test.py
python analysis/street_population.py
```

---

## License

All data used is public domain (Brazilian government open data).
Analysis code is MIT licensed. Use it, fork it, prove us wrong.
