# Changelog

Todas as alterações relevantes deste projeto são registradas neste arquivo.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [Não publicado]

### Adicionado — Motor fiscal (`regras.py`)
- Tabela `GRUPOS_FEE` com 23 grupos de ativos,
  com `AssetGroupIRRF`, `Exemption`, `ExemptionValue` e `FeePercent`.
- `classificar_grupo(ticker, mercado)`: classifica o ativo em Stock, FII, ETF, BDR,
  Option, Gold, FutureIDX/FutureUSD/FutureFee/FutureOther, Term, FIAGRO e afins.
- `resultados_realizados(operacoes)`: apuração do resultado por operação, com
  preço médio ponderado (taxas somadas ao custo) e separação de Day Trade
  (casamento de compra e venda no mesmo dia).
- `apurar_mensal(resultados, notas, saldos_iniciais)`: tabela mensal de apuração com
  isenção por limite de vendas, alíquotas por bucket (Day Trade 20%, Swing Trade 15%,
  FII 20%), compensação de prejuízo entre meses e **compensação do IRRF retido**,
  com transporte do IRRF não utilizado para as competências seguintes
  (`IRRFPrevious*`, `IRRFUsed*`, `IRRFNextMonth*`, separados por Day Trade e
  Swing Trade).
- `posicao_atual(operacoes)`: posição em custódia com quantidade e preço médio.

### Adicionado — Persistência (`persistencia.py`)
- Camada SQLite (`dados.db`) com 4 tabelas: `notas`, `operacoes`,
  `prejuizos_anteriores` e `proventos`.
- **Deduplicação**: `notas` tem `UNIQUE(corretora, numero)` e `operacoes` usa hash
  único; reimportar PDFs sobrepostos não duplica registros.
- `salvar_notas`, `carregar_operacoes`, `carregar_notas`, `resumo_importacao`,
  `ler_prejuizos`, `gravar_prejuizos`, `carregar_proventos`, `adicionar_provento`,
  `remover_provento` e `limpar_dados`.
- Saldo de **IRRF a compensar** (`ir_day`, `ir_swing`) lido e gravado junto com os
  saldos de prejuízo.

### Adicionado — Interface (`app.py` v3)
- Reescrita com **8 abas**: Upload de Notas, Visão Geral, Extrato, Meu Patrimônio,
  Apuração de IR, DARF, Proventos e Relatórios.
- Aba **Apuração de IR** com edição dos saldos iniciais de prejuízo **e de IRRF**
  por bucket, transporte calculado para o mês seguinte e detalhamento por
  mercado/categoria (campos `Results*`).
- Aba **DARF** com competência, composição, dados para o Sicalc, código de receita
  `6015` e vencimento calculado no último dia útil do mês seguinte.

### Adicionado — Validação (`validar.py`)
- Suíte sem dependência de pytest, executável com `python validar.py` (exit code 0/1).
- Cobre: classificação de ativos, reconciliação com os dados de referência (Set/2026),
  isenção, compensação entre meses, compensação de IRRF entre meses, deduplicação
  com os 4 PDFs reais e a reconciliação dos futuros (teste 7, `ajuste do dia −
  despesas da nota`).
- Resultado atual: **todas as verificações passam** (`EXIT=0`), incluindo
  `IRRFFinal = 192,65` e `IRRFBase = 205,79` idênticos aos dados de referência.

### Alterado
- `README.md` reescrito: 8 abas, arquitetura, regras fiscais, validação e deploy.
- `.gitignore`: passou a ignorar `*.db`, `*.db-journal`, `*.sqlite*` e `_tmp_notas/`.
- `app.py`: removida a dívida técnica `__import__("regras")` — `classificar_grupo`
  agora é importada no topo do módulo.

### Removido
- Ferramenta interna de mapeamento de telas e API retirada do projeto; as capturas
  locais foram renomeadas para `ref_exemplo/` e `ANALISE_REFERENCIA.md`,
  mantendo-se fora do versionamento.
- Menções ao sistema de referência eliminadas de `README.md`, `CHANGELOG.md`,
  `app.py`, `persistencia.py`, `regras.py` e `validar.py`.

### Corrigido
- `validar.py` retornava exit code 1 no Windows por não fechar a conexão SQLite antes
  da remoção do diretório temporário — corrigido com `conexao.close()`.
- **Futuros não descontavam as despesas** (`regras.py`): o resultado realizado usava o
  ajuste **bruto** da nota. Agora o ajuste entra líquido de corretagem/emolumentos,
  como nos demais mercados. `WDO V26`: -50,00 → **-50,57**.
- **I.S.S. ficava fora do "Total das despesas"** da nota BM&F (`parser.py`): o valor
  impresso não inclui o I.S.S., que é somado agora em `_extrair_despesas`. Nota
  122982 (09/09/2026): despesas 27,36 → **28,58**. Era o resíduo de R$ 1,19 que
  impedia o fechamento da reconciliação.
- Resultado: os futuros de Set/2026 passaram a bater com os dados de referência **dia
  a dia** — `WIN V26` 384,84 × 384,87 e `WDO V26` exato.
- **IRRF retido era descartado** (`regras.py`): `IRRFFinal = max(IR − IRRF do mês, 0)`
  jogava fora o IRRF que excedia o IR apurado, e o saldo de IRRF de meses anteriores
  (`ir_day`/`ir_swing`, já existente no banco) nunca era usado. Agora o IRRF é
  compensado por bucket e o excedente é transportado para as competências seguintes.
  Com os dados reais, o IRRF de R$ 0,16 de Swing Trade (mês sem IR a pagar por esse
  bucket) passou a aparecer em vez de ser perdido.

## Base
- Projeto construído a partir do mapeamento de **27 telas** de um sistema de
  referência (pasta `ref_exemplo/`) e das regras documentadas em
  `ANALISE_REFERENCIA.md`.
