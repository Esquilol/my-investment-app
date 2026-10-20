# Changelog

Todas as alterações relevantes deste projeto são registradas neste arquivo.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [Não publicado]

### Alterado — Nome do aplicativo: FiscoTrade
- O app passou a se chamar **FiscoTrade** em todos os pontos visíveis: título da
  página (`page_title`), cabeçalho da tela de acesso, título da barra lateral,
  marca da landing (`landing.MARCA`), saudação da página de upload, `README.md`
  e o cabeçalho do `validar.py`.

### Corrigido — Acesso do administrador
- O seed do administrador em `persistencia._semear` ficou **idempotente**: a
  linha é inserida com `INSERT OR IGNORE` sempre que os segredos existem, e não
  mais apenas quando o banco não tinha nenhum administrador. Assim o admin é
  criado mesmo em bancos que já tinham outros usuários (caso típico depois de
  habilitar os segredos depois do primeiro deploy).
- Documentado que, **sem os segredos `[admin]` configurados**, nenhum
  administrador é criado: localmente o arquivo `.streamlit/secrets.toml` (fora
  do versionamento) e, no Streamlit Cloud, *App settings → Secrets* precisam
  conter `usuario`, `email` e `senha`. Como o banco SQLite é recriado a cada
  reinício da nuvem, o admin é semeado de novo automaticamente a cada boot —
  desde que os segredos estejam presentes.

### Adicionado — Landing pública e login habilitado
- **`landing.py`** (novo): página pública mostrada antes do login, com as seções
  **Início** (destaque e o que o app faz), **Planos** e **Dúvidas**, mais os
  atalhos **Criar conta** e **Acessar minha conta**. O texto descreve apenas o
  que o app entrega — sem métricas de audiência inventadas nem referência a
  serviços de terceiros — e os planos são lidos do banco (tabela `planos`), o
  mesmo que o checkout usa.
- A tela de acesso ganhou o botão **Voltar** (volta à landing) e a seleção de
  modo passou a ser por opção — assim os atalhos da landing abrem direto em
  **Entrar** ou **Criar conta**.

### Alterado — Fim do modo de teste
- O `MODO_TESTE` foi removido: o app agora **exige login** em todas as execuções.
  A navegação só é montada depois da autenticação, e o botão **Sair** limpa a
  sessão e devolve o usuário à landing.
- **Credenciais do administrador saíram do código**: usuário, e-mail e senha vêm
  todos de `st.secrets["admin"]` (localmente em `.streamlit/secrets.toml`, fora
  do versionamento; no Streamlit Cloud, em *App settings → Secrets*). O admin é
  criado apenas se ainda não existir nenhum administrador — e, sem os segredos,
  o app sobe sem usuário administrativo.
- O teste 9 de `validar.py` deixou de citar a senha literal: ele usa os valores
  dos segredos e, quando eles não estão presentes, apenas confirma que nenhum
  admin foi semeado.

### Adicionado — Parâmetros fiscais editáveis e monitor de legislação
- **Tabela de cálculo no painel administrativo**: nova página **Parâmetros fiscais**
  permite editar as alíquotas (day trade, swing trade, FII/FIAGRO), as isenções
  (ações/BDR/ouro e ativos dos EUA), os meses até o vencimento e o código de receita
  do DARF. O motor lê os valores vigentes em `regras.PARAMETROS`, então a mudança
  recai imediatamente sobre as telas de IR e DARF — sem reenviar as notas.
- **`regras.py`**: `PARAMETROS_FISCAIS` (chave, rótulo, tipo, descrição e padrão),
  `PARAMETROS_PADRAO`, `aplicar_parametros` (ignora chave/valor inválido, para que um
  parâmetro corrompido nunca derrube a apuração), `aliquota`, `limite_isencao`,
  `codigo_receita_darf` e `meses_ate_vencimento`.
- **`monitor.py`** (novo): acompanha quatro fontes oficiais (Lei 15.270/2025,
  Lei 11.033/2004, Lei 8.668/1993 e IN RFB 1.585/2015) e guarda um **hash SHA-256**
  do conteúdo. O botão **Buscar mudanças**, no painel admin, baixa as páginas de novo
  e avisa quando o texto mudou — o gatilho para revisar a tabela de cálculo.
  Sem API paga: usa apenas `urllib`.
- **`persistencia.py`**: esquema **v4** com as tabelas `parametros_fiscais` e
  `monitor_legislacao`; `carregar_parametros_fiscais`, `gravar_parametros_fiscais`,
  `carregar_monitor_legislacao` e `gravar_monitor_legislacao`. O `garantir_esquema`
  aplica as tabelas novas automaticamente no deploy.
- O painel exibe a **última verificação** de cada fonte, a situação (alterada /
  sem mudança / não verificada) e um aviso quando a última busca passou de 30 dias.

### Alterado — Moeda brasileira nas tabelas
- As tabelas de **Apuração de IR**, **DARF** (Competências e Composição), **Extrato** e
  **Meu Patrimônio** passaram a exibir valores em reais no padrão brasileiro
  (`R$ 1.234,56`), eliminando os artefatos de ponto flutuante (ex.:
  `1291.5300000000002`). Zero vira `—`, o que tira as fileiras de `0,00` da leitura.
- Colunas zeradas em todas as competências são **descartadas** no resumo de IR e na
  tabela de resultados por mercado; esta última ganhou rótulos legíveis (ex.: "Ações
  (ST)").

### Adicionado — SaaS: contas, planos e painel administrativo
- **App multiusuário**: cada pessoa cria a própria conta, entra no plano **Gratuito**
  e pode assinar o **PRO**. Há ainda um **painel administrativo** restrito.
- **Planos** (`PLANOS_PADRAO`): **Gratuito** (até 20 notas importadas, sem exportação
  em Excel) e **PRO** (R$ 29,90/mês, notas ilimitadas, exportação em Excel). O
  cadastro entra sempre no Gratuito.
- **`saas.py`** (novo) — regras do SaaS: `plano_do_usuario`, `eh_pro`, `rotulo_plano`,
  `limite_notas`, `pode_importar`, `pode_exportar_excel`, `validar_cupom`,
  `calcular_preco`, `assinar` (gera **pagamento** e **nota fiscal**
  `NF-AAAAMM-00001`), `cancelar_assinatura`, `metricas`, `definir_status_usuario` e
  `definir_admin`.
- **`admin.py`** (novo) — painel administrativo com 5 páginas: **Visão Geral**
  (cadastros, PRO × gratuitos, faturamento e ticket médio), **Contas** (filtros
  Gratuito / Assinante / Ativo / Inativo, troca de plano e ativação/inativação),
  **Assinaturas** (status e cancelamento), **Pagamentos** (métodos Pix/cartão e notas
  fiscais) e **Cupons** (criar, listar e ativar/desativar).
- **Checkout simulado**: planos, forma de pagamento (Pix/cartão), **cupom de
  desconto** percentual (com validade e limite de usos) e ativação da assinatura.
  Nenhuma cobrança real é feita.
- **Páginas novas do investidor**: **Planos e Assinatura** e **Minha Conta**.
- **Administrador padrão** (`jhon`) **semeado** na criação do banco, já no plano PRO
  e com `is_admin = 1`.
- **Controle de acesso por rota**: as páginas de `admin.py` só entram em
  `st.navigation` quando `is_admin` é verdadeiro — para um usuário comum elas não
  existem no menu.

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
- Camada SQLite (`dados.db`) **multiusuário** com `PRAGMA foreign_keys` e
  `PRAGMA user_version`; esquema v2 com as tabelas de dados do investidor
  (`notas`, `operacoes`, `prejuizos_anteriores`, `proventos`) e as tabelas do SaaS
  (`usuarios`, `planos`, `assinaturas`, `pagamentos`, `cupons`, `cupons_usos`,
  `notas_fiscais`, `config_pagamento`).
- **Migração automática** do banco monousuário anterior (`_migrar`): recria as
  tabelas com `usuario_id`, copia os dados existentes e promove o usuário mais
  antigo a administrador; `_semear` cria os planos e o administrador padrão.
- Todas as consultas do investidor são **escopadas por `usuario_id`**.
- **Deduplicação**: `notas` tem `UNIQUE(corretora, numero)` e `operacoes` usa hash
  único; reimportar PDFs sobrepostos não duplica registros.
- `salvar_notas`, `carregar_operacoes`, `carregar_notas`, `resumo_importacao`,
  `ler_prejuizos`, `gravar_prejuizos`, `salvar_proventos`, `carregar_proventos`,
  `adicionar_provento`, `remover_provento` e `limpar_dados`.
- `salvar_proventos` **deduplica por contagem** de
  `(data, ticker, tipo, quantidade, valor)`: reimportar o mesmo extrato não duplica.
- Saldo de **IRRF a compensar** (`ir_day`, `ir_swing`) lido e gravado junto com os
  saldos de prejuízo.

### Adicionado — Proventos (`proventos.py`)
- Importação do extrato de proventos em **CSV/XLSX** sem digitação manual: as
  colunas de data, ativo, tipo, quantidade e valor são localizadas por
  **sinônimos** de cabeçalho, e os números aceitam o padrão brasileiro
  (`1.234,56`) e o símbolo `R$`.
- Datas convertidas para `AAAA-MM-DD`; tipos normalizados
  (Dividendo, JCP, Rendimento, Amortização, Bonificação, Aluguel, Sobras).
- `irrf_jcp(valor)`: IRRF de JCP a 15%, tratado como **tributação exclusiva** —
  definitivo e **fora do DARF 6015** do IR mensal da renda variável.

### Adicionado — Login local (`auth.py`)
- Login **local com senha**, sem dependências externas: PBKDF2-HMAC-SHA256 com
  sal aleatório, no formato `algoritmo$iteracoes$sal$hash`.
- A senha **não é gravada em claro**; a comparação usa `secrets.compare_digest`
  (tempo constante). A credencial fica na tabela `usuarios` do `dados.db`, que
  está no `.gitignore`.
- **Multiusuário**: `validar_cadastro`, `criar_conta`, `autenticar` (por usuário ou
  e-mail), `alterar_senha` e `gerar_token_recuperacao` / `redefinir_senha` (código
  de 6 caracteres válido por 1 hora, com recuperação **simulada**). Botão **Sair**
  na barra lateral.

### Adicionado — Interface
- Reescrita com **páginas navegáveis** (`st.navigation`): 10 do **investidor**
  (Upload de Notas, Visão Geral, Extrato, Meu Patrimônio, Apuração de IR, DARF,
  Proventos, Relatórios, Planos e Assinatura, Minha Conta) e 5 do **administrador**.
- **Gate de autenticação** com as abas **Entrar**, **Criar conta** e **Recuperar
  senha**; a sessão é revalidada a cada execução (conta desativada derruba o acesso).
- **Indicador de plano** na barra lateral (🆓 Gratuito / 💎 PRO) e identificação do
  perfil de administrador.
- Página **Apuração de IR** com edição dos saldos iniciais de prejuízo **e de IRRF**
  por bucket, transporte calculado para o mês seguinte e detalhamento por
  mercado/categoria (campos `Results*`).
- Página **DARF** com competência, composição, dados para o Sicalc, código de receita
  `6015` e vencimento calculado no último dia útil do mês seguinte.
- Página **Proventos** com importação de extrato (CSV/XLSX), lançamento manual,
  resumo por tipo (com o IRRF do JCP) e gráfico mensal.
- Página **Planos e Assinatura** (checkout simulado, com cupom) e **Minha Conta**
  (perfil e troca de senha).

### Adicionado — Controle de pagamento do DARF
- A página **DARF** ganhou o painel **Competências**, com a situação de cada mês
  (**Isento**, **Em aberto**, **Vencido** ou **Pago**) e as colunas de base, IR
  apurado, IRRF retido, valor a recolher e vencimento.
- Formulário **Pagamento** por competência: marcar o DARF como **pago**, informar o
  **valor pago** e a **data do pagamento**. O aviso de vencimento passa a refletir
  a situação (verde quando pago, vermelho quando vencido).
- `persistencia.carregar_darf_pagamentos` e `persistencia.gravar_darf_pagamento`:
  nova tabela `darf_pagamentos` (chave `usuario_id` + `competencia`), com
  isolamento por usuário; `limpar_dados` também apaga esses registros.

### Alterado — Tabelas com cores condicionais
- As tabelas de resultado (apuração mensal, detalhamento por mercado, extrato e a
  composição do DARF) passaram a exibir **verde para valores positivos** e
  **vermelho para negativos**, com o auxiliar `paginas._colorir`.

### Alterado — Compensação do IRRF em pool único
- O IRRF retido no mês (Day Trade + Swing Trade) e o acumulado de meses anteriores
  passaram a abater o IR apurado **sem separação por bucket**, como no relatório de
  referência: a retenção de Day Trade de um mês já reduz o DARF do próprio mês,
  mesmo sem imposto de Day Trade a compensar.
- O que excede o IR apurado **não se perde**: permanece acumulado no bucket de
  origem (`IRRFNextMonthDayTrade` / `IRRFNextMonthSwingTrade`) para as competências
  seguintes. O **FII continua com DARF próprio**, sem ser reduzido pelo IRRF de
  Day Trade/Swing Trade.
- Efeito: **Ago/2026 = R$ 137,41** e **Set/2026 = R$ 192,65**, centavo a centavo
  iguais ao relatório de referência (antes divergia 0,09 entre os meses).

### Adicionado — Aviso de dias sem nota no upload
- O cartão de conclusão do upload passou a alertar quando há **dias úteis sem nota
  dentro do período importado** (helper `paginas._dias_sem_nota`), listando as datas
  e lembrando que feriados e dias sem negócios também aparecem no aviso. Motivo:
  posições e prejuízos atravessam o mês, então uma nota fora do envio distorce a
  apuração.

### Adicionado — Gestão das notas importadas
- O upload **detecta notas repetidas** — tanto no mesmo envio (o mesmo PDF duas
  vezes) quanto as que já estão no banco — e as **ignora sem erro**, informando
  quantas foram puladas: nada é somado em dobro.
- A tabela **Notas importadas** passou a ser selecionável: **Selecionar todas**,
  **Limpar seleção** e **Apagar selecionadas**, que remove as notas escolhidas e
  as operações que vieram delas.
- `persistencia.remover_notas(conexao, usuario_id, chaves)`: apaga notas e
  operações por `(corretora, número da nota)`, mantendo o isolamento por usuário.

### Adicionado — Validação (`validar.py`)
- Suíte sem dependência de pytest, executável com `python validar.py` (exit code 0/1).
- Cobre: classificação de ativos, reconciliação com os dados de referência (Set/2026),
  isenção, compensação entre meses, compensação de IRRF entre meses, deduplicação
  com os 4 PDFs reais, a reconciliação dos futuros (teste 7, `ajuste do dia −
  despesas da nota`, usando **todo o histórico** — as posições de futuro atravessam
  o mês), a importação de proventos com o IRRF de JCP (teste 8), a
  **autenticação** (teste 9: cadastro, login por usuário e por e-mail, hash PBKDF2,
  troca de senha e recuperação) e as **regras do SaaS** (teste 10: planos, limites,
  cupons, preço, checkout e métricas).
- Os testes que dependem de PDFs reais leem a pasta `~/Downloads/Notas` (ajustável
  pela variável de ambiente `NOTAS_DIR`) e são ignorados quando ela não existe —
  nenhuma nota de corretagem entra no repositório.
- Resultado atual: **todas as verificações passam** (`EXIT=0`), incluindo
  `IRRFFinal = 192,65` e `IRRFBase = 205,79` idênticos aos dados de referência.

### Segurança
- A senha do administrador **deixou de ficar no código**: `auth.py` agora lê as
  credenciais de `st.secrets["admin"]` (Streamlit Cloud: *App settings → Secrets*;
  local: `.streamlit/secrets.toml`, fora do versionamento). Sem `senha` configurada,
  o administrador não é semeado e o app segue funcionando sem painel administrativo.
- Histórico do Git reescrito para remover um e-mail pessoal que havia sido gravado
  em um commit de `.devcontainer` (autoria normalizada para o `noreply` do GitHub).

### Alterado
- `requirements.txt`: removido `playwright`, que não era importado em lugar nenhum
  (resquício da ferramenta de mapeamento) e deixava o build do Streamlit Cloud
  pesado.
- `README.md` reescrito: 10 páginas do investidor + 5 do admin, planos, acesso,
  arquitetura, regras fiscais, validação e deploy.
- `.gitignore`: passou a ignorar `*.db`, `*.db-journal`, `*.sqlite*` e `_tmp_notas/`.
- `app.py`: removida a dívida técnica `__import__("regras")` — `classificar_grupo`
  agora é importada no topo do módulo.
- **`app.py` dividido em dois módulos**: as abas foram substituídas por
  páginas navegáveis e todo o conteúdo (utilitários, carga dos dados e as
  funções `pagina_*`) foi movido para o novo `paginas.py`. O `app.py` ficou
  reduzido à entrada: gate de autenticação, `paginas.carregar()` e o
  `st.navigation([...]).run()`. Motivo: com páginas baseadas em `callable`, o
  `AppTest.switch_page` não funciona — mantendo cada `pagina_*` como função, as
  páginas continuam testáveis isoladamente.
- `use_container_width=True` substituído por `width="stretch"` (depreciado no
  Streamlit 1.66).

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
- **`no such table: darf_pagamentos` no app publicado**: o `CREATE TABLE` só rodava
  ao abrir a conexão, e a conexão é reaproveitada entre execuções
  (`st.cache_resource`) — depois de um deploy que criou a tabela, um banco antigo
  continuava sem ela e qualquer página quebrava. `VERSAO_ESQUEMA` subiu para **3** e
  a nova função `persistencia.garantir_esquema` confere o `PRAGMA user_version` a
  cada execução, aplicando o esquema quando o banco está atrás — sem tocar nos dados
  já existentes.

## Base
- Projeto construído a partir do mapeamento de **27 telas** de um sistema de
  referência (pasta `ref_exemplo/`) e das regras documentadas em
  `ANALISE_REFERENCIA.md`.
