# Relatório de Compatibilidade — Parser de Notas de Corretagem

**Projeto:** FiscoTrade
**Data:** 19/10/2026
**Escopo:** verificar se a extração de notas de corretagem (baseada na estrutura
observada na plataforma de referência **MyProfit** e implementada em
[parser.py](file:///C:/Users/Esquilo/Documents/Trae/default/parser.py)) é
compatível com notas de corretoras **além da Genial** — com foco na **XP**, que
já havia falhado em teste anterior.

**Ferramenta de teste:** [compatibilidade_notas.py](file:///C:/Users/Esquilo/Documents/Trae/default/compatibilidade_notas.py)
(sintético, sem dados pessoais). Execução: `python compatibilidade_notas.py`.

---

## 1. Mapeamento do que é extraído hoje

### 1.1 Campos por operação (dataclass `Operacao`)

| Campo | Origem na nota | Como é obtido | Observação |
|---|---|---|---|
| `data` | Data do pregão do **bloco** | `NOTA_HEADER_RE` ou 1ª data do PDF | definida por nota, não por linha |
| `tipo` | coluna **C/V** | capturável nos 3 layouts | "C"=compra, "V"=venda |
| `ticker` | Especificação do título / código | `TICKER_RE = [A-Z]{4}(\d{1,2}[A-Z]?\|[A-Z]\d{1,3})` | **exige código de negociação** (PETR4, MXRF11, PETRI439) |
| `quantidade` | Quantidade | grupo `qtd` | |
| `preco` | Preço/Ajuste | grupo `preco` (`[\d.]+,\d+`) | |
| `valor_total` | Valor/Ajuste | grupo `valor`/`ajuste` | BR = qtd×preço; futuro = \|ajuste\| |
| `mercado` | Tipo mercado | `_detect_mercado` (`MERCADOS`) | VISTA, FRACIONARIO, OPCAO, OURO, TERMO, FUTURO, BALCAO, BM |
| `corretora` | parâmetro do upload | rótulo | |
| `arquivo` / `nota` | metadado | nome do arquivo / `Nr. nota` | |
| `day_trade` | Obs. ("D") / futuros | marcado na apuração | |
| `taxas` | rateio das despesas da nota | `_ratear_despesas` por peso do valor | |
| `irrf` | IRRF da nota | `_extrair_irrf` | |
| `resultado` | ajuste do futuro | só no layout BM&F | |
| `obs` | linha crua | head/meio | |

### 1.2 Campos por nota (dataclass `Nota`)

`numero` (Nr. nota), `data` (data do pregão do bloco), `corretora`, `arquivo`,
`despesas` (total de custos), `irrf`, `operacoes`.

### 1.3 Âncoras/regex do parser e se são Genial-específicas

| Âncora | Regex | Genial-específica? |
|---|---|---|
| Cabeçalho | `Nr\.?\s*nota\s+Folha\s+Data\s*preg[ãa]o\s+(\d+)\s+\d+\s+(\d{2}/\d{2}/\d{4})` | **Não** (SINACOR também usa) |
| Linha BM&F | `^[CV] (MERC) (VENC) (data) qtd preço obs ajuste D/C taxa$` | **Sim** |
| Linha B3 RV | `^B3\s+[A-Z]{2}\s+LISTADO[CV] .* qtd preço valor D/C$` | **Sim** |
| Linha genérica | `^\s*(\d*)\s*([CV])\s+(meio)(ticker)\s+qtd preço total` | Não (mas incompleta) |
| Despesas BM&F | literal `Total das despesas` | **Sim** |
| Despesas B3 RV | literal `Total corretagem / Despesas` + `Taxa de liquidação/CCP` + `Taxa de Registro` + `Emolumentos` | **Sim** |
| IRRF B3 | `I.R.R.F s/ opera[çc][õo]es, base ... <valor>` | Não (SINACOR também usa) |
| IRRF BM&F | `IRRF Day Trade ( Projeção )` | **Sim** |

### 1.4 Entidades do MyProfit que informaram o modelo fiscal

Coletadas do mapeamento passivo da plataforma (`ANALISE_REFERENCIA.md`, não versionado):

| Endpoint | O que fornece |
|---|---|
| `GET /API/Exchanges` | 285 corretoras (`ExchangeName`, `CNPJ`, `Category`, `Currency`) |
| `GET /API/GroupsFee` | grupos fiscais: `AssetGroup`, `Exemption`, `FeePercent` (**0,15**), `ExemptionValue` (**20.000**) |
| `GET /API/Results` | resultados por operação: `Date`, `Ticker`, `Asset.AssetGroup` (OPTION/STOCK…), `Asset.Exemption`, `DayTrade` |
| `GET /API/Stock` | posição/preço médio: `Ticker`, `TickerRef`, `TotalBuy/Sell`, `PriceBuy/Sell` |
| `GET /API/MonthlyIRRF` | IRRF por mês/categoria (`IRRFBaseDayTrade`, `IRRFBaseSwingTrade`) |
| `GET /API/DARF` / `POST /API/DARF` | geração de guia |

**Conclusão do mapeamento:** o *modelo de dados* (ticker, grupo do ativo, isenção,
alíquota, day trade, IRRF) é **agnóstico de corretora** e cobre o necessário. O que
está amarrado à Genial é a **camada de parsing do texto do PDF** (âncoras literais
e regex de linha), não o modelo fiscal.

---

## 2. Modelos de notas coletados

Pesquisa web (XP/HUB, Monte Bravo, Clear, Rico, Santander, BTG, manual XP de
nota para swing trade) e o exemplo público de extração de nota da **Clear**.
Todos os grandes brokers BR usam o **padrão SINACOR/B3** (três blocos:
*negócios realizados*, *resumo dos negócios*, *resumo financeiro*) — a diferença
está em rótulos e na coluna `Q`.

| # | Corretora | Layout | Particularidades relevantes ao parser |
|---|---|---|---|
| 1 | **XP Investimentos** | SINACOR | coluna `Q` = **`1-BOVESPA`** + `C/V`; `Obs` com `D` (day trade); resumo financeiro com `Clearing`, `Corretagem`, `ISS ( SÃO PAULO )`, `I.R.R.F s/ operações, base R$ ...`, `Total custos/despesas` |
| 2 | **Clear** | SINACOR (mesmo grupo XP) | `Q`=`1-BOVESPA`; mercado `FRACIONARIO`; título pode trazer só o **nome da empresa** sem código; resumo com `Total Custos Operacionais` |
| 3 | **Rico** | SINACOR (mesmo grupo XP) | idem XP |
| 4 | **BTG Pactual** | SINACOR | idem, rótulo `Total Custos`; opções em `OPCAO DE COMPRA` |
| 5 | *Genial (controle)* | **próprio** | `B3 RV LISTADO[CV] ...` e `C WIN V26 ...` |

> As amostras usadas nos testes são **sintéticas** (tickers públicos e números
> inventados), fiéis ao layout documentado, para não expor dados de notas reais.

---

## 3. Metodologia

`compatibilidade_notas.py` injeta o texto sintético de cada corretora no pipeline
real (`parser.extract_notas`, com `extract_text` substituído) e mede: notas
reconhecidas, operações extraídas × esperadas, despesas, IRRF e âncoras
presentes/ausentes.

---

## 4. Resultados dos testes

| Corretora | Notas | Operações (esp.) | Despesas | IRRF | Status |
|---|---|---|---|---|---|
| Genial B3 RV (controle) | 1 | 2 (2) | 11,16 | 0,01 | **OK** |
| Genial BM&F (controle) | 1 | 2 (2) | 1,22 | 0,00 | **OK** |
| **XP** | 0 | **0 (2)** | 0,00 | 0,00 | **FALHA** |
| **Clear** | 0 | **0 (2)** | 0,00 | 0,00 | **FALHA** |
| **Rico** | 0 | **0 (2)** | 0,00 | 0,00 | **FALHA** |
| **BTG Pactual** | 0 | **0 (1)** | 0,00 | 0,00 | **FALHA** |

**Resultado: 2/6 compatíveis; 4 falhas.** Todas as corretoras SINACOR (XP, Clear,
Rico, BTG) falham — e falham de forma **silenciosa**: a nota é descartada sem erro
(o `extract_notas` faz `if not operacoes: continue`), o que explica o sintoma
"XP não funciona e não diz o porquê".

---

## 5. Falhas identificadas

### F1 (crítica) — prefixo `1-BOVESPA` quebra o regex genérico
Evidência com a linha XP real (sintética):

```
1-BOVESPA   C    VISTA   PETROLEO BRASILEIRO S/A - PETROBRAS   PETR4   100   28,50   2.850,00   D
```

`OP_RE` começa em `^\s*(?P<num>\d*)\s*(?P<cv>[CV])`:
- `\d*` casa `"1"`, em seguida `[CV]` tenta casar `"-"` → **falha**;
- backtrack `num=""`, `[CV]` tenta casar `"1"` → **falha**.

`OP_RE.match(linha) → False`; `_parse_futuro`, `_parse_genial_b3` e
`_parse_generico` retornam todos `None` → **0 operações**. A coluna `Q` (ambiente
de negociação `1-BOVESPA`) é um campo fixo do padrão SINACOR/B3 que o parser não
prevê.

### F2 (crítica) — despesas só existem nos rótulos da Genial
`_extrair_despesas` só reconhece `Total das despesas` (BM&F) ou
`Total corretagem / Despesas` (Genial B3 RV). Nas notas SINACOR esses textos não
existem; os custos aparecem como `Clearing`, `Corretagem`, `Taxa de liquidação`,
`Emolumentos`, `ISS`, `Total custos/despesas`/`Total Custos Operacionais`.
Resultado: `_extrair_despesas(texto_xp) → 0.0`. **Todo o custo da operação é
perdido**, o que distorce preço médio e IR (as taxas deixam de compor a base).

### F3 (média) — IRRF é extraído, mas descartado junto com a nota
`_extrair_irrf(texto_xp) → 0,31` (a âncora `I.R.R.F s/ operações, base R$...`
casa bem). Porém, como não há operações (F1), a nota inteira é descartada e o
IRRF retido **não é aproveitado** na apuração.

### F4 (média) — dependência do código do ativo (`ticker`)
`TICKER_RE` exige `[A-Z]{4}(\d{1,2}[A-Z]?|[A-Z]\d{1,3})`. Notas que exibem apenas
o **nome da empresa** na "Especificação do título" (caso documentado da Clear:
*"ENGIE BRASILON NM"*), sem o código, não geram ticker. Também não há mapeamento
`nome → ticker` para recuperar o ativo.

### F5 (baixa) — divergências de rótulo entre corretoras
Mesmo entre GENIAL, o parser depende de strings literais com acentuação e
espaçamento exatos (`Taxa de liquidação/CCP`, `ISS ( SÃO PAULO )`,
`Total corretagem / Despesas`). Qualquer variação de rótulo (ex.: `Total Custos`,
`Total Custos Operacionais`) invalida a extração — confirmado por F2.

---

## 6. Sugestões de ajustes

### A1 — Tornar o regex genérico tolerante ao `Q` do SINACOR (corrige F1)
Prefixar `OP_RE` com um grupo opcional que consome o ambiente de negociação:

```python
OP_RE = re.compile(
    r"^\s*(?:\d+\s*-\s*[A-Z&]+\s+)?"        # NOVO: "1-BOVESPA ", "1-BM&F "
    r"(?P<num>\d*)\s*(?P<cv>[CV])\s+"
    r"(?P<meio>.*?)"
    r"(?P<ticker>[A-Z]{4}\d{1,2}[A-Z]?)\s+"
    r"(?P<qtd>[\d.]+)\s+"
    r"(?P<preco>[\d.]+,\d{2})\s+"
    r"(?P<total>[\d.]+,\d{2})"
)
```

Verificado: com o prefixo opcional, a linha XP passa a casar e produz
`tipo=C, ticker=PETR4, qtd=100, preco=28.5, total=2850.0`.

### A2 — Extrair despesas por rótulos genéricos (corrige F2/F5)
Generalizar a busca: casar `Total\s+(custos|corretagem|despesas)[^\n]*` e
somar, quando presentes, `Clearing`, `Corretagem`, `Taxa de liquidação`,
`Taxa de registro`, `Emolumentos`, `ISS`. Manter a regra atual da Genial como
caso particular e usar o total genérico como *fallback* quando o literal Genial
não existir.

### A3 — Não descartar a nota quando só o IRRF for reconhecido (corrige F3)
Trocar o `if not operacoes: continue` por um registro do bloco mesmo sem
operações, ou (preferível) garantir A1 para que as operações sejam lidas. Assim o
IRRF retido (`0,005%` swing / `1%` day trade) entra na compensação.

### A4 — Tornar o ticker opcional + mapa nome → ticker (corrige F4)
Se `TICKER_RE` não achar o código, tentar extrair o ativo pelo *nome* e resolver
por um dicionário `nome → ticker` (ou deixar o usuário associar no upload).
Alternativa robusta: usar `páginas.py`/persistência para permitir mapeamento
manual quando o ticker não for inferível.

### A5 — Centralizar as âncoras em um dicionário por corretora
Substituir os literais espalhados por uma tabela `layout = {"Genial": {...}, "XP": {...}, "SINACOR": {...}}`,
reduzindo o acoplamento a acentuação/espaçamento (corrige F5) e facilitando
adicionar novas corretoras sem tocar no núcleo do parser.

### A6 — Cobrir sinônimos de mercado
Além de `VISTA/FRACIONARIO/OPCAO/TERMO/OURO/FUTURO`, aceitar
`OPCAO DE COMPRA`/`OPCAO DE VENDA`, `A VISTA`, `A TERMO`, `EXERCICIO DE OPCAO`.

---

## 7. Resumo executivo

- O **modelo fiscal** herdado do MyProfit (ticker, grupo, isenção R$20k, day
  trade, IRRF, DARF) é **agnóstico de corretora** e suficiente.
- O gargalo é exclusivamente o **parsing do texto do PDF**, hoje preso às
  âncoras literais e à estrutura de linha da **Genial**.
- A **XP (e Clear/Rico/BTG, todas SINACOR)** falha por **um** motivo principal e
  determinístico: o regex genérico não prevê a coluna `Q` = `1-BOVESPA` (F1),
  agravado pela ausência de âncoras de despesa genéricas (F2).
- Com os ajustes **A1 + A2** (tolerância ao `1-BOVESPA` e despesas por rótulos
  genéricos) a expectativa é destravar toda a família SINACOR, que é a base
  comum de XP, Clear, Rico, BTG, Santander, Monte Bravo e demais.
- Recomenda-se reexecutar `compatibilidade_notas.py` após cada ajuste; o
  resultado esperado é **6/6** casos compatíveis.
