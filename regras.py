"""
regras.py
---------
Motor de classificação de ativos e de apuração fiscal de renda variável (B3).

As regras abaixo seguem a legislação de renda variável da B3 e as convenções de
relatório conferidas contra os dados de referência documentados em
``ANALISE_REFERENCIA.md``:

* tabela de grupos de ativos, isenções e alíquotas (23 grupos);
* estrutura da apuração mensal (campos ``Results*``, ``BaseCalc*``, ``IRRF*``);
* totais por competência (``Results*``/``IRCalc*``/``Total*``);
* saldos de prejuízo anteriores a compensar.

Fórmulas confirmadas contra os dados de Setembro/2026:

    ResultsDayTrade    = soma dos resultados das operações day trade
    ResultsSwingTrade  = soma dos resultados das operações swing (pós-isenção)
    BaseCalcDayTrade   = ResultsDayTrade - |PreviousAcumulatedLossDayTrade|
    BaseCalcSwingTrade = ResultsSwingTrade - |PreviousAcumulatedLossSwingTrade|
    IRRFBaseDayTrade   = 0,20 * BaseCalcDayTrade
    IRRFBaseSwingTrade = 0,15 * BaseCalcSwingTrade
    IRRFBase           = IRRFBaseDayTrade + IRRFBaseSwingTrade
    IRRFFinal          = IRRFBase - IRRF retido no mês - IRRF anterior (>= 0)

O IRRF retido que excede o IR apurado não é perdido: fica acumulado para as
competências seguintes, separado por bucket (Day Trade x Swing Trade).

Uso:
    from regras import classificar_grupo, resultados_realizados, apurar_mensal
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

# ===========================================================================
# 1. Grupos de ativos e tributação
# ===========================================================================

@dataclass(frozen=True)
class GrupoFee:
    """Um grupo de ativos e suas regras de tributação."""

    grupo: str            # AssetGroup
    nome: str             # GroupName
    irrf: str             # AssetGroupIRRF (agrupamento usado no relatório)
    isento: bool          # Exemption: participa da isenção por limite de vendas
    fee_percent: float    # FeePercent: alíquota de swing trade
    isento_valor: float   # ExemptionValue: limite de vendas isentas no mês


GRUPOS_FEE: dict[str, GrupoFee] = {
    g.grupo: g
    for g in (
        GrupoFee("STOCK", "Ações", "STOCK", True, 0.15, 20000.0),
        GrupoFee("STOCK_USA", "Ações EUA", "STOCK_USA", True, 0.15, 35000.0),
        GrupoFee("BDR", "BDR", "STOCK", True, 0.15, 20000.0),
        GrupoFee("EXPENSES", "Despesas", "EXPENSES", False, 0.0, 0.0),
        GrupoFee("RIGHT", "Direito de subscrição", "STOCK", True, 0.15, 20000.0),
        GrupoFee("FUTUSD", "Dólar Futuro", "FUTUSD", False, 0.15, 0.0),
        GrupoFee("ETF", "ETF", "STOCK", False, 0.15, 0.0),
        GrupoFee("ETF_FIXEDINCOME", "ETF Renda Fixa", "ETF_FIXEDINCOME", True, 0.0, 0.0),
        GrupoFee("ETF_USA", "ETF USA", "ETF_USA", True, 0.15, 35000.0),
        GrupoFee("FIAGRO", "FI Agro", "FIAGRO", False, 0.2, 0.0),
        GrupoFee("FII", "Fundo Imobiliário", "FII", False, 0.2, 0.0),
        GrupoFee("FUNDEXEMPTION", "Fundos Isentos", "FUNDEXEMPTION", True, 0.0, 0.0),
        GrupoFee("FUTOTH", "Futuros Outros", "FUTOTH", False, 0.15, 0.0),
        GrupoFee("FUTIDX", "Índice Futuro", "FUTIDX", False, 0.15, 0.0),
        GrupoFee("FUTFEE", "Juros Futuros", "FUTFEE", False, 0.15, 0.0),
        GrupoFee("FUNDS_USA", "Mutual Funds USA", "FUNDS_USA", False, 0.0, 0.0),
        GrupoFee("OPTION", "Opções", "OPTION", False, 0.15, 0.0),
        GrupoFee("OPTION_USA", "Opções EUA", "OPTION_USA", True, 0.0, 0.0),
        GrupoFee("FLEXOPTION", "Opções Flexíveis", "FLEXOPTION", False, 0.0, 0.0),
        GrupoFee("GOLD", "Ouro na bolsa", "STOCK", True, 0.15, 20000.0),
        GrupoFee("REIT", "REIT", "REIT", True, 0.0, 0.0),
        GrupoFee("FIXED_INCOME_USA", "Renda Fixa EUA", "FIXED_INCOME_USA", False, 0.0, 0.0),
        GrupoFee("TERM", "Termo", "TERM", False, 0.0, 0.0),
    )
}

# Rótulo do resultado no relatório (campos ``Results*``)
ROTULO_MERCADO: dict[str, str] = {
    "STOCK": "Stock",
    "STOCK_USA": "Stock",
    "BDR": "Stock",
    "RIGHT": "Stock",
    "ETF": "Stock",
    "ETF_FIXEDINCOME": "Stock",
    "FUNDEXEMPTION": "Stock",
    "REIT": "Stock",
    "FUNDS_USA": "Stock",
    "FIXED_INCOME_USA": "Stock",
    "GOLD": "Gold",
    "OPTION": "Option",
    "OPTION_USA": "Option",
    "FLEXOPTION": "Option",
    "FUTIDX": "FutureIDX",
    "FUTFEE": "FutureFee",
    "FUTUSD": "FutureUSD",
    "FUTOTH": "FutureOther",
    "TERM": "Term",
    "FII": "FII",
    "FIAGRO": "FII",
    "EXPENSES": "Expenses",
}

# Alíquota de day trade (todas as categorias), conforme base observada:
#   0,20 * 241,17 + 0,15 * 1050,37 = 205,79  ->  IRRFBase de Set/2026
ALIQUOTA_DAY_TRADE = 0.20

# Código de receita do DARF para ganhos líquidos em renda variável (pessoa física)
CODIGO_RECEITA_DARF = "6015"


def aliquota(grupo: str, day_trade: bool) -> float:
    """Alíquota aplicável a um grupo de ativos em swing trade ou day trade."""
    meta = GRUPOS_FEE.get(grupo)
    if meta is None:
        return ALIQUOTA_DAY_TRADE if day_trade else 0.15
    if day_trade:
        return ALIQUOTA_DAY_TRADE
    return meta.fee_percent


def bucket_tributario(grupo: str, day_trade: bool) -> str:
    """Bucket de compensação de prejuízo: ``DayTrade``, ``SwingTrade`` ou ``FII``."""
    if day_trade:
        return "DayTrade"
    if grupo in ("FII", "FIAGRO"):
        return "FII"
    return "SwingTrade"


# ===========================================================================
# 2. Classificação do ativo em grupo
# ===========================================================================

# ETFs negociados na B3 (não têm isenção de R$ 20 mil)
ETFS_B3 = {
    "BOVA11", "BOVV11", "SMAL11", "IVVB11", "BRAX11", "XINA11", "EURP11", "ASIA11",
    "ACWI11", "SPXI11", "ISUS11", "GOVE11", "MATB11", "PIBB11", "FIND11", "DIVO11",
    "IDIV11", "NDIV11", "UTIP11", "ECOO11", "REVE11", "BOVB11", "XBOV11", "ESGB11",
    "ICHT11", "HASH11", "QBTC11", "QETH11", "BITH11", "ETHE11", "GOLD11", "BIOM11",
    "FIXA11", "IRFM11", "LFTS11", "B5P211", "IMAB11", "IB5M11", "BOVA11",
}

# FIAGRO (FII de cadeia agroindustrial) — alíquota de 20% e sem isenção
FIAGROS = {
    "FIAG11", "KNCA11", "KNCR11", "KNRI11", "CPTR11", "RZAG11", "SNAG11", "GCRA11",
    "EGAF11", "FGAA11", "IAGR11", "KCRE11", "VGIA11", "AGRX11", "RURA11", "DCRA11",
}

# Prefixo do contrato futuro -> grupo
_PREFIXO_FUTURO = {
    "WIN": "FUTIDX", "IND": "FUTIDX",
    "WDO": "FUTUSD", "DOL": "FUTUSD",
    "DI1": "FUTFEE", "DAP": "FUTFEE", "FRC": "FUTFEE", "OC1": "FUTFEE",
    "BGI": "FUTOTH", "CCM": "FUTOTH", "ICF": "FUTOTH", "SJC": "FUTOTH",
    "ETH": "FUTOTH", "BTC": "FUTOTH",
}

# Série de opção: 4 letras + letra de série + 1 a 3 dígitos (ex.: PETRI439)
_OPCAO_RE = re.compile(r"^[A-Z]{4}[A-Z]\d{1,3}$")


def classificar_grupo(ticker: str, mercado: str = "") -> str:
    """
    Classifica um ativo no seu grupo tributário (``AssetGroup``).

    A classificação usa o mercado informado pelo parser quando disponível e,
    para o mercado à vista, o sufixo numérico do ticker.
    """
    t = (ticker or "").upper().strip()
    m = (mercado or "").upper().strip()

    if m == "FUTURO":
        return _PREFIXO_FUTURO.get(t.split()[0][:3], "FUTOTH")
    if m == "OURO":
        return "GOLD"
    if m == "TERMO":
        return "TERM"
    if m == "OPCAO":
        return "OPTION"
    if _OPCAO_RE.match(t):            # série de opção sem mercado explícito
        return "OPTION"

    # Mercado à vista / fracionário
    if t.endswith("11"):
        if t in ETFS_B3:
            return "ETF"
        if t in FIAGROS:
            return "FIAGRO"
        return "FII"
    if re.fullmatch(r"[A-Z]{4}3[2-9]", t):   # BDR: 4 letras + 32..39
        return "BDR"
    return "STOCK"


# ===========================================================================
# 3. Resultados realizados
# ===========================================================================

COLUNAS_RESULTADO = [
    "data", "mes", "ticker", "grupo", "rotulo", "categoria", "bucket",
    "quantidade", "vendas", "resultado",
]

# Ordens de coluna do detalhamento por mercado (espelho de ``Results*``)
_MERCADOS = ["Stock", "Gold", "Option", "FutureIDX", "FutureFee", "Term",
             "FutureUSD", "FutureOther"]
_CATEGORIAS = ["SwingTrade", "DayTrade"]


def _linha_resultado(row, *, day_trade: bool, quantidade: float,
                     resultado: float, vendas: float) -> dict:
    grupo = row["grupo"]
    return {
        "data": row["data"],
        "mes": row["data"].strftime("%Y-%m"),
        "ticker": row["ticker"],
        "grupo": grupo,
        "rotulo": ROTULO_MERCADO.get(grupo, "Outros"),
        "categoria": "Day Trade" if day_trade else "Swing Trade",
        "bucket": bucket_tributario(grupo, day_trade),
        "quantidade": round(float(quantidade), 6),
        "vendas": round(float(vendas), 2),
        "resultado": round(float(resultado), 2),
    }


def resultados_realizados(operacoes: pd.DataFrame) -> pd.DataFrame:
    """
    Converte as operações em **resultados realizados** (eventos tributáveis).

    * Futuros e termo: o ajuste do dia é o resultado, menos as despesas da nota.
    * À vista / opções / ouro: o resultado é realizado quando a posição é
      encerrada ou reduzida — na **venda** (posição comprada) ou na **recompra**
      (posição vendida/"descoberta"), sempre contra o preço médio com as taxas
      de corretagem somadas ao custo.
    * Quantidades compradas e vendidas do mesmo ticker no mesmo dia são
      tratadas como **day trade** (quantidade casada), descontando as taxas das
      duas pernas do resultado.
    """
    if operacoes is None or operacoes.empty:
        return pd.DataFrame(columns=COLUNAS_RESULTADO)

    df = operacoes.copy()
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df = df.dropna(subset=["data"])
    if df.empty:
        return pd.DataFrame(columns=COLUNAS_RESULTADO)

    df["taxas"] = pd.to_numeric(df.get("taxas"), errors="coerce").fillna(0.0)
    df["grupo"] = [
        classificar_grupo(t, m) for t, m in zip(df["ticker"], df["mercado"])
    ]
    df = df.sort_values(["data", "tipo"]).reset_index(drop=True)  # 'C' antes de 'V'

    registros: list[dict] = []

    # --- Futuros / termo: cada ajuste já é um resultado realizado -----------
    # O ajuste da nota é bruto; as despesas da nota (corretagem, emolumentos,
    # I.S.S.) entram como custo, como nos demais mercados.
    derivativos = df["mercado"].isin(["FUTURO", "TERMO"])
    for _, row in df[derivativos].iterrows():
        if pd.isna(row.get("resultado")):
            continue
        registros.append(_linha_resultado(
            row,
            day_trade=bool(row.get("day_trade")),
            quantidade=row.get("quantidade") or 0.0,
            resultado=float(row["resultado"]) - float(row.get("taxas") or 0.0),
            vendas=0.0,
        ))

    # --- À vista / opções / ouro -------------------------------------------
    rv = df[~derivativos].copy()
    if not rv.empty:
        dias = rv["data"].dt.date

        # Quantidade casada (day trade) e totais de cada lado, por dia/ticker.
        totais: dict[tuple, dict] = {}
        for (dia, ticker), grupo_dia in rv.groupby([dias, "ticker"], sort=False):
            if ticker is None:
                continue
            qtd_c = float(grupo_dia.loc[grupo_dia["tipo"] == "C", "quantidade"].sum())
            qtd_v = float(grupo_dia.loc[grupo_dia["tipo"] == "V", "quantidade"].sum())
            if qtd_c > 0 and qtd_v > 0:
                totais[(dia, ticker)] = {
                    "C": qtd_c, "V": qtd_v, "casada": min(qtd_c, qtd_v),
                }

        # Day trade: resultado casado do dia, líquido das taxas das duas pernas.
        for (dia, ticker), tot in totais.items():
            casada = tot["casada"]
            if casada <= 0:
                continue
            grupo_dia = rv[(dias == dia) & (rv["ticker"] == ticker)]
            compras = grupo_dia[grupo_dia["tipo"] == "C"]
            vendas = grupo_dia[grupo_dia["tipo"] == "V"]
            pm_compra = (compras["quantidade"] * compras["preco"]).sum() / tot["C"]
            pm_venda = (vendas["quantidade"] * vendas["preco"]).sum() / tot["V"]
            taxas = (float(compras["taxas"].sum()) * (casada / tot["C"])
                     + float(vendas["taxas"].sum()) * (casada / tot["V"]))
            registros.append(_linha_resultado(
                grupo_dia.iloc[0], day_trade=True, quantidade=casada,
                resultado=casada * (pm_venda - pm_compra) - taxas,
                vendas=casada * pm_venda,
            ))

        # Perna "swing": o que sobra de cada operação após remover a parcela
        # casada no day trade.
        pernas: list[dict] = []
        for _, row in rv.iterrows():
            chave = (row["data"].date(), row["ticker"])
            tot = totais.get(chave)
            lado = "C" if row["tipo"] == "C" else "V"
            fator = ((tot[lado] - tot["casada"]) / tot[lado]) if tot and tot[lado] else 1.0
            qtd = float(row["quantidade"] or 0.0) * fator
            if qtd <= 0:
                continue
            pernas.append({
                "data": row["data"],
                "ticker": row["ticker"],
                "grupo": row["grupo"],
                "tipo": row["tipo"],
                "quantidade": qtd,
                "preco": float(row["preco"] or 0.0),
                "taxas": float(row["taxas"]) * fator,
            })

        # Posição comprada (qtd > 0) ou vendida (qtd < 0): o resultado é
        # realizado na operação que reduz a posição e é datado nesse dia.
        posicao: dict[str, dict] = {}
        for perna in sorted(pernas, key=lambda r: (r["data"], r["tipo"])):
            ticker = perna["ticker"]
            qtd = perna["quantidade"]
            preco = perna["preco"]
            taxas = perna["taxas"]
            reg = posicao.setdefault(ticker, {"qtd": 0.0, "custo": 0.0})

            if perna["tipo"] == "C":
                if reg["qtd"] < 0:                       # recompra (cobre a venda)
                    coberta = min(qtd, -reg["qtd"])
                    fracao = coberta / qtd
                    pm = reg["custo"] / (-reg["qtd"])    # preço médio líquido da venda
                    registros.append(_linha_resultado(
                        perna, day_trade=False, quantidade=coberta,
                        resultado=coberta * (pm - preco) - taxas * fracao,
                        vendas=coberta * pm,
                    ))
                    reg["custo"] -= coberta * pm
                    reg["qtd"] += coberta
                    qtd -= coberta
                    taxas -= taxas * fracao
                if qtd > 0:                              # compra (abre/aumenta a posição)
                    reg["custo"] += qtd * preco + taxas
                    reg["qtd"] += qtd
            else:
                if reg["qtd"] > 0:                       # venda (realiza a posição comprada)
                    vendida = min(qtd, reg["qtd"])
                    fracao = vendida / qtd
                    pm = reg["custo"] / reg["qtd"]
                    registros.append(_linha_resultado(
                        perna, day_trade=False, quantidade=vendida,
                        resultado=vendida * (preco - pm) - taxas * fracao,
                        vendas=vendida * preco,
                    ))
                    reg["custo"] -= vendida * pm
                    reg["qtd"] -= vendida
                    qtd -= vendida
                    taxas -= taxas * fracao
                if qtd > 0:                              # venda descoberta (abre/aumenta)
                    reg["custo"] += qtd * preco - taxas
                    reg["qtd"] -= qtd

    return pd.DataFrame(registros, columns=COLUNAS_RESULTADO)


# ===========================================================================
# 4. Apuração mensal (isenção + compensação de prejuízo)
# ===========================================================================

BUCKETS = ("DayTrade", "SwingTrade", "FII")

#: Bucket tributário -> chave do saldo de IRRF retido acumulado a compensar
#: (espelho de ``PreviousLoss.IRDayTrade`` / ``IRSwingTrade`` no relatório).
IRRF_POR_BUCKET = {"DayTrade": "ir_day", "SwingTrade": "ir_swing"}

SALDOS_INICIAIS_PADRAO: dict[str, float] = {
    **{b: 0.0 for b in BUCKETS},
    **{chave: 0.0 for chave in IRRF_POR_BUCKET.values()},
}

# Colunas da tabela mensal, na ordem do relatório de apuração
COLUNAS_APURACAO = (
    ["mes"]
    + [f"Results{mercado}{categoria}" for categoria in _CATEGORIAS for mercado in _MERCADOS]
    + [
        "ResultsDayTrade", "ResultsSwingTrade",
        "PreviousAcumulatedLossDayTrade", "PreviousAcumulatedLossSwingTrade",
        "BaseCalcDayTrade", "BaseCalcSwingTrade",
        "IRRFBaseDayTrade", "IRRFBaseSwingTrade", "IRRFBase",
        "IRRFMonthlyDayTrade", "IRRFPreviousDayTrade",
        "IRRFUsedDayTrade", "IRRFNextMonthDayTrade",
        "IRRFMonthlySwingTrade", "IRRFPreviousSwingTrade",
        "IRRFUsedSwingTrade", "IRRFNextMonthSwingTrade",
        "ResultsFII", "PreviousAcumulatedLossFII", "BaseCalcFII",
        "IRRFBaseFII", "IRRFMonthlyFII",
        "IRRFFinal", "DARFFinal", "ExemptionMessage",
    ]
)


def _irrf_retido_mes(notas: pd.DataFrame | None, mes: str) -> dict[str, float]:
    """IRRF retido no mês, separado entre day trade e swing trade."""
    retido = {"DayTrade": 0.0, "SwingTrade": 0.0}
    if notas is None or notas.empty:
        return retido

    notas = notas.copy()
    notas["data"] = pd.to_datetime(notas["data"], errors="coerce")
    do_mes = notas[notas["data"].dt.strftime("%Y-%m") == mes]

    # uma nota pode aparecer em mais de um arquivo: conta-se uma única vez
    do_mes = do_mes.drop_duplicates(subset=["corretora", "numero"])
    for categoria, grupo in do_mes.groupby("categoria_irrf"):
        if categoria in retido:
            retido[categoria] += float(grupo["irrf"].sum())
    return retido


def apurar_mensal(resultados: pd.DataFrame,
                  notas: pd.DataFrame | None = None,
                  saldos_iniciais: dict[str, float] | None = None
                  ) -> tuple[pd.DataFrame, dict[str, float]]:
    """
    Apura o IR mês a mês, aplicando isenção e compensação de prejuízo.

    Parâmetros
    ----------
    resultados : saída de :func:`resultados_realizados`.
    notas : DataFrame com ``numero``, ``corretora``, ``data``, ``irrf`` e
        ``categoria_irrf`` ("DayTrade"/"SwingTrade") — usado no IRRF retido.
    saldos_iniciais : saldo de prejuízo a compensar por bucket
        (``DayTrade``, ``SwingTrade``, ``FII``; valores negativos = prejuízo) e
        IRRF retido acumulado de meses anteriores (``ir_day``, ``ir_swing``).

    Retorna
    -------
    (tabela_mensal, saldos_finais), com ``saldos_finais`` já contendo o prejuízo
    e o IRRF que passam para o mês seguinte.
    """
    saldos = dict(SALDOS_INICIAIS_PADRAO)
    if saldos_iniciais:
        for bucket, valor in saldos_iniciais.items():
            if bucket in saldos:
                saldos[bucket] = float(valor or 0.0)

    if resultados is None or resultados.empty:
        return pd.DataFrame(columns=COLUNAS_APURACAO), saldos

    linhas: list[dict] = []

    for mes in sorted(resultados["mes"].unique()):
        mes_res = resultados[resultados["mes"] == mes].copy()

        # --- isenção: vendas do mês <= limite do grupo ---------------------
        isento = pd.Series(False, index=mes_res.index)
        for grupo, g in mes_res[mes_res["categoria"] == "Swing Trade"].groupby("grupo"):
            meta = GRUPOS_FEE.get(grupo)
            if meta and meta.isento and meta.isento_valor > 0:
                if g["vendas"].sum() <= meta.isento_valor:
                    isento.loc[g.index] = True
        tributavel = mes_res[~isento]

        retido = _irrf_retido_mes(notas, mes)

        linha: dict = {"mes": mes}

        # detalhamento por mercado (pós-isenção, pré-compensação)
        agregado = tributavel.groupby(["rotulo", "categoria"])["resultado"].sum()
        for (mercado, categoria_res), valor in agregado.items():
            sufixo = "DayTrade" if categoria_res == "Day Trade" else "SwingTrade"
            linha[f"Results{mercado}{sufixo}"] = round(float(valor), 2)

        ir_total = 0.0
        ir_devido = 0.0
        for bucket in BUCKETS:
            grupo_bucket = tributavel[tributavel["bucket"] == bucket]
            resultado_bucket = float(grupo_bucket["resultado"].sum())

            anterior = saldos.get(bucket, 0.0)
            base = resultado_bucket + anterior
            saldos[bucket] = min(base, 0.0)

            if base > 0 and resultado_bucket > 0:
                # alíquotas podem variar dentro do bucket (ex.: STOCK 15% x ETF_FIXEDINCOME 0%)
                irr = sum(
                    (float(g["resultado"].sum()) / resultado_bucket)
                    * base
                    * aliquota(gr, bucket == "DayTrade")
                    for gr, g in grupo_bucket.groupby("grupo")
                )
            else:
                irr = 0.0

            # IRRF retido: o do próprio mês e o acumulado de meses anteriores
            # abatem o IR apurado; o que sobra fica para o mês seguinte em vez
            # de se perder (é a "compensação" do IRRF entre competências).
            chave_irrf = IRRF_POR_BUCKET.get(bucket)
            retido_mes = float(retido.get(bucket, 0.0))
            if chave_irrf:
                retido_anterior = saldos.get(chave_irrf, 0.0)
                usado_anterior = min(retido_anterior, max(irr - retido_mes, 0.0))
                devido = max(irr - retido_mes - retido_anterior, 0.0)
                saldos[chave_irrf] = round(
                    retido_anterior - usado_anterior + max(retido_mes - irr, 0.0), 2
                )
                proximo_irrf = saldos[chave_irrf]
            else:
                retido_anterior = usado_anterior = 0.0
                proximo_irrf = 0.0
                devido = irr

            if bucket == "DayTrade":
                linha["ResultsDayTrade"] = round(resultado_bucket, 2)
                linha["PreviousAcumulatedLossDayTrade"] = round(anterior, 2)
                linha["BaseCalcDayTrade"] = round(base, 2)
                linha["IRRFBaseDayTrade"] = round(irr, 2)
                linha["IRRFMonthlyDayTrade"] = round(retido_mes, 2)
                linha["IRRFPreviousDayTrade"] = round(retido_anterior, 2)
                linha["IRRFUsedDayTrade"] = round(usado_anterior, 2)
                linha["IRRFNextMonthDayTrade"] = round(proximo_irrf, 2)
            elif bucket == "SwingTrade":
                linha["ResultsSwingTrade"] = round(resultado_bucket, 2)
                linha["PreviousAcumulatedLossSwingTrade"] = round(anterior, 2)
                linha["BaseCalcSwingTrade"] = round(base, 2)
                linha["IRRFBaseSwingTrade"] = round(irr, 2)
                linha["IRRFMonthlySwingTrade"] = round(retido_mes, 2)
                linha["IRRFPreviousSwingTrade"] = round(retido_anterior, 2)
                linha["IRRFUsedSwingTrade"] = round(usado_anterior, 2)
                linha["IRRFNextMonthSwingTrade"] = round(proximo_irrf, 2)
            else:  # FII
                linha["ResultsFII"] = round(resultado_bucket, 2)
                linha["PreviousAcumulatedLossFII"] = round(anterior, 2)
                linha["BaseCalcFII"] = round(base, 2)
                linha["IRRFBaseFII"] = round(irr, 2)
                linha["IRRFMonthlyFII"] = round(retido.get("FII", 0.0), 2)

            ir_total += irr
            ir_devido += devido

        linha["IRRFBase"] = round(ir_total, 2)
        linha["IRRFFinal"] = round(ir_devido, 2)
        linha["DARFFinal"] = round(ir_devido, 2)
        linha["ExemptionMessage"] = "DARF a pagar" if ir_devido > 0 else "Isento"
        linhas.append(linha)

    tabela = pd.DataFrame(linhas)
    for coluna in COLUNAS_APURACAO:
        if coluna not in tabela.columns:
            tabela[coluna] = 0.0
    return tabela[COLUNAS_APURACAO].fillna(0.0), saldos


# ===========================================================================
# 5. Carteira (posição em custódia)
# ===========================================================================

def posicao_atual(operacoes: pd.DataFrame) -> pd.DataFrame:
    """
    Posição em custódia por ticker, com preço médio ponderado.

    As taxas de corretagem das compras entram no custo (item 3 do checklist).
    """
    if operacoes is None or operacoes.empty:
        return pd.DataFrame(columns=["Ticker", "Grupo", "Quantidade", "Preço Médio", "Custo Total"])

    df = operacoes.copy()
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df = df.dropna(subset=["data"]).sort_values(["data", "tipo"])
    df["grupo"] = [classificar_grupo(t, m) for t, m in zip(df["ticker"], df["mercado"])]

    posicao: dict[str, dict] = {}
    for _, row in df.iterrows():
        if row["mercado"] in ("FUTURO", "TERMO"):
            continue                      # derivativos não geram custódia
        ticker = row["ticker"]
        qtd = float(row["quantidade"] or 0.0)
        preco = float(row["preco"] or 0.0)
        taxas = float(row.get("taxas") or 0.0)
        reg = posicao.setdefault(ticker, {"qtd": 0.0, "custo": 0.0, "grupo": row["grupo"]})

        if row["tipo"] == "C":
            reg["qtd"] += qtd
            reg["custo"] += qtd * preco + taxas
        else:
            pm = reg["custo"] / reg["qtd"] if reg["qtd"] > 0 else 0.0
            baixa = min(qtd, reg["qtd"])
            reg["custo"] -= baixa * pm
            reg["qtd"] -= qtd

    linhas = []
    for ticker, reg in posicao.items():
        if reg["qtd"] <= 1e-9:
            continue
        pm = reg["custo"] / reg["qtd"] if reg["qtd"] else 0.0
        linhas.append({
            "Ticker": ticker,
            "Grupo": reg["grupo"],
            "Quantidade": round(reg["qtd"], 4),
            "Preço Médio": round(pm, 2),
            "Custo Total": round(reg["custo"], 2),
        })
    return pd.DataFrame(linhas).sort_values("Ticker").reset_index(drop=True)


__all__ = [
    "GRUPOS_FEE", "GrupoFee", "ROTULO_MERCADO", "ALIQUOTA_DAY_TRADE",
    "CODIGO_RECEITA_DARF", "BUCKETS", "IRRF_POR_BUCKET", "SALDOS_INICIAIS_PADRAO",
    "COLUNAS_APURACAO", "COLUNAS_RESULTADO",
    "aliquota", "bucket_tributario", "classificar_grupo",
    "resultados_realizados", "apurar_mensal", "posicao_atual",
]
