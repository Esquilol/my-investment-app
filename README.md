# 📈 Gestor de Investimentos B3

Aplicativo em **Streamlit** para gerenciar investimentos e apurar **Imposto de Renda**
automaticamente a partir de **notas de corretagem em PDF** (sem digitação manual).

O projeto foi construído a partir do mapeamento de um sistema de referência
(ver `ANALISE_REFERENCIA.md` e `ref_exemplo/`), reproduzindo o fluxo
nota de corretagem → extrato de operações → apuração mensal → DARF.

## Funcionalidades (8 páginas)

| Página | O que faz |
| --- | --- |
| 📁 **Upload de Notas** | Importa PDFs de notas de corretagem com deduplicação por número de nota; mostra o resumo da importação e permite limpar os dados. |
| 📊 **Visão Geral** | Painel inicial: totais de resultado, patrimônio em custódia, evolução e últimos negócios. |
| 🧾 **Extrato** | Todas as operações gravadas, com filtros por período, ticker e tipo. |
| 💼 **Meu Patrimônio** | Posição em custódia com quantidade, preço médio e custo total por ativo. |
| 💰 **Apuração de IR** | Tabela mensal com isenção por limite de vendas e compensação de prejuízo entre meses; edição dos saldos iniciais de prejuízo. |
| 🧮 **DARF** | Valor a recolher por competência, com composição, dados para o Sicalc e código de receita. |
| 💵 **Proventos** | Importa o extrato de proventos (CSV/XLSX) e lança dividendos, JCP, rendimentos e amortizações à mão; faz o resumo por tipo, com o IRRF do JCP. |
| 📥 **Relatórios** | Exportação dos dados em **CSV** e **Excel**. |

> ⚠️ Os valores apurados são uma **estimativa técnica** e não substituem a apuração
> oficial (GCAP / DIRPF) nem a orientação de um contador.

## Regras fiscais implementadas

- **Day Trade**: 20% (sem isenção).
- **Swing Trade**: 15%; **FII / FIAGRO**: 20%.
- **Isenção** para ações / BDR / ouro quando as vendas do mês não passam de
  **R$ 20.000,00** (ativos EUA: **R$ 35.000,00**), conforme a tabela de grupos
  (`Exemption` + `ExemptionValue`).
- **Compensação de prejuízo** por bucket (**Day Trade**, **Swing Trade**, **FII**)
  entre meses, carregando o saldo negativo para o mês seguinte.
- **Preço médio** calculado com as **taxas somadas ao custo**.
- **IRRF retido na fonte** (dedo-duro) descontado do imposto mensal.
- **IRRF de JCP**: 15% com **tributação exclusiva** — é definitivo e **não entra**
  no DARF 6015; serve para informar o rendimento na declaração anual.
- **DARF** com código de receita **6015** e vencimento no **último dia útil do mês seguinte**.

## Estrutura do projeto

```
.
├── app.py            # Entrada Streamlit (configura a página e monta o menu)
├── paginas.py        # Conteúdo das 8 páginas navegáveis e carga dos dados
├── parser.py         # Extrator de operações das notas em PDF (pdfplumber)
├── persistencia.py   # Camada SQLite (notas, operações, prejuízos, proventos)
├── proventos.py      # Importação do extrato de proventos e IRRF de JCP
├── regras.py         # Motor fiscal (classificação, preço médio, apuração mensal)
├── validar.py        # Suíte de validação do motor fiscal (sem pytest)
├── requirements.txt  # Dependências
├── CHANGELOG.md      # Histórico de alterações
└── README.md
```

Fluxo de dados:

```
PDF  →  parser.py  →  persistencia.py (dados.db)  →  regras.py  →  paginas.py  →  app.py
```

## Instalação

Requer **Python 3.10+** (testado com 3.12).

```bash
# (opcional) criar ambiente virtual
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# instalar dependências
pip install -r requirements.txt
```

## Executar localmente

No Windows, chamar o Streamlit **como módulo** evita problemas de PATH:

```bash
python -m streamlit run app.py
```

O navegador abrirá em `http://localhost:8501`.

## Validação

A suíte `validar.py` confere o motor fiscal contra os números de referência de
Set/2026 e cobre classificação de ativos, isenção, compensação de prejuízo,
compensação de IRRF, deduplicação de notas e a importação de proventos com o
IRRF de JCP:

```bash
python validar.py
```

Retorna `EXIT=0` quando todas as verificações passam.

## Como usar

1. Em **📁 Upload de Notas**, envie os PDFs das notas de corretagem.
2. Em **💵 Proventos**, importe o extrato de proventos (CSV/XLSX) da corretora.
3. Confira a posição em **💼 Meu Patrimônio** e as operações em **🧾 Extrato**.
4. Em **💰 Apuração de IR**, ajuste os saldos de prejuízo anteriores, se houver.
5. Em **🧮 DARF**, veja o valor a recolher da competência.
6. Exporte em **📥 Relatórios** (CSV ou Excel).

## Deploy

- **Streamlit Community Cloud**: aponte o repositório e o arquivo `app.py`.
- **Render**: crie um *Web Service* com o comando
  `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`.
- **Replit**: importe o repositório e rode `streamlit run app.py`.

## Publicar no GitHub

O repositório local já está inicializado e com o commit inicial
(`feat: motor fiscal, persistencia SQLite e interface com 8 páginas`).
Antes de publicar, configure sua identidade (usada nos próximos commits):

```bash
git config --global user.name  "Seu Nome"
git config --global user.email "seu-email@exemplo.com"
```

Depois, aponte para o remoto e envie:

```bash
git branch -M main
git remote add origin https://github.com/<seu-usuario>/<seu-repo>.git
git push -u origin main
```

Arquivos com dados pessoais e o banco local (`*.db`) já estão no `.gitignore`.

## Próximos passos sugeridos

- Ampliar o suporte a outros layouts de corretora (3 layouts já mapeados).
- Integrar a importação automática de notas (integrações com corretoras).
- Gerar o arquivo do GCAP / DIRPF a partir da apuração.
