"""
persistencia.py
---------------
Camada de acesso ao **SQLite** (``dados.db``).

Por usuário, guarda:

* as notas de corretagem e as operações, com **deduplicação** por
  (usuário, corretora, número da nota);
* o saldo de **prejuízo / IRRF** anterior a compensar;
* os **proventos**, importados do extrato ou lançados à mão.

Para a operação SaaS, guarda ainda:

* **usuários** (nome, CPF, hash de senha, perfil de acesso, plano e status);
* **planos**, **assinaturas** e **pagamentos**;
* **cupons** de desconto e **notas fiscais**;
* os **parceiros** e as **indicações** que trouxeram cada conta nova;
* a **configuração dos métodos de pagamento**.

O banco fica fora do versionamento (``.gitignore``), de modo que credenciais e
dados pessoais nunca vão para o repositório.

Uso:
    from persistencia import conectar, salvar_notas, carregar_operacoes
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from parser import Nota

#: Banco criado ao lado dos módulos do projeto.
CAMINHO_PADRAO = Path(__file__).with_name("dados.db")

#: Versão do esquema gravada em ``PRAGMA user_version``.
#: 3 — acrescenta a tabela ``darf_pagamentos``.
#: 4 — acrescenta ``parametros_fiscais`` e ``monitor_legislacao``.
#: 5 — acrescenta ``parceiros`` e ``indicacoes``; ``cupons`` ganha o modo
#:     "meses grátis" e ``usuarios`` ganha nome, CPF e origem.
#: 6 — a chave única da nota passa a incluir a ``folha``: notas que ocupam
#:     mais de uma página deixam de ter a 2ª folha descartada na importação.
VERSAO_ESQUEMA = 6

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario       TEXT    NOT NULL UNIQUE,
    email         TEXT    NOT NULL UNIQUE,
    hash          TEXT    NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    ativo         INTEGER NOT NULL DEFAULT 1,
    plano_codigo  TEXT    NOT NULL DEFAULT 'free',
    nome          TEXT,
    cpf           TEXT,
    telefone      TEXT,
    cidade        TEXT,
    estado        TEXT,
    endereco      TEXT,
    cep           TEXT,
    origem        TEXT,
    reset_token   TEXT,
    reset_expira  TEXT,
    criado_em     TEXT
);

CREATE TABLE IF NOT EXISTS planos (
    codigo        TEXT PRIMARY KEY,
    nome          TEXT    NOT NULL,
    preco_mensal  REAL    NOT NULL DEFAULT 0,
    limite_notas  INTEGER NOT NULL DEFAULT -1,
    exporta_excel INTEGER NOT NULL DEFAULT 0,
    descricao     TEXT
);

CREATE TABLE IF NOT EXISTS assinaturas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id      INTEGER NOT NULL,
    plano_codigo    TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'ativa',
    inicio          TEXT,
    fim             TEXT,
    valor_pago      REAL    NOT NULL DEFAULT 0,
    cupom_codigo    TEXT,
    forma_pagamento TEXT,
    criado_em       TEXT,
    FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
);

CREATE TABLE IF NOT EXISTS pagamentos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id    INTEGER NOT NULL,
    assinatura_id INTEGER,
    valor         REAL    NOT NULL DEFAULT 0,
    desconto      REAL    NOT NULL DEFAULT 0,
    valor_final   REAL    NOT NULL DEFAULT 0,
    forma         TEXT,
    status        TEXT    NOT NULL DEFAULT 'pago',
    referencia    TEXT,
    criado_em     TEXT,
    FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
);

CREATE TABLE IF NOT EXISTS cupons (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo       TEXT    NOT NULL UNIQUE,
    tipo         TEXT    NOT NULL DEFAULT 'percentual',
    desconto_pct REAL    NOT NULL DEFAULT 0,
    meses_gratis INTEGER NOT NULL DEFAULT 0,
    ativo        INTEGER NOT NULL DEFAULT 1,
    validade     TEXT,
    uso_maximo   INTEGER NOT NULL DEFAULT 0,
    usos         INTEGER NOT NULL DEFAULT 0,
    criado_em    TEXT
);

CREATE TABLE IF NOT EXISTS parceiros (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT    NOT NULL,
    email           TEXT,
    codigo          TEXT    NOT NULL UNIQUE,
    comissao_pct    REAL    NOT NULL DEFAULT 0,
    beneficio_tipo  TEXT    NOT NULL DEFAULT 'percentual',
    beneficio_valor REAL    NOT NULL DEFAULT 0,
    ativo           INTEGER NOT NULL DEFAULT 1,
    criado_em       TEXT
);

CREATE TABLE IF NOT EXISTS indicacoes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id      INTEGER NOT NULL UNIQUE,
    parceiro_id     INTEGER NOT NULL,
    beneficio_usado INTEGER NOT NULL DEFAULT 0,
    criado_em       TEXT,
    FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
    FOREIGN KEY (parceiro_id) REFERENCES parceiros (id)
);

CREATE TABLE IF NOT EXISTS notas_fiscais (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id   INTEGER NOT NULL,
    pagamento_id INTEGER,
    numero       TEXT    NOT NULL,
    valor        REAL    NOT NULL DEFAULT 0,
    data         TEXT,
    FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
);

CREATE TABLE IF NOT EXISTS config_pagamento (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    pix_chave         TEXT,
    pix_recebedor     TEXT,
    cartao_provedor   TEXT,
    cartao_api_key    TEXT,
    cartao_public_key TEXT,
    ambiente          TEXT NOT NULL DEFAULT 'simulado',
    atualizado_em     TEXT
);

CREATE TABLE IF NOT EXISTS notas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id      INTEGER NOT NULL,
    numero          TEXT    NOT NULL,
    corretora       TEXT    NOT NULL,
    folha           TEXT    NOT NULL DEFAULT '',
    data            TEXT,
    arquivo         TEXT,
    despesas        REAL    NOT NULL DEFAULT 0,
    irrf            REAL    NOT NULL DEFAULT 0,
    categoria_irrf  TEXT    NOT NULL DEFAULT 'SwingTrade',
    UNIQUE (usuario_id, corretora, numero, folha)
);

CREATE TABLE IF NOT EXISTS operacoes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id   INTEGER NOT NULL,
    hash         TEXT    NOT NULL,
    corretora    TEXT,
    nota         TEXT,
    folha        TEXT,
    data         TEXT,
    tipo         TEXT,
    ticker       TEXT,
    quantidade   REAL,
    preco        REAL,
    valor_total  REAL,
    mercado      TEXT,
    taxas        REAL    NOT NULL DEFAULT 0,
    irrf         REAL    NOT NULL DEFAULT 0,
    resultado    REAL,
    day_trade    INTEGER NOT NULL DEFAULT 0,
    obs          TEXT,
    arquivo      TEXT,
    UNIQUE (usuario_id, hash)
);

CREATE TABLE IF NOT EXISTS prejuizos_anteriores (
    usuario_id          INTEGER PRIMARY KEY,
    data                TEXT,
    previous_loss_fii   REAL NOT NULL DEFAULT 0,
    previous_loss_swing REAL NOT NULL DEFAULT 0,
    previous_loss_day   REAL NOT NULL DEFAULT 0,
    ir_swing            REAL NOT NULL DEFAULT 0,
    ir_day              REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS proventos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    data       TEXT NOT NULL,
    ticker     TEXT NOT NULL,
    tipo       TEXT NOT NULL,
    quantidade REAL NOT NULL DEFAULT 0,
    valor      REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS darf_pagamentos (
    usuario_id     INTEGER NOT NULL,
    competencia    TEXT    NOT NULL,
    pago           INTEGER NOT NULL DEFAULT 0,
    valor_pago     REAL    NOT NULL DEFAULT 0,
    data_pagamento TEXT,
    atualizado_em  TEXT,
    PRIMARY KEY (usuario_id, competencia)
);

CREATE TABLE IF NOT EXISTS parametros_fiscais (
    chave         TEXT PRIMARY KEY,
    valor         TEXT NOT NULL,
    atualizado_em TEXT
);

CREATE TABLE IF NOT EXISTS monitor_legislacao (
    url           TEXT PRIMARY KEY,
    titulo        TEXT,
    hash          TEXT,
    verificado_em TEXT,
    mudou_em      TEXT
);

CREATE TABLE IF NOT EXISTS opcoes_operacoes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id           INTEGER NOT NULL,
    codigo               TEXT    NOT NULL,
    ativo_subjacente     TEXT,
    tipo_opcao           TEXT,
    estrutura            TEXT    NOT NULL,
    data_inicio          TEXT    NOT NULL,
    data_fim             TEXT,
    dias                 INTEGER,
    quantidade           REAL    NOT NULL DEFAULT 100,
    preco_pago           REAL    NOT NULL DEFAULT 0,
    preco_recebido       REAL    NOT NULL DEFAULT 0,
    preco_atual          REAL    NOT NULL DEFAULT 0,
    valor_alocado        REAL    NOT NULL DEFAULT 0,
    valor_final          REAL    NOT NULL DEFAULT 0,
    resultado_financeiro REAL    NOT NULL DEFAULT 0,
    resultado_pct        REAL    NOT NULL DEFAULT 0,
    sucesso              TEXT    NOT NULL DEFAULT 'n',
    status               TEXT    NOT NULL DEFAULT 'aberta',
    operacao_origem_id   INTEGER,
    meta_rolagem_pct     REAL    NOT NULL DEFAULT 100.0,
    observacoes          TEXT,
    criado_em            TEXT,
    FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
    FOREIGN KEY (operacao_origem_id) REFERENCES opcoes_operacoes (id)
);
"""

#: Planos semeados na primeira execução. ``limite_notas = -1`` significa ilimitado.
PLANOS_PADRAO = [
    ("free", "Gratuito", 0.0, 20, 0,
     "Até 20 notas importadas, apuração de IR e proventos. Sem exportação em Excel."),
    ("pro", "PRO", 29.90, -1, 1,
     "Notas ilimitadas, exportação completa em Excel/CSV e suporte prioritário."),
]


def agora() -> str:
    """Data/hora local em ISO, usada em todos os carimbos de tempo."""
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Conexão, migração e semeadura
# ---------------------------------------------------------------------------

def _colunas(conexao: sqlite3.Connection, tabela: str) -> set[str]:
    return {linha["name"] for linha in conexao.execute(f"PRAGMA table_info({tabela})")}


def _acrescentar_colunas(conexao: sqlite3.Connection) -> None:
    """
    Acrescenta colunas novas em tabelas que já existem (migração idempotente).

    O ``CREATE TABLE IF NOT EXISTS`` do esquema não altera tabelas já criadas,
    então toda coluna acrescentada depois da primeira versão precisa entrar
    aqui — do contrário um banco antigo continuaria sem a coluna e as consultas
    falhariam com *no such column*.
    """
    novas = {
        "usuarios": {
            "nome": "TEXT",
            "cpf": "TEXT",
            "telefone": "TEXT",
            "cidade": "TEXT",
            "estado": "TEXT",
            "endereco": "TEXT",
            "cep": "TEXT",
            "origem": "TEXT",
            "modulo_fiscal": "INTEGER NOT NULL DEFAULT 1",
            "modulo_opcoes": "INTEGER NOT NULL DEFAULT 1",
        },
        "cupons": {
            "tipo": "TEXT NOT NULL DEFAULT 'percentual'",
            "meses_gratis": "INTEGER NOT NULL DEFAULT 0",
        },
        # A coluna ``folha`` de ``notas`` **não** entra aqui: ela exige a
        # recriação da tabela para trocar a UNIQUE (ver ``_migrar_v6``), e um
        # ``ADD COLUMN`` antes disso impediria a migração de rodar.
        "operacoes": {"folha": "TEXT"},
    }
    for tabela, colunas in novas.items():
        existentes = _colunas(conexao, tabela)
        for nome, definicao in colunas.items():
            if existentes and nome not in existentes:
                conexao.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {definicao}")

    conexao.execute("""
        CREATE TABLE IF NOT EXISTS opcoes_operacoes (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id           INTEGER NOT NULL,
            codigo               TEXT    NOT NULL,
            ativo_subjacente     TEXT,
            tipo_opcao           TEXT,
            estrutura            TEXT    NOT NULL,
            data_inicio          TEXT    NOT NULL,
            data_fim             TEXT,
            dias                 INTEGER,
            quantidade           REAL    NOT NULL DEFAULT 100,
            preco_pago           REAL    NOT NULL DEFAULT 0,
            preco_recebido       REAL    NOT NULL DEFAULT 0,
            preco_atual          REAL    NOT NULL DEFAULT 0,
            valor_alocado        REAL    NOT NULL DEFAULT 0,
            valor_final          REAL    NOT NULL DEFAULT 0,
            resultado_financeiro REAL    NOT NULL DEFAULT 0,
            resultado_pct        REAL    NOT NULL DEFAULT 0,
            sucesso              TEXT    NOT NULL DEFAULT 'n',
            status               TEXT    NOT NULL DEFAULT 'aberta',
            operacao_origem_id   INTEGER,
            meta_rolagem_pct     REAL    NOT NULL DEFAULT 100.0,
            observacoes          TEXT,
            criado_em            TEXT,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
            FOREIGN KEY (operacao_origem_id) REFERENCES opcoes_operacoes (id)
        );
    """)

    # O CPF identifica uma pessoa: não pode repetir entre contas. Índice parcial
    # porque o administrador e as contas antigas não têm CPF preenchido.
    conexao.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_cpf "
        "ON usuarios (cpf) WHERE cpf IS NOT NULL")
    conexao.commit()


def _migrar_v6(conexao: sqlite3.Connection) -> None:
    """
    v6: incluir a ``folha`` na chave única da nota.

    Uma nota de corretagem pode ocupar mais de uma página; o campo *Folha*
    distingue essas páginas. O esquema antigo gravava a UNIQUE apenas por
    ``(usuario_id, corretora, numero)``, então a 2ª folha era descartada em
    silêncio. Como o SQLite não altera uma UNIQUE existente, a tabela é
    recriada. As notas já gravadas recebem ``folha = '1'`` (antes da correção
    só a 1ª folha sobrevivia), de modo que uma reimportação acrescente apenas
    as folhas seguintes.
    """
    if "folha" not in _colunas(conexao, "notas"):
        conexao.executescript("ALTER TABLE notas RENAME TO notas_v5;")
        conexao.executescript(_ESQUEMA)          # recria ``notas`` no formato novo
        conexao.execute(
            "INSERT INTO notas "
            "(id, usuario_id, numero, corretora, folha, data, arquivo, despesas, "
            " irrf, categoria_irrf) "
            "SELECT id, usuario_id, numero, corretora, '1', data, arquivo, "
            "       despesas, irrf, categoria_irrf FROM notas_v5")
        conexao.execute("DROP TABLE notas_v5")

    conexao.execute(
        "UPDATE notas SET folha = '1' WHERE folha IS NULL OR folha = ''")


def _migrar(conexao: sqlite3.Connection) -> None:
    """
    Converte o esquema **monousuário** antigo no esquema multiusuário.

    Os dados existentes passam a pertencer ao primeiro usuário (promovido a
    administrador), de modo que nada é perdido na atualização.
    """
    if "usuario_id" in _colunas(conexao, "notas"):
        _migrar_v6(conexao)
        _acrescentar_colunas(conexao)
        conexao.execute(f"PRAGMA user_version = {VERSAO_ESQUEMA}")
        return

    # 1) usuarios ganha e-mail, perfil, status e plano.
    if _colunas(conexao, "usuarios") and "email" not in _colunas(conexao, "usuarios"):
        conexao.executescript("""
            ALTER TABLE usuarios RENAME TO usuarios_antigo;
            CREATE TABLE usuarios (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario       TEXT    NOT NULL UNIQUE,
                email         TEXT    NOT NULL UNIQUE,
                hash          TEXT    NOT NULL,
                is_admin      INTEGER NOT NULL DEFAULT 0,
                ativo         INTEGER NOT NULL DEFAULT 1,
                plano_codigo  TEXT    NOT NULL DEFAULT 'free',
                reset_token   TEXT,
                reset_expira  TEXT,
                criado_em     TEXT
            );
            INSERT INTO usuarios
                (id, usuario, email, hash, is_admin, ativo, plano_codigo, criado_em)
            SELECT id, usuario, usuario || '@local', hash, 1, 1, 'free', criado_em
            FROM usuarios_antigo;
            DROP TABLE usuarios_antigo;
        """)

    dono = conexao.execute(
        "SELECT MIN(id) FROM usuarios").fetchone()[0] or 1

    # 2) tabelas de dados do usuário: acrescenta usuario_id e refaz as restrições.
    for tabela, colunas in (
        ("notas", "numero, corretora, data, arquivo, despesas, irrf, categoria_irrf"),
        ("operacoes", "hash, corretora, nota, data, tipo, ticker, quantidade, preco, "
                      "valor_total, mercado, taxas, irrf, resultado, day_trade, obs, arquivo"),
        ("proventos", "data, ticker, tipo, quantidade, valor"),
    ):
        if "usuario_id" in _colunas(conexao, tabela):
            continue
        conexao.executescript(f"""
            ALTER TABLE {tabela} RENAME TO {tabela}_antigo;
        """)
        conexao.executescript(_ESQUEMA)          # recria no formato novo
        conexao.execute(
            f"INSERT INTO {tabela} (usuario_id, {colunas}) "
            f"SELECT ?, {colunas} FROM {tabela}_antigo",
            (dono,),
        )
        conexao.execute(f"DROP TABLE {tabela}_antigo")

    if "usuario_id" not in _colunas(conexao, "prejuizos_anteriores"):
        conexao.executescript("ALTER TABLE prejuizos_anteriores RENAME TO prejuizos_antigo;")
        conexao.executescript(_ESQUEMA)
        conexao.execute(
            "INSERT INTO prejuizos_anteriores "
            "(usuario_id, data, previous_loss_fii, previous_loss_swing, "
            " previous_loss_day, ir_swing, ir_day) "
            "SELECT ?, data, previous_loss_fii, previous_loss_swing, "
            "       previous_loss_day, ir_swing, ir_day "
            "FROM prejuizos_antigo WHERE id = 1",
            (dono,),
        )
        conexao.execute("DROP TABLE prejuizos_antigo")

    _migrar_v6(conexao)
    _acrescentar_colunas(conexao)
    conexao.execute(f"PRAGMA user_version = {VERSAO_ESQUEMA}")


def _semear(conexao: sqlite3.Connection) -> None:
    """Cria os planos, a configuração de pagamento, os parâmetros fiscais e o admin."""
    conexao.executemany(
        "INSERT OR IGNORE INTO planos "
        "(codigo, nome, preco_mensal, limite_notas, exporta_excel, descricao) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        PLANOS_PADRAO,
    )
    conexao.execute(
        "INSERT OR IGNORE INTO config_pagamento (id, ambiente) VALUES (1, 'simulado')")

    # Parâmetros do motor fiscal: semeados com os valores de lei vigentes; o
    # painel administrativo pode alterá-los depois (INSERT OR IGNORE preserva
    # o que já foi gravado).
    from regras import PARAMETROS_PADRAO

    conexao.executemany(
        "INSERT OR IGNORE INTO parametros_fiscais (chave, valor, atualizado_em) "
        "VALUES (?, ?, ?)",
        [(chave, str(valor), agora()) for chave, valor in PARAMETROS_PADRAO.items()],
    )

    # Administrador: as credenciais vêm dos segredos (``st.secrets["admin"]``),
    # nunca do código. O ``INSERT OR IGNORE`` torna o seed idempotente: se o
    # usuário já existir (mesmo que a senha tenha sido trocada depois), nada é
    # alterado. Sem os segredos configurados, o app sobe sem usuário
    # administrativo — por isso os segredos precisam existir no ambiente
    # (localmente em ``.streamlit/secrets.toml``; no Streamlit Cloud em
    # *App settings → Secrets*).
    from auth import ADMIN_PADRAO_EMAIL, ADMIN_PADRAO_SENHA, ADMIN_PADRAO_USUARIO, gerar_hash

    if ADMIN_PADRAO_USUARIO and ADMIN_PADRAO_SENHA and ADMIN_PADRAO_EMAIL:
        conexao.execute(
            "INSERT OR IGNORE INTO usuarios "
            "(usuario, email, hash, is_admin, ativo, plano_codigo, criado_em) "
            "VALUES (?, ?, ?, 1, 1, 'pro', ?)",
            (ADMIN_PADRAO_USUARIO,
             ADMIN_PADRAO_EMAIL,
             gerar_hash(ADMIN_PADRAO_SENHA), agora()),
        )
    conexao.commit()


def conectar(caminho: Path | str | None = None) -> sqlite3.Connection:
    """Abre (criando e atualizando se necessário) o banco SQLite do projeto."""
    destino = Path(caminho) if caminho else CAMINHO_PADRAO
    if destino.parent and not destino.parent.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)

    conexao = sqlite3.connect(str(destino), check_same_thread=False)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.executescript(_ESQUEMA)
    _migrar(conexao)
    _semear(conexao)
    conexao.commit()
    return conexao


def garantir_esquema(conexao: sqlite3.Connection) -> sqlite3.Connection:
    """
    Aplica o esquema em uma conexão já aberta, **só se o banco estiver atrás**.

    A conexão é reaproveitada entre execuções do Streamlit
    (``st.cache_resource``), então o ``CREATE TABLE`` de ``conectar`` roda uma
    única vez por processo: um deploy que acrescente tabelas novas não
    recriaria a conexão, e as consultas falhariam com *no such table*. Aqui o
    ``PRAGMA user_version`` é conferido a cada execução e o esquema é aplicado
    quando a versão do banco é menor que a do código.
    """
    versao = conexao.execute("PRAGMA user_version").fetchone()[0]
    if versao == VERSAO_ESQUEMA:
        return conexao

    conexao.executescript(_ESQUEMA)
    _migrar(conexao)
    _semear(conexao)
    conexao.commit()
    return conexao


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------

_CAMPOS_PUBLICOS = ("id, usuario, nome, email, cpf, telefone, cidade, estado, "
                    "endereco, cep, origem, is_admin, ativo, plano_codigo, "
                    "modulo_fiscal, modulo_opcoes, criado_em")


def criar_usuario(conexao: sqlite3.Connection, usuario: str, email: str,
                  senha_hash: str, is_admin: bool = False,
                  plano_codigo: str = "free", nome: str | None = None,
                  cpf: str | None = None, origem: str | None = None) -> int:
    """Insere um usuário e devolve o ``id`` criado."""
    try:
        cur = conexao.execute(
            "INSERT INTO usuarios (usuario, email, hash, is_admin, ativo, plano_codigo, "
            " nome, cpf, origem, criado_em) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
            (usuario.strip(), email.strip().lower(), senha_hash,
             int(is_admin), plano_codigo, nome, cpf, origem, agora()),
        )
    except sqlite3.IntegrityError as erro:
        raise ValueError("usuário, e-mail ou CPF já cadastrado") from erro
    conexao.commit()
    return int(cur.lastrowid)


def usuario_em_uso(conexao: sqlite3.Connection, usuario: str) -> bool:
    """Diz se o apelido de login já pertence a alguém (usado ao gerar um novo)."""
    return conexao.execute("SELECT 1 FROM usuarios WHERE usuario = ?",
                           (usuario,)).fetchone() is not None


def obter_usuario(conexao: sqlite3.Connection, usuario_id: int):
    """Linha do usuário (sem o hash) ou ``None``."""
    colunas = ", ".join(_CAMPOS_PUBLICOS.split(", "))
    return conexao.execute(
        f"SELECT {colunas} FROM usuarios WHERE id = ?", (int(usuario_id),)
    ).fetchone()


def obter_por_login(conexao: sqlite3.Connection, login: str):
    """Linha **com hash**, buscando por usuário, e-mail ou CPF (usado no login)."""
    limpo = (login or "").strip()
    digitos = "".join(c for c in limpo if c.isdigit())
    return conexao.execute(
        "SELECT id, usuario, nome, email, cpf, hash, is_admin, ativo, plano_codigo, "
        "       modulo_fiscal, modulo_opcoes, criado_em "
        "FROM usuarios WHERE usuario = ? OR email = ? OR (cpf IS NOT NULL AND cpf = ?)",
        (limpo, limpo.lower(), digitos),
    ).fetchone()


def obter_por_email(conexao: sqlite3.Connection, email: str):
    return conexao.execute(
        "SELECT id, usuario, nome, email, cpf, hash, is_admin, ativo, plano_codigo, "
        "       modulo_fiscal, modulo_opcoes, criado_em "
        "FROM usuarios WHERE email = ?", (email.strip().lower(),)
    ).fetchone()


def listar_usuarios(conexao: sqlite3.Connection) -> pd.DataFrame:
    """Todos os usuários, com o nome do plano (para o painel administrativo)."""
    return pd.read_sql_query(
        "SELECT u.id, u.usuario, u.nome, u.email, u.cpf, u.origem, "
        "       u.plano_codigo AS plano, p.nome AS plano_nome, "
        "       u.is_admin, u.ativo, u.modulo_fiscal, u.modulo_opcoes, u.criado_em "
        "FROM usuarios u LEFT JOIN planos p ON p.codigo = u.plano_codigo "
        "ORDER BY u.id",
        conexao,
    )


def atualizar_usuario(conexao: sqlite3.Connection, usuario_id: int, **campos) -> None:
    """Atualiza os campos informados de um usuário (usuario, email, hash, ativo...)."""
    permitidos = {"usuario", "email", "hash", "is_admin", "ativo", "plano_codigo",
                  "nome", "cpf", "telefone", "cidade", "estado", "endereco", "cep",
                  "origem", "reset_token", "reset_expira", "modulo_fiscal", "modulo_opcoes"}
    itens = {k: v for k, v in campos.items() if k in permitidos}
    if not itens:
        return
    if "email" in itens:
        itens["email"] = str(itens["email"]).strip().lower()
    atribuicoes = ", ".join(f"{k} = ?" for k in itens)
    try:
        conexao.execute(
            f"UPDATE usuarios SET {atribuicoes} WHERE id = ?",
            (*itens.values(), int(usuario_id)),
        )
    except sqlite3.IntegrityError as erro:
        raise ValueError("usuário ou e-mail já cadastrado") from erro
    conexao.commit()


def contar_usuarios(conexao: sqlite3.Connection) -> dict:
    """Contagens usadas no dashboard administrativo."""
    total = conexao.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    pagos = conexao.execute(
        "SELECT COUNT(*) FROM usuarios WHERE plano_codigo <> 'free'").fetchone()[0]
    ativos = conexao.execute(
        "SELECT COUNT(*) FROM usuarios WHERE ativo = 1").fetchone()[0]
    return {"total": total, "pagos": pagos, "free": total - pagos,
            "ativos": ativos, "inativos": total - ativos}


# ---------------------------------------------------------------------------
# Planos
# ---------------------------------------------------------------------------

def listar_planos(conexao: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT codigo, nome, preco_mensal, limite_notas, exporta_excel, descricao "
        "FROM planos ORDER BY preco_mensal",
        conexao,
    )


def obter_plano(conexao: sqlite3.Connection, codigo: str):
    return conexao.execute(
        "SELECT codigo, nome, preco_mensal, limite_notas, exporta_excel, descricao "
        "FROM planos WHERE codigo = ?", (codigo,)
    ).fetchone()


# ---------------------------------------------------------------------------
# Assinaturas e pagamentos
# ---------------------------------------------------------------------------

def criar_assinatura(conexao: sqlite3.Connection, usuario_id: int, plano_codigo: str,
                     valor_pago: float, forma: str, cupom_codigo: str | None = None,
                     meses: int = 1) -> int:
    """Registra a assinatura, encerrando a anterior do mesmo usuário."""
    from calendar import monthrange
    from datetime import date

    hoje = date.today()
    mes_fim = hoje.month - 1 + meses
    fim = date(hoje.year + mes_fim // 12, mes_fim % 12 + 1,
               min(hoje.day, monthrange(hoje.year + mes_fim // 12, mes_fim % 12 + 1)[1]))

    conexao.execute(
        "UPDATE assinaturas SET status = 'substituida' "
        "WHERE usuario_id = ? AND status = 'ativa'", (int(usuario_id),))
    cur = conexao.execute(
        "INSERT INTO assinaturas "
        "(usuario_id, plano_codigo, status, inicio, fim, valor_pago, cupom_codigo, "
        " forma_pagamento, criado_em) VALUES (?, ?, 'ativa', ?, ?, ?, ?, ?, ?)",
        (int(usuario_id), plano_codigo, hoje.isoformat(), fim.isoformat(),
         float(valor_pago), cupom_codigo, forma, agora()),
    )
    conexao.execute("UPDATE usuarios SET plano_codigo = ? WHERE id = ?",
                    (plano_codigo, int(usuario_id)))
    conexao.commit()
    return int(cur.lastrowid)


def assinatura_ativa(conexao: sqlite3.Connection, usuario_id: int):
    return conexao.execute(
        "SELECT a.*, p.nome AS plano_nome FROM assinaturas a "
        "LEFT JOIN planos p ON p.codigo = a.plano_codigo "
        "WHERE a.usuario_id = ? AND a.status = 'ativa' "
        "ORDER BY a.id DESC LIMIT 1", (int(usuario_id),)
    ).fetchone()


def listar_assinaturas(conexao: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT a.id, u.usuario, a.plano_codigo AS plano, p.nome AS plano_nome, "
        "       a.status, a.inicio, a.fim, a.valor_pago, a.cupom_codigo, "
        "       a.forma_pagamento, a.criado_em "
        "FROM assinaturas a "
        "JOIN usuarios u ON u.id = a.usuario_id "
        "LEFT JOIN planos p ON p.codigo = a.plano_codigo "
        "ORDER BY a.id DESC",
        conexao,
    )


def cancelar_assinatura(conexao: sqlite3.Connection, usuario_id: int) -> None:
    """Cancela a assinatura vigente e devolve o usuário ao plano gratuito."""
    conexao.execute("UPDATE assinaturas SET status = 'cancelada' "
                    "WHERE usuario_id = ? AND status = 'ativa'", (int(usuario_id),))
    conexao.execute("UPDATE usuarios SET plano_codigo = 'free' WHERE id = ?",
                    (int(usuario_id),))
    conexao.commit()


def registrar_pagamento(conexao: sqlite3.Connection, usuario_id: int, assinatura_id: int,
                        valor: float, desconto: float, valor_final: float,
                        forma: str, referencia: str,
                        status: str = "pago") -> int:
    cur = conexao.execute(
        "INSERT INTO pagamentos "
        "(usuario_id, assinatura_id, valor, desconto, valor_final, forma, status, "
        " referencia, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (int(usuario_id), int(assinatura_id), float(valor), float(desconto),
         float(valor_final), forma, status, referencia, agora()),
    )
    conexao.commit()
    return int(cur.lastrowid)


def listar_pagamentos(conexao: sqlite3.Connection,
                      usuario_id: int | None = None) -> pd.DataFrame:
    """Pagamentos; com ``usuario_id``, apenas os do próprio usuário."""
    if usuario_id is not None:
        return pd.read_sql_query(
            "SELECT id, valor, desconto, valor_final AS valor_pago, forma, status, "
            "       referencia, criado_em "
            "FROM pagamentos WHERE usuario_id = ? ORDER BY id DESC",
            conexao, params=(int(usuario_id),),
        )
    return pd.read_sql_query(
        "SELECT pg.id, u.usuario, pg.valor, pg.desconto, pg.valor_final AS valor_pago, "
        "       pg.forma, pg.status, pg.referencia, pg.criado_em "
        "FROM pagamentos pg JOIN usuarios u ON u.id = pg.usuario_id "
        "ORDER BY pg.id DESC",
        conexao,
    )


def faturamento_total(conexao: sqlite3.Connection) -> float:
    linha = conexao.execute(
        "SELECT COALESCE(SUM(valor_final), 0) FROM pagamentos WHERE status = 'pago'"
    ).fetchone()
    return float(linha[0])


# ---------------------------------------------------------------------------
# Cupons de desconto
# ---------------------------------------------------------------------------

def criar_cupom(conexao: sqlite3.Connection, codigo: str, desconto_pct: float = 0.0,
                validade: str | None = None, uso_maximo: int = 0,
                tipo: str = "percentual", meses_gratis: int = 0) -> int:
    """
    Cria um cupom.

    ``tipo`` aceita ``"percentual"`` (desconto sobre a mensalidade) ou
    ``"meses"`` (meses grátis do plano, sem cobrança no checkout).
    """
    try:
        cur = conexao.execute(
            "INSERT INTO cupons (codigo, tipo, desconto_pct, meses_gratis, ativo, "
            " validade, uso_maximo, usos, criado_em) VALUES (?, ?, ?, ?, 1, ?, ?, 0, ?)",
            (codigo.strip().upper(), tipo, float(desconto_pct), int(meses_gratis),
             validade, int(uso_maximo), agora()),
        )
    except sqlite3.IntegrityError as erro:
        raise ValueError("já existe um cupom com esse código") from erro
    conexao.commit()
    return int(cur.lastrowid)


def listar_cupons(conexao: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id, codigo, tipo, desconto_pct, meses_gratis, ativo, validade, "
        "       uso_maximo, usos, criado_em "
        "FROM cupons ORDER BY id DESC",
        conexao,
    )


def obter_cupom(conexao: sqlite3.Connection, codigo: str):
    return conexao.execute(
        "SELECT * FROM cupons WHERE codigo = ?", (codigo.strip().upper(),)
    ).fetchone()


def definir_cupom_ativo(conexao: sqlite3.Connection, cupom_id: int, ativo: bool) -> None:
    conexao.execute("UPDATE cupons SET ativo = ? WHERE id = ?",
                    (int(ativo), int(cupom_id)))
    conexao.commit()


def registrar_uso_cupom(conexao: sqlite3.Connection, codigo: str) -> None:
    conexao.execute("UPDATE cupons SET usos = usos + 1 WHERE codigo = ?",
                    (codigo.strip().upper(),))
    conexao.commit()


# ---------------------------------------------------------------------------
# Parceiros e indicações
# ---------------------------------------------------------------------------

def criar_parceiro(conexao: sqlite3.Connection, nome: str, codigo: str,
                   comissao_pct: float = 0.0, beneficio_tipo: str = "percentual",
                   beneficio_valor: float = 0.0, email: str | None = None) -> int:
    """
    Cadastra um parceiro.

    ``comissao_pct`` é o quanto ele recebe sobre o que os indicados gastam;
    ``beneficio_tipo``/``beneficio_valor`` é o que o **indicado** ganha no
    primeiro checkout (``"percentual"`` em % ou ``"meses"`` de plano grátis).
    """
    try:
        cur = conexao.execute(
            "INSERT INTO parceiros (nome, email, codigo, comissao_pct, beneficio_tipo, "
            " beneficio_valor, ativo, criado_em) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (nome.strip(), (email or "").strip().lower() or None,
             codigo.strip().upper(), float(comissao_pct), beneficio_tipo,
             float(beneficio_valor), agora()),
        )
    except sqlite3.IntegrityError as erro:
        raise ValueError("já existe um parceiro com esse código") from erro
    conexao.commit()
    return int(cur.lastrowid)


def listar_parceiros(conexao: sqlite3.Connection,
                     somente_ativos: bool = False) -> pd.DataFrame:
    """Parceiros com o número de indicados e o total já faturado por eles."""
    filtro = "WHERE pa.ativo = 1" if somente_ativos else ""
    return pd.read_sql_query(
        "SELECT pa.id, pa.nome, pa.codigo, pa.email, "
        "       pa.comissao_pct, pa.beneficio_tipo, pa.beneficio_valor, pa.ativo, "
        "       COUNT(i.id) AS indicados, "
        "       COALESCE(SUM(pg.total), 0) AS faturado_indicados, "
        "       pa.criado_em "
        "FROM parceiros pa "
        "LEFT JOIN indicacoes i ON i.parceiro_id = pa.id "
        "LEFT JOIN (SELECT usuario_id, SUM(valor_final) AS total FROM pagamentos "
        "           WHERE status = 'pago' GROUP BY usuario_id) pg "
        "       ON pg.usuario_id = i.usuario_id "
        f"{filtro} "
        "GROUP BY pa.id ORDER BY pa.id DESC",
        conexao,
    )


def obter_parceiro(conexao: sqlite3.Connection, parceiro_id: int):
    return conexao.execute("SELECT * FROM parceiros WHERE id = ?",
                           (int(parceiro_id),)).fetchone()


def obter_parceiro_por_codigo(conexao: sqlite3.Connection, codigo: str):
    return conexao.execute("SELECT * FROM parceiros WHERE codigo = ?",
                           (codigo.strip().upper(),)).fetchone()


def definir_parceiro_ativo(conexao: sqlite3.Connection, parceiro_id: int,
                           ativo: bool) -> None:
    conexao.execute("UPDATE parceiros SET ativo = ? WHERE id = ?",
                    (int(ativo), int(parceiro_id)))
    conexao.commit()


def registrar_indicacao(conexao: sqlite3.Connection, usuario_id: int,
                        parceiro_id: int) -> int:
    """Liga uma conta nova ao parceiro que a indicou (uma indicação por conta)."""
    try:
        cur = conexao.execute(
            "INSERT INTO indicacoes (usuario_id, parceiro_id, beneficio_usado, criado_em) "
            "VALUES (?, ?, 0, ?)", (int(usuario_id), int(parceiro_id), agora()))
    except sqlite3.IntegrityError as erro:
        raise ValueError("esta conta já tem uma indicação registrada") from erro
    conexao.commit()
    return int(cur.lastrowid)


def obter_indicacao(conexao: sqlite3.Connection, usuario_id: int):
    """Indicação da conta, com os dados do parceiro, ou ``None``."""
    return conexao.execute(
        "SELECT i.id, i.usuario_id, i.parceiro_id, i.beneficio_usado, i.criado_em, "
        "       pa.nome AS parceiro_nome, pa.codigo AS parceiro_codigo, "
        "       pa.comissao_pct, pa.beneficio_tipo, pa.beneficio_valor, pa.ativo AS parceiro_ativo "
        "FROM indicacoes i JOIN parceiros pa ON pa.id = i.parceiro_id "
        "WHERE i.usuario_id = ?", (int(usuario_id),)
    ).fetchone()


def marcar_beneficio_usado(conexao: sqlite3.Connection, usuario_id: int) -> None:
    """Marca o benefício da indicação como consumido (usado uma única vez)."""
    conexao.execute("UPDATE indicacoes SET beneficio_usado = 1 WHERE usuario_id = ?",
                    (int(usuario_id),))
    conexao.commit()


def listar_indicacoes(conexao: sqlite3.Connection,
                      parceiro_id: int | None = None) -> pd.DataFrame:
    """Indicações com o nome da conta, do parceiro e quanto ela já gastou."""
    condicao = "WHERE i.parceiro_id = ?" if parceiro_id is not None else ""
    parametros = (int(parceiro_id),) if parceiro_id is not None else ()
    return pd.read_sql_query(
        "SELECT i.id, u.usuario, u.nome, u.email, pa.nome AS parceiro, "
        "       i.beneficio_usado, COALESCE(pg.total, 0) AS total_gasto, i.criado_em "
        "FROM indicacoes i "
        "JOIN usuarios u ON u.id = i.usuario_id "
        "JOIN parceiros pa ON pa.id = i.parceiro_id "
        "LEFT JOIN (SELECT usuario_id, SUM(valor_final) AS total FROM pagamentos "
        "           WHERE status = 'pago' GROUP BY usuario_id) pg "
        "       ON pg.usuario_id = i.usuario_id "
        f"{condicao} "
        "ORDER BY i.id DESC",
        conexao,
    )


# ---------------------------------------------------------------------------
# Notas fiscais
# ---------------------------------------------------------------------------

def registrar_nota_fiscal(conexao: sqlite3.Connection, usuario_id: int,
                          pagamento_id: int, valor: float) -> str:
    """Emite um número sequencial de nota fiscal para o pagamento."""
    numero = conexao.execute("SELECT COUNT(*) FROM notas_fiscais").fetchone()[0] + 1
    referencia = f"NF-{datetime.now():%Y%m}-{numero:05d}"
    conexao.execute(
        "INSERT INTO notas_fiscais (usuario_id, pagamento_id, numero, valor, data) "
        "VALUES (?, ?, ?, ?, ?)",
        (int(usuario_id), int(pagamento_id), referencia, float(valor), agora()),
    )
    conexao.commit()
    return referencia


def listar_notas_fiscais(conexao: sqlite3.Connection, usuario_id: int | None = None) -> pd.DataFrame:
    if usuario_id is None:
        consulta = ("SELECT nf.id, u.usuario, nf.numero, nf.valor, nf.data "
                    "FROM notas_fiscais nf JOIN usuarios u ON u.id = nf.usuario_id "
                    "ORDER BY nf.id DESC")
        return pd.read_sql_query(consulta, conexao)
    return pd.read_sql_query(
        "SELECT id, numero, valor, data FROM notas_fiscais "
        "WHERE usuario_id = ? ORDER BY id DESC", conexao, params=(int(usuario_id),))


# ---------------------------------------------------------------------------
# Configuração dos métodos de pagamento
# ---------------------------------------------------------------------------

def obter_config_pagamento(conexao: sqlite3.Connection) -> dict:
    linha = conexao.execute("SELECT * FROM config_pagamento WHERE id = 1").fetchone()
    if linha is None:
        return {}
    return dict(linha)


def gravar_config_pagamento(conexao: sqlite3.Connection, dados: dict) -> None:
    conexao.execute(
        "INSERT INTO config_pagamento "
        "(id, pix_chave, pix_recebedor, cartao_provedor, cartao_api_key, "
        " cartao_public_key, ambiente, atualizado_em) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "  pix_chave = excluded.pix_chave,"
        "  pix_recebedor = excluded.pix_recebedor,"
        "  cartao_provedor = excluded.cartao_provedor,"
        "  cartao_api_key = excluded.cartao_api_key,"
        "  cartao_public_key = excluded.cartao_public_key,"
        "  ambiente = excluded.ambiente,"
        "  atualizado_em = excluded.atualizado_em",
        (
            dados.get("pix_chave"), dados.get("pix_recebedor"),
            dados.get("cartao_provedor"), dados.get("cartao_api_key"),
            dados.get("cartao_public_key"), dados.get("ambiente", "simulado"),
            agora(),
        ),
    )
    conexao.commit()


# ---------------------------------------------------------------------------
# Notas e operações (por usuário)
# ---------------------------------------------------------------------------

def _hash_operacao(chave: str, ocorrencia: int) -> str:
    return hashlib.sha1(f"{chave}#{ocorrencia}".encode("utf-8")).hexdigest()


def salvar_notas(conexao: sqlite3.Connection, notas: list[Nota],
                 usuario_id: int) -> tuple[int, int]:
    """
    Grava as notas e suas operações para o usuário.

    Retorna ``(notas_novas, operacoes_novas)``. Notas já existentes (mesmo
    usuário + número + data) são ignoradas — é isso que evita contar em
    dobro as notas que aparecem em mais de um PDF exportado ou reimportadas com
    rótulo de corretora corrigido.
    """
    notas_novas = 0
    ops_novas = 0

    for nota in notas:
        # A folha distingue as páginas de uma nota multi-página; a 1ª folha (ou
        # a única) vale "1", alinhado ao valor gravado pela migração v6.
        folha = nota.folha or "1"
        data_iso = nota.data.isoformat() if nota.data else None

        # 1. Verifica se esta mesma nota (mesmo número, folha e data) já existe para o usuário
        existente = conexao.execute(
            "SELECT id, corretora FROM notas "
            "WHERE usuario_id = ? AND numero = ? AND folha = ? AND (data = ? OR (? IS NULL AND data IS NULL))",
            (int(usuario_id), str(nota.numero), folha, data_iso, data_iso),
        ).fetchone()

        if existente is not None:
            corretora_existente = existente["corretora"]
            # Se a nota existente foi gravada com 'XP Investimentos' (ou genérica) e agora
            # foi identificada com a corretora correta (ex: 'Genial'), atualiza a corretora
            if corretora_existente != nota.corretora and nota.corretora not in ("Genérico (SINACOR)", "XP Investimentos"):
                conexao.execute(
                    "UPDATE notas SET corretora = ? WHERE id = ?",
                    (nota.corretora, existente["id"]),
                )
                conexao.execute(
                    "UPDATE operacoes SET corretora = ? "
                    "WHERE usuario_id = ? AND nota = ? AND folha = ?",
                    (nota.corretora, int(usuario_id), str(nota.numero), folha),
                )
        else:
            categoria_irrf = (
                "DayTrade"
                if nota.operacoes and all(op.day_trade for op in nota.operacoes)
                else "SwingTrade"
            )
            cur = conexao.execute(
                "INSERT OR IGNORE INTO notas "
                "(usuario_id, numero, corretora, folha, data, arquivo, despesas, irrf, categoria_irrf) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(usuario_id),
                    nota.numero,
                    nota.corretora,
                    folha,
                    data_iso,
                    nota.arquivo,
                    nota.despesas,
                    nota.irrf,
                    categoria_irrf,
                ),
            )
            if cur.rowcount > 0:
                notas_novas += 1

        ocorrencias: dict[str, int] = {}
        for op in nota.operacoes:
            chave = "|".join(str(p) for p in (
                op.corretora, op.nota, op.folha or "1", op.data, op.tipo, op.ticker,
                op.quantidade, op.preco, op.valor_total, op.resultado,
            ))
            indice = ocorrencias.get(chave, 0)
            ocorrencias[chave] = indice + 1

            cur = conexao.execute(
                "INSERT OR IGNORE INTO operacoes "
                "(usuario_id, hash, corretora, nota, folha, data, tipo, ticker, quantidade, "
                " preco, valor_total, mercado, taxas, irrf, resultado, day_trade, obs, arquivo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(usuario_id),
                    _hash_operacao(chave, indice),
                    op.corretora, op.nota, op.folha or "1",
                    op.data.isoformat() if op.data else None,
                    op.tipo, op.ticker, op.quantidade, op.preco, op.valor_total,
                    op.mercado, op.taxas, op.irrf, op.resultado,
                    int(op.day_trade), op.obs, op.arquivo,
                ),
            )
            ops_novas += cur.rowcount

    conexao.commit()
    return notas_novas, ops_novas


def sanitizar_duplicatas(conexao: sqlite3.Connection, usuario_id: int) -> dict[str, int]:
    """
    Remove notas e operações duplicadas do usuário (ex: quando as mesmas notas
    foram importadas com corretoras diferentes, como 'XP Investimentos' e 'Genial',
    ou múltiplos uploads com sobreposição mensal vs diária).

    Garante que para cada (numero, folha, data) exista apenas uma nota,
    privilegiando a corretora correta (Genial, etc.), e eliminando
    operações duplicadas no cálculo do IR.
    """
    usuario_id = int(usuario_id)
    removidas_notas = 0
    removidas_ops = 0
    corrigidas = 0

    # 1. Agrupar notas por (numero, folha, data)
    linhas = conexao.execute(
        "SELECT id, numero, corretora, folha, data, arquivo FROM notas "
        "WHERE usuario_id = ? ORDER BY id ASC",
        (usuario_id,),
    ).fetchall()

    grupos: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
    for r in linhas:
        chave = (str(r["numero"]), str(r["folha"] or "1"), str(r["data"] or ""))
        grupos.setdefault(chave, []).append(r)

    for chave, lista_notas in grupos.items():
        if len(lista_notas) > 1:
            # Seleciona a melhor: prefere uma que NÃO seja "XP Investimentos" se houver outra
            melhor = None
            for n in lista_notas:
                if n["corretora"] not in ("XP Investimentos", "Genérico (SINACOR)"):
                    melhor = n
                    break
            if melhor is None:
                melhor = lista_notas[0]

            for n in lista_notas:
                if n["id"] != melhor["id"]:
                    conexao.execute("DELETE FROM notas WHERE id = ?", (n["id"],))
                    if n["corretora"] != melhor["corretora"]:
                        conexao.execute(
                            "DELETE FROM operacoes "
                            "WHERE usuario_id = ? AND corretora = ? AND nota = ? AND folha = ?",
                            (usuario_id, n["corretora"], n["numero"], n["folha"]),
                        )
                    removidas_notas += 1

    # 2. Corrigir corretora de notas remanescentes se usuário só opera na Genial
    notas_xp = conexao.execute(
        "SELECT id, numero, folha FROM notas WHERE usuario_id = ? AND corretora IN ('XP Investimentos', 'Genérico (SINACOR)')",
        (usuario_id,),
    ).fetchall()
    notas_genial = conexao.execute(
        "SELECT count(*) as c FROM notas WHERE usuario_id = ? AND corretora = 'Genial'",
        (usuario_id,),
    ).fetchone()
    if notas_xp and notas_genial and notas_genial["c"] > 0:
        for nxp in notas_xp:
            conexao.execute(
                "UPDATE notas SET corretora = 'Genial' WHERE id = ?", (nxp["id"],)
            )
            conexao.execute(
                "UPDATE operacoes SET corretora = 'Genial' WHERE usuario_id = ? AND nota = ? AND folha = ?",
                (usuario_id, nxp["numero"], nxp["folha"]),
            )
            corrigidas += 1

    conexao.commit()
    return {
        "notas_removidas": removidas_notas,
        "operacoes_removidas": 0,
        "corretoras_corrigidas": corrigidas,
    }


def limpar_dados(conexao: sqlite3.Connection, usuario_id: int) -> None:
    """Apaga notas, operações, proventos e DARFs pagos **do usuário** (mantém os prejuízos)."""
    for tabela in ("operacoes", "notas", "proventos", "darf_pagamentos"):
        conexao.execute(f"DELETE FROM {tabela} WHERE usuario_id = ?", (int(usuario_id),))
    conexao.commit()


def remover_notas(conexao: sqlite3.Connection, usuario_id: int,
                  chaves: list[tuple[str, str, str]]) -> int:
    """
    Apaga as notas indicadas e as operações que vieram delas.

    ``chaves`` é uma lista de ``(corretora, número da nota, folha)`` — a mesma
    chave que identifica a nota na importação. Retorna quantas notas foram
    removidas.
    """
    removidas = 0
    for corretora, numero, folha in chaves:
        cur = conexao.execute(
            "DELETE FROM notas "
            "WHERE usuario_id = ? AND corretora = ? AND numero = ? AND folha = ?",
            (int(usuario_id), str(corretora), str(numero), str(folha)),
        )
        removidas += cur.rowcount
        conexao.execute(
            "DELETE FROM operacoes "
            "WHERE usuario_id = ? AND corretora = ? AND nota = ? AND folha = ?",
            (int(usuario_id), str(corretora), str(numero), str(folha)),
        )
    conexao.commit()
    return removidas


def carregar_operacoes(conexao: sqlite3.Connection, usuario_id: int) -> pd.DataFrame:
    """DataFrame com as operações do usuário."""
    return pd.read_sql_query(
        "SELECT data, tipo, ticker, quantidade, preco, valor_total, mercado, "
        "       taxas, irrf, resultado, day_trade, nota, folha, corretora, arquivo, obs "
        "FROM operacoes WHERE usuario_id = ? ORDER BY data, nota, folha, id",
        conexao, params=(int(usuario_id),),
    )


def carregar_notas(conexao: sqlite3.Connection, usuario_id: int) -> pd.DataFrame:
    """DataFrame com as notas do usuário (usado para o IRRF retido)."""
    return pd.read_sql_query(
        "SELECT numero, corretora, folha, data, arquivo, despesas, irrf, categoria_irrf "
        "FROM notas WHERE usuario_id = ? ORDER BY data, numero, folha",
        conexao, params=(int(usuario_id),),
    )


def resumo_importacao(conexao: sqlite3.Connection, usuario_id: int) -> dict:
    """Contagens exibidas na página de upload."""
    parametro = (int(usuario_id),)
    notas = conexao.execute(
        "SELECT COUNT(*) FROM notas WHERE usuario_id = ?", parametro).fetchone()[0]
    operacoes = conexao.execute(
        "SELECT COUNT(*) FROM operacoes WHERE usuario_id = ?", parametro).fetchone()[0]
    arquivos = conexao.execute(
        "SELECT COUNT(DISTINCT arquivo) FROM notas WHERE usuario_id = ?",
        parametro).fetchone()[0]
    return {"notas": notas, "operacoes": operacoes, "arquivos": arquivos}


def contar_notas(conexao: sqlite3.Connection, usuario_id: int) -> int:
    return int(conexao.execute(
        "SELECT COUNT(*) FROM notas WHERE usuario_id = ?", (int(usuario_id),)
    ).fetchone()[0])


# ---------------------------------------------------------------------------
# Prejuízos anteriores a compensar
# ---------------------------------------------------------------------------

def ler_prejuizos(conexao: sqlite3.Connection, usuario_id: int) -> dict:
    """Saldo de prejuízo anterior a compensar, por bucket, do usuário."""
    linha = conexao.execute(
        "SELECT * FROM prejuizos_anteriores WHERE usuario_id = ?", (int(usuario_id),)
    ).fetchone()
    if linha is None:
        return {"data": None, "DayTrade": 0.0, "SwingTrade": 0.0, "FII": 0.0,
                "ir_swing": 0.0, "ir_day": 0.0}
    return {
        "data": linha["data"],
        "DayTrade": linha["previous_loss_day"],
        "SwingTrade": linha["previous_loss_swing"],
        "FII": linha["previous_loss_fii"],
        "ir_swing": linha["ir_swing"],
        "ir_day": linha["ir_day"],
    }


def gravar_prejuizos(conexao: sqlite3.Connection, usuario_id: int, dados: dict) -> None:
    """Grava (substituindo) o saldo de prejuízo anterior a compensar do usuário."""
    conexao.execute(
        "INSERT INTO prejuizos_anteriores "
        "(usuario_id, data, previous_loss_fii, previous_loss_swing, previous_loss_day, "
        " ir_swing, ir_day) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(usuario_id) DO UPDATE SET "
        "  data = excluded.data,"
        "  previous_loss_fii = excluded.previous_loss_fii,"
        "  previous_loss_swing = excluded.previous_loss_swing,"
        "  previous_loss_day = excluded.previous_loss_day,"
        "  ir_swing = excluded.ir_swing,"
        "  ir_day = excluded.ir_day",
        (
            int(usuario_id),
            dados.get("data"),
            float(dados.get("FII", 0.0) or 0.0),
            float(dados.get("SwingTrade", 0.0) or 0.0),
            float(dados.get("DayTrade", 0.0) or 0.0),
            float(dados.get("ir_swing", 0.0) or 0.0),
            float(dados.get("ir_day", 0.0) or 0.0),
        ),
    )
    conexao.commit()


# ---------------------------------------------------------------------------
# Proventos (por usuário)
# ---------------------------------------------------------------------------

def carregar_proventos(conexao: sqlite3.Connection, usuario_id: int) -> pd.DataFrame:
    """Proventos do usuário, importados do extrato ou lançados manualmente."""
    return pd.read_sql_query(
        "SELECT id, data, ticker, tipo, quantidade, valor FROM proventos "
        "WHERE usuario_id = ? ORDER BY data",
        conexao, params=(int(usuario_id),),
    )


def salvar_proventos(conexao: sqlite3.Connection, usuario_id: int, registros) -> int:
    """
    Grava proventos deduplicando por ``(data, ticker, tipo, quantidade, valor)``.

    Reimportar o mesmo extrato não duplica linhas: para cada chave, só as
    ocorrências que excedem as já gravadas são inseridas — o mesmo critério de
    contagem usado nas operações. Retorna quantas linhas foram gravadas.
    """
    contagem: dict[tuple, int] = {}
    for linha in conexao.execute(
        "SELECT data, ticker, tipo, quantidade, valor, COUNT(*) AS total "
        "FROM proventos WHERE usuario_id = ? "
        "GROUP BY data, ticker, tipo, quantidade, valor", (int(usuario_id),)
    ):
        existente = (
            str(linha["data"]),
            str(linha["ticker"]).strip().upper(),
            str(linha["tipo"]),
            round(float(linha["quantidade"]), 8),
            round(float(linha["valor"]), 2),
        )
        contagem[existente] = contagem.get(existente, 0) + int(linha["total"])

    gravados = 0
    for registro in registros:
        chave = (
            str(registro["data"]),
            str(registro["ticker"]).strip().upper(),
            str(registro["tipo"]),
            round(float(registro["quantidade"]), 8),
            round(float(registro["valor"]), 2),
        )
        if contagem.get(chave, 0) > 0:
            contagem[chave] -= 1                 # linha já existia no banco
            continue

        conexao.execute(
            "INSERT INTO proventos (usuario_id, data, ticker, tipo, quantidade, valor) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (int(usuario_id), *chave),
        )
        gravados += 1

    conexao.commit()
    return gravados


def adicionar_provento(conexao: sqlite3.Connection, usuario_id: int, data: str,
                       ticker: str, tipo: str, quantidade: float, valor: float) -> None:
    """Registra um provento (dividendo, JCP, rendimento ou amortização)."""
    conexao.execute(
        "INSERT INTO proventos (usuario_id, data, ticker, tipo, quantidade, valor) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (int(usuario_id), data, ticker.upper(), tipo, float(quantidade), float(valor)),
    )
    conexao.commit()


def remover_provento(conexao: sqlite3.Connection, usuario_id: int,
                     identificador: int) -> None:
    """Remove um provento do usuário pelo seu id."""
    conexao.execute("DELETE FROM proventos WHERE id = ? AND usuario_id = ?",
                    (int(identificador), int(usuario_id)))
    conexao.commit()


# ---------------------------------------------------------------------------
# Pagamento do DARF (por usuário e competência)
# ---------------------------------------------------------------------------

def carregar_darf_pagamentos(conexao: sqlite3.Connection,
                             usuario_id: int) -> dict[str, dict]:
    """
    Controle de pagamento do DARF, por competência (``"AAAA-MM"``).

    Devolve ``{competencia: {"pago", "valor_pago", "data_pagamento"}}``.
    """
    linhas = conexao.execute(
        "SELECT competencia, pago, valor_pago, data_pagamento FROM darf_pagamentos "
        "WHERE usuario_id = ?",
        (int(usuario_id),),
    ).fetchall()
    return {
        linha["competencia"]: {
            "pago": bool(linha["pago"]),
            "valor_pago": float(linha["valor_pago"] or 0.0),
            "data_pagamento": linha["data_pagamento"],
        }
        for linha in linhas
    }


def gravar_darf_pagamento(conexao: sqlite3.Connection, usuario_id: int,
                          competencia: str, pago: bool, valor_pago: float = 0.0,
                          data_pagamento: str | None = None) -> None:
    """Marca (substituindo) o pagamento do DARF de uma competência."""
    conexao.execute(
        "INSERT INTO darf_pagamentos "
        "(usuario_id, competencia, pago, valor_pago, data_pagamento, atualizado_em) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(usuario_id, competencia) DO UPDATE SET "
        "  pago = excluded.pago,"
        "  valor_pago = excluded.valor_pago,"
        "  data_pagamento = excluded.data_pagamento,"
        "  atualizado_em = excluded.atualizado_em",
        (
            int(usuario_id),
            str(competencia),
            int(bool(pago)),
            float(valor_pago or 0.0),
            data_pagamento or None,
            agora(),
        ),
    )
    conexao.commit()


# ---------------------------------------------------------------------------
# Parâmetros fiscais (globais, editáveis no painel administrativo)
# ---------------------------------------------------------------------------

def carregar_parametros_fiscais(conexao: sqlite3.Connection) -> dict[str, str]:
    """Parâmetros do motor fiscal gravados no banco (``{chave: valor}``)."""
    linhas = conexao.execute(
        "SELECT chave, valor FROM parametros_fiscais").fetchall()
    return {linha["chave"]: linha["valor"] for linha in linhas}


def gravar_parametros_fiscais(conexao: sqlite3.Connection,
                              dados: dict[str, str]) -> None:
    """Grava (substituindo) os parâmetros do motor fiscal."""
    conexao.executemany(
        "INSERT INTO parametros_fiscais (chave, valor, atualizado_em) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET "
        "  valor = excluded.valor, atualizado_em = excluded.atualizado_em",
        [(str(chave), str(valor), agora()) for chave, valor in dados.items()],
    )
    conexao.commit()


# ---------------------------------------------------------------------------
# Monitor de legislação
# ---------------------------------------------------------------------------

def carregar_monitor_legislacao(conexao: sqlite3.Connection) -> dict[str, dict]:
    """Última verificação conhecida de cada fonte oficial, indexada pela URL."""
    linhas = conexao.execute("SELECT * FROM monitor_legislacao").fetchall()
    return {linha["url"]: dict(linha) for linha in linhas}


def gravar_monitor_legislacao(conexao: sqlite3.Connection, url: str, titulo: str,
                              hash_conteudo: str | None, mudou: bool) -> None:
    """
    Atualiza a verificação de uma fonte oficial.

    ``mudou_em`` só é reescrito quando há mudança; nas verificações em que nada
    mudou, a data da última alteração é preservada para o painel poder
    destacá-la.
    """
    momento = agora()
    conexao.execute(
        "INSERT INTO monitor_legislacao (url, titulo, hash, verificado_em, mudou_em) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(url) DO UPDATE SET "
        "  titulo = excluded.titulo,"
        "  hash = excluded.hash,"
        "  verificado_em = excluded.verificado_em,"
        "  mudou_em = CASE WHEN excluded.mudou_em IS NULL "
        "                  THEN monitor_legislacao.mudou_em "
        "                  ELSE excluded.mudou_em END",
        (str(url), titulo, hash_conteudo, momento, momento if mudou else None),
    )
    conexao.commit()


# ---------------------------------------------------------------------------
# Módulo Opções & Diário de Trades
# ---------------------------------------------------------------------------

def identificar_opcao(codigo: str) -> dict:
    """
    Identifica ativo base, tipo (CALL/PUT) e mês de vencimento a partir do ticker B3.
    Ex: BOVAI42 -> BOVA11, CALL, Setembro
        PETRU427 -> PETR4, PUT, Setembro
        BEEFX287 -> BEEF3, PUT, Dezembro
    """
    import re
    cod = (codigo or "").strip().upper()
    meses_call = {
        'A': 'Janeiro', 'B': 'Fevereiro', 'C': 'Março', 'D': 'Abril',
        'E': 'Maio', 'F': 'Junho', 'G': 'Julho', 'H': 'Agosto',
        'I': 'Setembro', 'J': 'Outubro', 'K': 'Novembro', 'L': 'Dezembro'
    }
    meses_put = {
        'M': 'Janeiro', 'N': 'Fevereiro', 'O': 'Março', 'P': 'Abril',
        'Q': 'Maio', 'R': 'Junho', 'S': 'Julho', 'T': 'Agosto',
        'U': 'Setembro', 'V': 'Outubro', 'W': 'Novembro', 'X': 'Dezembro'
    }
    acoes_conhecidas = {
        "PETR": "PETR4", "VALE": "VALE3", "BOVA": "BOVA11", "BEEF": "BEEF3",
        "CSNA": "CSNA3", "USIM": "USIM5", "GGBR": "GGBR4", "RENT": "RENT3",
        "BRKM": "BRKM5", "BRAP": "BRAP4", "BPRAP": "BRAP4", "MBRF": "MBRF3",
        "MRBF": "MBRF3", "COGN": "COGN3", "PRIO": "PRIO3", "WEGE": "WEGE3",
        "MGLU": "MGLU3", "CMIN": "CMIN3", "BBAS": "BBAS3", "BBDC": "BBDC4",
        "ITUB": "ITUB4", "ITSA": "ITSA4", "SUZB": "SUZB3", "JBSS": "JBSS3",
        "RAIZ": "RAIZ4", "ELET": "ELET3", "EQTL": "EQTL3", "HAPV": "HAPV3",
    }
    m = re.match(r"^([A-Z]{3,5})([A-X])(.*)$", cod)
    if m:
        pref, letra, resto = m.groups()
        ativo = acoes_conhecidas.get(pref, f"{pref}3")
        if letra in meses_call:
            tipo = "CALL"
            mes = meses_call[letra]
        else:
            tipo = "PUT"
            mes = meses_put[letra]
        return {
            "codigo": cod,
            "ativo_subjacente": ativo,
            "tipo_opcao": tipo,
            "mes_vencimento": mes,
            "letra": letra,
        }
    return {
        "codigo": cod,
        "ativo_subjacente": cod,
        "tipo_opcao": "CALL",
        "mes_vencimento": "",
        "letra": "",
    }


def listar_opcoes_operacoes(conexao: sqlite3.Connection, usuario_id: int, status: str | None = None) -> list[dict]:
    """Lista as operações de opções do usuário, ordenadas por data de início descendente."""
    sql = "SELECT * FROM opcoes_operacoes WHERE usuario_id = ?"
    params: list = [int(usuario_id)]
    if status:
        sql += " AND status = ?"
        params.append(status.lower().strip())
    sql += " ORDER BY data_inicio DESC, id DESC"
    cur = conexao.execute(sql, params)
    colunas = [desc[0] for desc in cur.description]
    return [dict(zip(colunas, linha)) for linha in cur.fetchall()]


def salvar_opcao_operacao(conexao: sqlite3.Connection, usuario_id: int, dados: dict) -> int:
    """Insere uma nova operação de opção no diário."""
    info = identificar_opcao(dados.get("codigo", ""))
    codigo = info["codigo"]
    ativo = dados.get("ativo_subjacente") or info["ativo_subjacente"]
    tipo = dados.get("tipo_opcao") or info["tipo_opcao"]
    estrutura = dados.get("estrutura", "COMPRA DE CALL").strip().upper()
    data_inicio = dados.get("data_inicio") or agora()[:10]
    data_fim = dados.get("data_fim") or None
    dias = dados.get("dias")
    quantidade = float(dados.get("quantidade", 100))
    preco_pago = float(dados.get("preco_pago", 0.0))
    preco_recebido = float(dados.get("preco_recebido", 0.0))
    preco_atual = float(dados.get("preco_atual", preco_pago))
    valor_alocado = float(dados.get("valor_alocado") or (quantidade * preco_pago if preco_pago > 0 else 0.0))
    valor_final = float(dados.get("valor_final") or (quantidade * preco_recebido if preco_recebido > 0 else 0.0))
    status = dados.get("status", "aberta").lower().strip()

    resultado_financeiro = float(dados.get("resultado_financeiro") or 0.0)
    resultado_pct = float(dados.get("resultado_pct") or 0.0)
    if status in ("encerrada", "rolada") and valor_final > 0:
        if "VENDA" in estrutura:
            resultado_financeiro = valor_alocado - valor_final
            resultado_pct = ((preco_recebido - preco_pago) / preco_recebido * 100) if preco_recebido > 0 else 0.0
        else:
            resultado_financeiro = valor_final - valor_alocado
            resultado_pct = ((preco_recebido - preco_pago) / preco_pago * 100) if preco_pago > 0 else 0.0

    sucesso = dados.get("sucesso") or ("s" if resultado_financeiro > 0 else "n")
    operacao_origem_id = dados.get("operacao_origem_id")
    meta_rolagem_pct = float(dados.get("meta_rolagem_pct", 100.0))
    observacoes = dados.get("observacoes", "")

    cur = conexao.execute("""
        INSERT INTO opcoes_operacoes (
            usuario_id, codigo, ativo_subjacente, tipo_opcao, estrutura,
            data_inicio, data_fim, dias, quantidade, preco_pago, preco_recebido,
            preco_atual, valor_alocado, valor_final, resultado_financeiro,
            resultado_pct, sucesso, status, operacao_origem_id, meta_rolagem_pct,
            observacoes, criado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        int(usuario_id), codigo, ativo, tipo, estrutura,
        data_inicio, data_fim, dias, quantidade, preco_pago, preco_recebido,
        preco_atual, valor_alocado, valor_final, resultado_financeiro,
        resultado_pct, sucesso, status, operacao_origem_id, meta_rolagem_pct,
        observacoes, agora()
    ))
    conexao.commit()
    return cur.lastrowid


def encerrar_opcao_operacao(conexao: sqlite3.Connection, usuario_id: int, operacao_id: int,
                           data_fim: str, preco_recebido: float, observacoes: str = "") -> None:
    """Encerra uma operação de opção calculando os resultados."""
    cur = conexao.execute("SELECT * FROM opcoes_operacoes WHERE id = ? AND usuario_id = ?",
                          (int(operacao_id), int(usuario_id)))
    op = cur.fetchone()
    if not op:
        raise ValueError("Operação não encontrada.")
    colunas = [desc[0] for desc in cur.description]
    item = dict(zip(colunas, op))

    quantidade = float(item["quantidade"])
    preco_pago = float(item["preco_pago"])
    valor_alocado = float(item["valor_alocado"])
    estrutura = item["estrutura"]
    valor_final = quantidade * preco_recebido

    if "VENDA" in estrutura:
        res_fin = valor_alocado - valor_final
        res_pct = ((item["preco_recebido"] - preco_recebido) / item["preco_recebido"] * 100) if item["preco_recebido"] > 0 else 0.0
    else:
        res_fin = valor_final - valor_alocado
        res_pct = ((preco_recebido - preco_pago) / preco_pago * 100) if preco_pago > 0 else 0.0

    sucesso = "s" if res_fin > 0 else "n"
    obs = (item["observacoes"] or "").strip()
    if observacoes:
        obs = f"{obs} | {observacoes}".strip(" |")

    conexao.execute("""
        UPDATE opcoes_operacoes SET
            data_fim = ?,
            preco_recebido = ?,
            valor_final = ?,
            resultado_financeiro = ?,
            resultado_pct = ?,
            sucesso = ?,
            status = 'encerrada',
            observacoes = ?
        WHERE id = ? AND usuario_id = ?
    """, (data_fim, preco_recebido, valor_final, res_fin, res_pct, sucesso, obs, int(operacao_id), int(usuario_id)))
    conexao.commit()


def rolar_opcao_operacao(conexao: sqlite3.Connection, usuario_id: int, operacao_id: int,
                        data_rolagem: str, preco_fechamento: float, novo_codigo: str,
                        novo_preco_pago: float, nova_quantidade: float, nova_estrutura: str | None = None,
                        observacoes: str = "") -> int:
    """
    Rola uma operação vencedora (ou de ajuste) para uma nova opção:
    1. Encerra a operação atual com status 'rolada' e registra o lucro/prejuízo.
    2. Abre a nova operação vinculada como filha (operacao_origem_id).
    """
    cur = conexao.execute("SELECT * FROM opcoes_operacoes WHERE id = ? AND usuario_id = ?",
                          (int(operacao_id), int(usuario_id)))
    op = cur.fetchone()
    if not op:
        raise ValueError("Operação original não encontrada.")
    colunas = [desc[0] for desc in cur.description]
    item = dict(zip(colunas, op))

    quantidade = float(item["quantidade"])
    preco_pago = float(item["preco_pago"])
    valor_alocado = float(item["valor_alocado"])
    estrutura = item["estrutura"]
    valor_final = quantidade * preco_fechamento

    if "VENDA" in estrutura:
        res_fin = valor_alocado - valor_final
        res_pct = ((item["preco_recebido"] - preco_fechamento) / item["preco_recebido"] * 100) if item["preco_recebido"] > 0 else 0.0
    else:
        res_fin = valor_final - valor_alocado
        res_pct = ((preco_fechamento - preco_pago) / preco_pago * 100) if preco_pago > 0 else 0.0

    sucesso = "s" if res_fin > 0 else "n"
    obs_antiga = (item["observacoes"] or "").strip()
    obs_antiga = f"{obs_antiga} | Rolada para {novo_codigo} em {data_rolagem}".strip(" |")

    conexao.execute("""
        UPDATE opcoes_operacoes SET
            data_fim = ?,
            preco_recebido = ?,
            valor_final = ?,
            resultado_financeiro = ?,
            resultado_pct = ?,
            sucesso = ?,
            status = 'rolada',
            observacoes = ?
        WHERE id = ? AND usuario_id = ?
    """, (data_rolagem, preco_fechamento, valor_final, res_fin, res_pct, sucesso, obs_antiga, int(operacao_id), int(usuario_id)))

    # Inserir nova perna (rolagem)
    novo_alocado = nova_quantidade * novo_preco_pago
    info_novo = identificar_opcao(novo_codigo)
    obs_nova = f"Rolagem da {item['codigo']} (Lucro perna anterior: R$ {res_fin:,.2f} / +{res_pct:.1f}%)."
    if observacoes:
        obs_nova += f" {observacoes}"

    nova_id = salvar_opcao_operacao(conexao, usuario_id, {
        "codigo": novo_codigo,
        "ativo_subjacente": info_novo["ativo_subjacente"],
        "tipo_opcao": info_novo["tipo_opcao"],
        "estrutura": nova_estrutura or item["estrutura"],
        "data_inicio": data_rolagem,
        "quantidade": nova_quantidade,
        "preco_pago": novo_preco_pago,
        "valor_alocado": novo_alocado,
        "status": "aberta",
        "operacao_origem_id": int(operacao_id),
        "meta_rolagem_pct": float(item.get("meta_rolagem_pct") or 100.0),
        "observacoes": obs_nova,
    })
    return nova_id


def atualizar_cotacao_opcao(conexao: sqlite3.Connection, usuario_id: int,
                            operacao_id: int, preco_atual: float) -> None:
    """Atualiza a cotação corrente de uma opção aberta para recalcular o rendimento."""
    conexao.execute(
        "UPDATE opcoes_operacoes SET preco_atual = ? WHERE id = ? AND usuario_id = ?",
        (float(preco_atual), int(operacao_id), int(usuario_id))
    )
    conexao.commit()


def excluir_opcao_operacao(conexao: sqlite3.Connection, usuario_id: int, operacao_id: int) -> None:
    """Exclui uma operação de opção."""
    conexao.execute("DELETE FROM opcoes_operacoes WHERE id = ? AND usuario_id = ?",
                    (int(operacao_id), int(usuario_id)))
    conexao.commit()


def atualizar_modulos_usuario(conexao: sqlite3.Connection, usuario_id: int,
                             modulo_fiscal: bool, modulo_opcoes: bool) -> None:
    """Ativa ou desativa os módulos de um usuário."""
    conexao.execute(
        "UPDATE usuarios SET modulo_fiscal = ?, modulo_opcoes = ? WHERE id = ?",
        (int(bool(modulo_fiscal)), int(bool(modulo_opcoes)), int(usuario_id))
    )
    conexao.commit()


def importar_opcoes_google_sheet(conexao: sqlite3.Connection, usuario_id: int,
                                 sheet_id: str = "1N2Sv8LwM_VTT5SVKorBAGS2vUKoKdvn3jdvhlwaUl5k") -> dict:
    """
    Importa diretamente as operações da planilha Google 'Minhas Operacoes' (somente leitura).
    """
    import json, os, urllib.request, urllib.parse

    token_path = os.path.expanduser(r"~\.gemini\antigravity\plugin_data\gsheets\token.json")
    if not os.path.exists(token_path):
        raise RuntimeError("Token de autenticação do Google Sheets não encontrado. Execute a autorização primeiro.")

    with open(token_path, "r", encoding="utf-8") as f:
        token_data = json.load(f)
    access_token = token_data.get("token", {}).get("access_token")
    if not access_token:
        raise RuntimeError("Token de acesso inválido no arquivo de credenciais.")

    range_name = "'Minhas Operacoes'!A4:N200"
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{urllib.parse.quote(range_name)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})

    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        rows = res.get("values", [])

    def _pnum(v):
        if not v:
            return 0.0
        s = str(v).replace("R$", "").replace("%", "").strip()
        s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0

    importadas = 0
    atualizadas = 0

    for r in rows[1:]:
        if not r or len(r) < 2 or not str(r[0]).strip() or "Total" in str(r):
            continue
        codigo = str(r[0]).strip().upper()
        estrutura = str(r[1]).strip().upper() if len(r) > 1 and r[1] else "COMPRA DE CALL"
        dt_inicio = str(r[2]).strip() if len(r) > 2 and r[2] else agora()[:10]
        dt_fim = str(r[3]).strip() if len(r) > 3 and r[3] and r[3] != "TRAVA" else ""
        dias = int(_pnum(r[4])) if len(r) > 4 and r[4] and str(r[4]).strip().isdigit() else None
        recebido = _pnum(r[5]) if len(r) > 5 else 0.0
        pago = _pnum(r[6]) if len(r) > 6 else 0.0
        res_pct = _pnum(r[7]) if len(r) > 7 else 0.0
        sucesso = str(r[8]).strip().lower() if len(r) > 8 and r[8] else ("s" if res_pct > 0 else "n")
        status_raw = str(r[9]).strip().lower() if len(r) > 9 and r[9] else ("encerrada" if dt_fim else "aberta")
        status = "encerrada" if "encerr" in status_raw or "fechad" in status_raw else "aberta"
        alocado = _pnum(r[10]) if len(r) > 10 else 0.0
        final = _pnum(r[11]) if len(r) > 11 else 0.0
        res_fin = _pnum(r[12]) if len(r) > 12 else 0.0
        obs = str(r[13]).strip() if len(r) > 13 else ""

        qtd = 100.0
        if alocado > 0 and pago > 0:
            qtd = round(alocado / pago)

        existente = conexao.execute(
            "SELECT id FROM opcoes_operacoes WHERE usuario_id = ? AND codigo = ? AND data_inicio = ?",
            (int(usuario_id), codigo, dt_inicio)
        ).fetchone()

        if existente:
            conexao.execute("""
                UPDATE opcoes_operacoes SET
                    estrutura = ?, data_fim = ?, dias = ?, quantidade = ?,
                    preco_pago = ?, preco_recebido = ?, valor_alocado = ?,
                    valor_final = ?, resultado_financeiro = ?, resultado_pct = ?,
                    sucesso = ?, status = ?, observacoes = ?
                WHERE id = ?
            """, (
                estrutura, dt_fim, dias, qtd, pago, recebido, alocado,
                final, res_fin, res_pct, sucesso, status, obs, int(existente[0])
            ))
            atualizadas += 1
        else:
            salvar_opcao_operacao(conexao, usuario_id, {
                "codigo": codigo,
                "estrutura": estrutura,
                "data_inicio": dt_inicio,
                "data_fim": dt_fim,
                "dias": dias,
                "quantidade": qtd,
                "preco_pago": pago,
                "preco_recebido": recebido,
                "preco_atual": pago if status == "aberta" else 0.0,
                "valor_alocado": alocado,
                "valor_final": final,
                "resultado_financeiro": res_fin,
                "resultado_pct": res_pct,
                "sucesso": sucesso,
                "status": status,
                "observacoes": obs,
            })
            importadas += 1

    conexao.commit()
    return {"importadas": importadas, "atualizadas": atualizadas, "total": importadas + atualizadas}


def importar_opcoes_arquivo(conexao: sqlite3.Connection, usuario_id: int,
                            conteudo_bytes: bytes, nome_arquivo: str) -> dict:
    """
    Importa operações de opções a partir de arquivo Excel (.xlsx, .xls) ou CSV anexado pelo usuário.
    """
    import io, unicodedata
    import pandas as pd

    def _norm(s) -> str:
        if s is None or pd.isna(s):
            return ""
        return unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8').lower().strip()

    if nome_arquivo.lower().endswith(('.xlsx', '.xls')):
        df = pd.read_excel(io.BytesIO(conteudo_bytes), header=None)
    else:
        lido = False
        for enc in ("utf-8", "latin1", "cp1252"):
            for sep in (";", ",", "\t"):
                try:
                    df = pd.read_csv(io.BytesIO(conteudo_bytes), sep=sep, header=None, encoding=enc, engine="python")
                    if df.shape[1] >= 2 and len(df) >= 1:
                        lido = True
                        break
                except Exception:
                    continue
            if lido:
                break
        if not lido:
            raise ValueError("Não foi possível ler o arquivo. Certifique-se de que é um Excel (.xlsx) ou CSV válido.")

    # Detectar linha de cabeçalho
    header_idx = None
    for idx in range(min(15, len(df))):
        vals = [_norm(x) for x in df.iloc[idx].values if pd.notna(x)]
        if any("cod" in x or "ticker" in x or "opcao" in x for x in vals):
            header_idx = idx
            break

    if header_idx is not None:
        headers = [str(x).strip() for x in df.iloc[header_idx].values]
        df_dados = df.iloc[header_idx + 1:].copy()
        df_dados.columns = headers
    else:
        df_dados = df.copy()

    # Mapear colunas semanticamente
    col_map = {}
    for col in df_dados.columns:
        nc = _norm(col)
        if any(k in nc for k in ["cod", "ticker", "opcao"]) and "codigo" not in col_map:
            col_map["codigo"] = col
        elif any(k in nc for k in ["estru", "estrat"]) and "estrutura" not in col_map:
            col_map["estrutura"] = col
        elif any(k in nc for k in ["inicio", "abert", "data ent"]) and "data_inicio" not in col_map:
            col_map["data_inicio"] = col
        elif any(k in nc for k in ["final", "fech", "fim", "saida", "data sai"]) and "data_fim" not in col_map:
            col_map["data_fim"] = col
        elif "dias" in nc and "dias" not in col_map:
            col_map["dias"] = col
        elif any(k in nc for k in ["receb", "saida", "venda"]) and "preco_recebido" not in col_map:
            col_map["preco_recebido"] = col
        elif any(k in nc for k in ["pago", "compra", "entrada"]) and "preco_pago" not in col_map:
            col_map["preco_pago"] = col
        elif any(k in nc for k in ["resultado %", "rentab", "%"]) and "resultado_pct" not in col_map:
            col_map["resultado_pct"] = col
        elif "sucesso" in nc and "sucesso" not in col_map:
            col_map["sucesso"] = col
        elif "status" in nc and "status" not in col_map:
            col_map["status"] = col
        elif any(k in nc for k in ["aloc", "invest"]) and "valor_alocado" not in col_map:
            col_map["valor_alocado"] = col
        elif any(k in nc for k in ["fina", "total final", "resgate"]) and "valor_final" not in col_map:
            col_map["valor_final"] = col
        elif any(k in nc for k in ["resultado", "lucro", "preju"]) and "resultado_financeiro" not in col_map:
            if "%" not in nc:
                col_map["resultado_financeiro"] = col
        elif any(k in nc for k in ["obs", "coluna 1", "nota"]) and "observacoes" not in col_map:
            col_map["observacoes"] = col

    def _pnum(v):
        if v is None or pd.isna(v):
            return 0.0
        s = str(v).replace("R$", "").replace("%", "").strip()
        s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0

    def _pdata(v):
        if v is None or pd.isna(v):
            return ""
        s = str(v).strip()
        if not s or s.lower() in ("nan", "none", "trava"):
            return ""
        if hasattr(v, "strftime"):
            return v.strftime("%d/%m/%Y")
        return s

    importadas = 0
    atualizadas = 0

    for _, row in df_dados.iterrows():
        cod_val = row.get(col_map.get("codigo", ""), "")
        if pd.isna(cod_val) or not str(cod_val).strip() or "total" in str(cod_val).lower():
            continue
        codigo = str(cod_val).strip().upper()
        if len(codigo) < 4:
            continue

        estrutura = str(row.get(col_map.get("estrutura", ""), "COMPRA DE CALL")).strip().upper()
        if not estrutura or estrutura == "NAN":
            estrutura = "COMPRA DE CALL"

        dt_inicio = _pdata(row.get(col_map.get("data_inicio", ""))) or agora()[:10]
        dt_fim = _pdata(row.get(col_map.get("data_fim", "")))

        dias_val = row.get(col_map.get("dias", ""), "")
        dias = int(_pnum(dias_val)) if dias_val and str(dias_val).strip().isdigit() else None

        recebido = _pnum(row.get(col_map.get("preco_recebido", ""), 0))
        pago = _pnum(row.get(col_map.get("preco_pago", ""), 0))
        res_pct = _pnum(row.get(col_map.get("resultado_pct", ""), 0))
        sucesso = str(row.get(col_map.get("sucesso", ""), "")).strip().lower()
        if not sucesso or sucesso not in ("s", "n"):
            sucesso = "s" if res_pct > 0 else "n"

        status_raw = str(row.get(col_map.get("status", ""), "")).strip().lower()
        status = "encerrada" if ("encerr" in status_raw or "fechad" in status_raw or dt_fim) else "aberta"

        alocado = _pnum(row.get(col_map.get("valor_alocado", ""), 0))
        final = _pnum(row.get(col_map.get("valor_final", ""), 0))
        res_fin = _pnum(row.get(col_map.get("resultado_financeiro", ""), 0))
        obs = str(row.get(col_map.get("observacoes", ""), "")).strip()
        if obs.lower() in ("nan", "none"):
            obs = ""

        qtd = 100.0
        if alocado > 0 and pago > 0:
            qtd = round(alocado / pago)

        existente = conexao.execute(
            "SELECT id FROM opcoes_operacoes WHERE usuario_id = ? AND codigo = ? AND data_inicio = ?",
            (int(usuario_id), codigo, dt_inicio)
        ).fetchone()

        if existente:
            conexao.execute("""
                UPDATE opcoes_operacoes SET
                    estrutura = ?, data_fim = ?, dias = ?, quantidade = ?,
                    preco_pago = ?, preco_recebido = ?, valor_alocado = ?,
                    valor_final = ?, resultado_financeiro = ?, resultado_pct = ?,
                    sucesso = ?, status = ?, observacoes = ?
                WHERE id = ?
            """, (
                estrutura, dt_fim, dias, qtd, pago, recebido, alocado,
                final, res_fin, res_pct, sucesso, status, obs, int(existente[0])
            ))
            atualizadas += 1
        else:
            salvar_opcao_operacao(conexao, usuario_id, {
                "codigo": codigo,
                "estrutura": estrutura,
                "data_inicio": dt_inicio,
                "data_fim": dt_fim,
                "dias": dias,
                "quantidade": qtd,
                "preco_pago": pago,
                "preco_recebido": recebido,
                "preco_atual": pago if status == "aberta" else 0.0,
                "valor_alocado": alocado,
                "valor_final": final,
                "resultado_financeiro": res_fin,
                "resultado_pct": res_pct,
                "sucesso": sucesso,
                "status": status,
                "observacoes": obs,
            })
            importadas += 1

    conexao.commit()
    return {"importadas": importadas, "atualizadas": atualizadas, "total": importadas + atualizadas}


def gerar_modelo_planilha_opcoes() -> bytes:
    """Gera um arquivo Excel modelo (.xlsx) com o formato padrão para preenchimento de opções."""
    import io
    import pandas as pd

    dados_modelo = [
        {
            "CÓDIGO": "BOVAI42",
            "ESTRUTURA": "COMPRA DE CALL",
            "DATA INICIO": "24/08/2026",
            "DATA FINAL": "31/08/2026",
            "DIAS": 7,
            "RECEBIDO": 3.27,
            "PAGO": 0.98,
            "RESULTADO %": "233,7%",
            "SUCESSO": "s",
            "STATUS": "Encerrada",
            "Valor Alocado": 196.00,
            "Valor Final": 654.00,
            "Resultado R$": 458.00,
            "Observações": "Exemplo de operação encerrada",
        },
        {
            "CÓDIGO": "BEEFX400",
            "ESTRUTURA": "COMPRA DE PUT",
            "DATA INICIO": "29/10/2026",
            "DATA FINAL": "",
            "DIAS": "",
            "RECEBIDO": "",
            "PAGO": 0.17,
            "RESULTADO %": "",
            "SUCESSO": "",
            "STATUS": "Aberta",
            "Valor Alocado": 170.00,
            "Valor Final": "",
            "Resultado R$": "",
            "Observações": "Rolagem com 50% de lucro no bolso",
        },
    ]
    df = pd.DataFrame(dados_modelo)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Minhas Operacoes")
    return buf.getvalue()


__all__ = [
    "CAMINHO_PADRAO", "VERSAO_ESQUEMA", "PLANOS_PADRAO", "agora", "conectar",
    "garantir_esquema",
    "criar_usuario", "obter_usuario", "obter_por_login", "obter_por_email",
    "listar_usuarios", "atualizar_usuario", "contar_usuarios", "usuario_em_uso",
    "listar_planos", "obter_plano",
    "criar_assinatura", "assinatura_ativa", "listar_assinaturas", "cancelar_assinatura",
    "registrar_pagamento", "listar_pagamentos", "faturamento_total",
    "criar_cupom", "listar_cupons", "obter_cupom", "definir_cupom_ativo",
    "registrar_uso_cupom",
    "criar_parceiro", "listar_parceiros", "obter_parceiro", "obter_parceiro_por_codigo",
    "definir_parceiro_ativo", "registrar_indicacao", "obter_indicacao",
    "marcar_beneficio_usado", "listar_indicacoes",
    "registrar_nota_fiscal", "listar_notas_fiscais",
    "obter_config_pagamento", "gravar_config_pagamento",
    "salvar_notas", "sanitizar_duplicatas", "limpar_dados", "remover_notas",
    "carregar_operacoes", "carregar_notas",
    "resumo_importacao", "contar_notas",
    "ler_prejuizos", "gravar_prejuizos",
    "carregar_proventos", "salvar_proventos", "adicionar_provento", "remover_provento",
    "carregar_darf_pagamentos", "gravar_darf_pagamento",
    "carregar_parametros_fiscais", "gravar_parametros_fiscais",
    "carregar_monitor_legislacao", "gravar_monitor_legislacao",
    "identificar_opcao", "listar_opcoes_operacoes", "salvar_opcao_operacao",
    "encerrar_opcao_operacao", "rolar_opcao_operacao", "atualizar_cotacao_opcao",
    "excluir_opcao_operacao", "atualizar_modulos_usuario", "importar_opcoes_google_sheet",
    "importar_opcoes_arquivo", "gerar_modelo_planilha_opcoes",
]
