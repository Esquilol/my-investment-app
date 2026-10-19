# 📈 Gestor de Investimentos B3

Aplicativo em **Streamlit** para gerenciar investimentos e apurar **Imposto de Renda**
automaticamente a partir de **notas de corretagem em PDF** (sem digitação manual).

O projeto foi construído a partir do mapeamento de um sistema de referência
(ver `ANALISE_REFERENCIA.md` e `ref_exemplo/`), reproduzindo o fluxo
nota de corretagem → extrato de operações → apuração mensal → DARF.

É um **SaaS multiusuário**: cada pessoa cria a própria conta, entra no **plano
Gratuito** e pode assinar o **PRO**; há ainda um **painel administrativo** restrito
a administradores (gestão de contas, assinaturas, pagamentos e cupons).

## Funcionalidades

### Painel do investidor (10 páginas)

| Página | O que faz |
| --- | --- |
| 📁 **Upload de Notas** | Importa PDFs de notas de corretagem com deduplicação por número de nota; mostra o resumo da importação e permite limpar os dados. |
| 📊 **Visão Geral** | Painel inicial: totais de resultado, patrimônio em custódia, evolução e últimos negócios. |
| 🧾 **Extrato** | Todas as operações gravadas, com filtros por período, ticker e tipo. |
| 💼 **Meu Patrimônio** | Posição em custódia com quantidade, preço médio e custo total por ativo. |
| 💰 **Apuração de IR** | Tabela mensal com isenção por limite de vendas e compensação de prejuízo entre meses; edição dos saldos iniciais de prejuízo. |
| 🧮 **DARF** | Valor a recolher por competência, com composição, dados para o Sicalc e código de receita. |
| 💵 **Proventos** | Importa o extrato de proventos (CSV/XLSX) e lança dividendos, JCP, rendimentos e amortizações à mão; faz o resumo por tipo, com o IRRF do JCP. |
| 📥 **Relatórios** | Exportação dos dados em **CSV** e **Excel** (Excel só no PRO). |
| 💳 **Planos e Assinatura** | Compara os planos, aplica **cupom de desconto** e faz o **checkout** (Pix/cartão, simulado); mostra assinatura vigente, pagamentos e notas fiscais. |
| 👤 **Minha Conta** | Perfil (usuário, e-mail, plano, perfil de acesso) e **troca de senha**. |

### Painel administrativo (5 páginas — apenas `is_admin`)

| Página | O que faz |
| --- | --- |
| 📊 **Visão Geral** | Métricas: cadastros, assinantes PRO × gratuitos, faturamento acumulado e ticket médio. |
| 👥 **Contas** | Todos os cadastros, com filtro **Gratuito / Assinante / Ativo / Inativo**, troca de plano e **ativação/inativação** da conta. |
| 📋 **Assinaturas** | Assinaturas ativas, canceladas e substituídas, com cancelamento. |
| 💳 **Pagamentos** | Configuração dos métodos de pagamento (chaves Pix/cartão) e notas fiscais emitidas. |
| 🎟️ **Cupons** | Criação, listagem e **ativação/desativação** de cupons promocionais. |

> ⚠️ Os valores apurados são uma **estimativa técnica** e não substituem a apuração
> oficial (GCAP / DIRPF) nem a orientação de um contador.

## Planos e monetização

| Plano | Preço | Notas | Exportação Excel |
| --- | --- | --- | --- |
| **Gratuito** | Grátis | até 20 notas importadas | não |
| **PRO** | R$ 29,90/mês | ilimitadas | sim |

- O **cadastro** entra sempre no plano **Gratuito**.
- O **checkout é simulado**: nenhuma cobrança real é feita. Ao assinar, geram-se
  um **pagamento** e uma **nota fiscal** (`NF-AAAAAM-00001`) no banco local.
- **Cupons** de desconto percentual podem ser aplicados no checkout; o uso é
  registrado e o cupom respeita validade e limite de usos.
- As **chaves de pagamento** (Pix/cartão) ficam na tabela `config_pagamento`, para
  quando a integração real for ligada.

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
├── app.py            # Entrada: gate de autenticação e navegação (investidor + admin)
├── paginas.py        # Conteúdo das 10 páginas do investidor e carga dos dados
├── admin.py          # Painel administrativo (5 páginas, restrito a is_admin)
├── parser.py         # Extrator de operações das notas em PDF (pdfplumber)
├── persistencia.py   # Camada SQLite multiusuário (usuários, planos, assinaturas,
│                     #   pagamentos, cupons, notas fiscais, notas e operações)
├── proventos.py      # Importação do extrato de proventos e IRRF de JCP
├── auth.py           # Contas, hash PBKDF2 da senha, login e recuperação
├── saas.py           # Regras do SaaS: planos, limites, cupons, checkout e métricas
├── regras.py         # Motor fiscal (classificação, preço médio, apuração mensal)
├── validar.py        # Suíte de validação (motor fiscal, persistência, auth e SaaS)
├── requirements.txt  # Dependências
├── CHANGELOG.md      # Histórico de alterações
└── README.md
```

Fluxo de dados:

```
PDF  →  parser.py  →  persistencia.py (dados.db)  →  regras.py  →  paginas.py  →  app.py
                                    ▲
                     auth.py / saas.py (contas, planos, pagamentos)
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

## Acesso e contas

O app é **multiusuário**. Na tela inicial há três abas: **Entrar**, **Criar conta**
e **Recuperar senha**.

- **Criar conta** pede usuário, e-mail e senha. A conta nasce no **plano Gratuito**.
- As senhas são gravadas apenas como **hash PBKDF2-HMAC-SHA256** (sal aleatório por
  usuário) na tabela `usuarios` — **nunca em claro**. A comparação usa
  `secrets.compare_digest` (tempo constante).
- **Recuperação de senha** é **simulada**: como o app ainda não envia e-mails, o
  código de recuperação (válido por 1 hora) é exibido na própria tela e informado
  no formulário de redefinição.
- Na barra lateral aparecem o **usuário**, um **indicador do plano** (🆓 Gratuito /
  💎 PRO), o perfil (Administrador, quando for o caso) e o botão **Sair**.

### Administrador

O primeiro administrador é **semeado automaticamente** na criação do banco, com o
usuário padrão **`jhon`** (definido em `auth.py` como `ADMIN_PADRAO_*`). Ele nasce
no plano PRO e com `is_admin = 1`, e é o **único** com acesso ao painel
administrativo.

> 🔒 **Troque a senha do administrador logo no primeiro login** (em **Minha Conta**)
> e mantenha o `dados.db` fora do versionamento — ele já está no `.gitignore`.

O acesso ao painel administrativo é **por rota**, não por botão: as páginas de
`admin.py` só são registradas em `st.navigation` quando `st.session_state["is_admin"]`
é verdadeiro. Para um usuário comum, elas simplesmente **não existem** no menu. A
cada execução o app relê o usuário no banco, então desativar uma conta ou remover o
perfil de administrador tem efeito imediato.

## Validação

A suíte `validar.py` confere o motor fiscal contra os números de referência de
Set/2026 e cobre classificação de ativos, isenção, compensação de prejuízo,
compensação de IRRF, deduplicação de notas, a importação de proventos com o
IRRF de JCP, a **autenticação** (cadastro, login, senha e recuperação) e as
**regras do SaaS** (planos, limites, cupons, checkout e métricas):

```bash
python validar.py
```

Retorna `EXIT=0` quando todas as verificações passam.

## Como usar

1. **Crie sua conta** (ou entre, se já tiver) na tela inicial.
2. Em **📁 Upload de Notas**, envie os PDFs das notas de corretagem.
3. Em **💵 Proventos**, importe o extrato de proventos (CSV/XLSX) da corretora.
4. Confira a posição em **💼 Meu Patrimônio** e as operações em **🧾 Extrato**.
5. Em **💰 Apuração de IR**, ajuste os saldos de prejuízo anteriores, se houver.
6. Em **🧮 DARF**, veja o valor a recolher da competência.
7. Exporte em **📥 Relatórios** (CSV ou Excel).
8. Em **💳 Planos e Assinatura**, aplique um cupom e assine o **PRO** (checkout simulado).
9. Em **👤 Minha Conta**, confira o perfil e troque a senha.

Administradores ainda veem o grupo **Administração** na barra lateral, com as
páginas de contas, assinaturas, pagamentos e cupons.

## Deploy

- **Streamlit Community Cloud**: aponte o repositório e o arquivo `app.py`.
- **Render**: crie um *Web Service* com o comando
  `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`.
- **Replit**: importe o repositório e rode `streamlit run app.py`.

## Publicar no GitHub

O repositório já está inicializado, com o remoto `origin` configurado. Para enviar
novas alterações:

```bash
git add app.py admin.py paginas.py persistencia.py saas.py auth.py validar.py \
        README.md CHANGELOG.md
git commit -m "feat: evolui o app para SaaS (contas, planos, admin)"
git push
```

Para sanitizar a autoria dos commits públicos, use o e-mail `noreply` do GitHub:

```bash
git config user.email "<id>+<usuario>@users.noreply.github.com"
git commit --amend --reset-author
```

Arquivos com dados pessoais e o banco local (`*.db`) já estão no `.gitignore`.

## Próximos passos sugeridos

- Ampliar o suporte a outros layouts de corretora (3 layouts já mapeados).
- Integrar a importação automática de notas (integrações com corretoras).
- Gerar o arquivo do GCAP / DIRPF a partir da apuração.
