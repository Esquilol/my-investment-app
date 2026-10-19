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

* **usuários** (hash de senha, perfil de acesso, plano e status);
* **planos**, **assinaturas** e **pagamentos**;
* **cupons** de desconto e **notas fiscais**;
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
VERSAO_ESQUEMA = 4

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
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
    desconto_pct REAL    NOT NULL DEFAULT 0,
    ativo        INTEGER NOT NULL DEFAULT 1,
    validade     TEXT,
    uso_maximo   INTEGER NOT NULL DEFAULT 0,
    usos         INTEGER NOT NULL DEFAULT 0,
    criado_em    TEXT
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
    data            TEXT,
    arquivo         TEXT,
    despesas        REAL    NOT NULL DEFAULT 0,
    irrf            REAL    NOT NULL DEFAULT 0,
    categoria_irrf  TEXT    NOT NULL DEFAULT 'SwingTrade',
    UNIQUE (usuario_id, corretora, numero)
);

CREATE TABLE IF NOT EXISTS operacoes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id   INTEGER NOT NULL,
    hash         TEXT    NOT NULL,
    corretora    TEXT,
    nota         TEXT,
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


def _migrar(conexao: sqlite3.Connection) -> None:
    """
    Converte o esquema **monousuário** antigo no esquema multiusuário.

    Os dados existentes passam a pertencer ao primeiro usuário (promovido a
    administrador), de modo que nada é perdido na atualização.
    """
    if "usuario_id" in _colunas(conexao, "notas"):
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

    if conexao.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
        from auth import ADMIN_PADRAO_EMAIL, ADMIN_PADRAO_SENHA, ADMIN_PADRAO_USUARIO, gerar_hash

        if ADMIN_PADRAO_SENHA:  # sem segredo configurado, não semeia o admin
            conexao.execute(
                "INSERT INTO usuarios (usuario, email, hash, is_admin, ativo, plano_codigo, criado_em) "
                "VALUES (?, ?, ?, 1, 1, 'pro', ?)",
                (ADMIN_PADRAO_USUARIO, ADMIN_PADRAO_EMAIL,
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

_CAMPOS_PUBLICOS = ("id, usuario, email, is_admin, ativo, plano_codigo, criado_em")


def criar_usuario(conexao: sqlite3.Connection, usuario: str, email: str,
                  senha_hash: str, is_admin: bool = False,
                  plano_codigo: str = "free") -> int:
    """Insere um usuário e devolve o ``id`` criado."""
    try:
        cur = conexao.execute(
            "INSERT INTO usuarios (usuario, email, hash, is_admin, ativo, plano_codigo, criado_em) "
            "VALUES (?, ?, ?, ?, 1, ?, ?)",
            (usuario.strip(), email.strip().lower(), senha_hash,
             int(is_admin), plano_codigo, agora()),
        )
    except sqlite3.IntegrityError as erro:
        raise ValueError("usuário ou e-mail já cadastrado") from erro
    conexao.commit()
    return int(cur.lastrowid)


def obter_usuario(conexao: sqlite3.Connection, usuario_id: int):
    """Linha do usuário (sem o hash) ou ``None``."""
    colunas = ", ".join(_CAMPOS_PUBLICOS.split(", "))
    return conexao.execute(
        f"SELECT {colunas} FROM usuarios WHERE id = ?", (int(usuario_id),)
    ).fetchone()


def obter_por_login(conexao: sqlite3.Connection, login: str):
    """Linha **com hash**, buscando por usuário ou e-mail (usado no login)."""
    return conexao.execute(
        "SELECT id, usuario, email, hash, is_admin, ativo, plano_codigo, criado_em "
        "FROM usuarios WHERE usuario = ? OR email = ?",
        (login.strip(), login.strip().lower()),
    ).fetchone()


def obter_por_email(conexao: sqlite3.Connection, email: str):
    return conexao.execute(
        "SELECT id, usuario, email, hash, is_admin, ativo, plano_codigo, criado_em "
        "FROM usuarios WHERE email = ?", (email.strip().lower(),)
    ).fetchone()


def listar_usuarios(conexao: sqlite3.Connection) -> pd.DataFrame:
    """Todos os usuários, com o nome do plano (para o painel administrativo)."""
    return pd.read_sql_query(
        "SELECT u.id, u.usuario, u.email, u.plano_codigo AS plano, p.nome AS plano_nome, "
        "       u.is_admin, u.ativo, u.criado_em "
        "FROM usuarios u LEFT JOIN planos p ON p.codigo = u.plano_codigo "
        "ORDER BY u.id",
        conexao,
    )


def atualizar_usuario(conexao: sqlite3.Connection, usuario_id: int, **campos) -> None:
    """Atualiza os campos informados de um usuário (usuario, email, hash, ativo...)."""
    permitidos = {"usuario", "email", "hash", "is_admin", "ativo", "plano_codigo",
                  "reset_token", "reset_expira"}
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

def criar_cupom(conexao: sqlite3.Connection, codigo: str, desconto_pct: float,
                validade: str | None = None, uso_maximo: int = 0) -> int:
    try:
        cur = conexao.execute(
            "INSERT INTO cupons (codigo, desconto_pct, ativo, validade, uso_maximo, "
            " usos, criado_em) VALUES (?, ?, 1, ?, ?, 0, ?)",
            (codigo.strip().upper(), float(desconto_pct), validade,
             int(uso_maximo), agora()),
        )
    except sqlite3.IntegrityError as erro:
        raise ValueError("já existe um cupom com esse código") from erro
    conexao.commit()
    return int(cur.lastrowid)


def listar_cupons(conexao: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id, codigo, desconto_pct, ativo, validade, uso_maximo, usos, criado_em "
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
    usuário + corretora + número) são ignoradas — é isso que evita contar em
    dobro as notas que aparecem em mais de um PDF exportado.
    """
    notas_novas = 0
    ops_novas = 0

    for nota in notas:
        categoria_irrf = (
            "DayTrade"
            if nota.operacoes and all(op.day_trade for op in nota.operacoes)
            else "SwingTrade"
        )
        cur = conexao.execute(
            "INSERT OR IGNORE INTO notas "
            "(usuario_id, numero, corretora, data, arquivo, despesas, irrf, categoria_irrf) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(usuario_id),
                nota.numero,
                nota.corretora,
                nota.data.isoformat() if nota.data else None,
                nota.arquivo,
                nota.despesas,
                nota.irrf,
                categoria_irrf,
            ),
        )
        if cur.rowcount == 0:
            continue                       # nota já importada quando este arquivo entrou
        notas_novas += 1

        ocorrencias: dict[str, int] = {}
        for op in nota.operacoes:
            chave = "|".join(str(p) for p in (
                op.corretora, op.nota, op.data, op.tipo, op.ticker,
                op.quantidade, op.preco, op.valor_total, op.resultado,
            ))
            indice = ocorrencias.get(chave, 0)
            ocorrencias[chave] = indice + 1

            cur = conexao.execute(
                "INSERT OR IGNORE INTO operacoes "
                "(usuario_id, hash, corretora, nota, data, tipo, ticker, quantidade, "
                " preco, valor_total, mercado, taxas, irrf, resultado, day_trade, obs, arquivo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(usuario_id),
                    _hash_operacao(chave, indice),
                    op.corretora, op.nota,
                    op.data.isoformat() if op.data else None,
                    op.tipo, op.ticker, op.quantidade, op.preco, op.valor_total,
                    op.mercado, op.taxas, op.irrf, op.resultado,
                    int(op.day_trade), op.obs, op.arquivo,
                ),
            )
            ops_novas += cur.rowcount

    conexao.commit()
    return notas_novas, ops_novas


def limpar_dados(conexao: sqlite3.Connection, usuario_id: int) -> None:
    """Apaga notas, operações, proventos e DARFs pagos **do usuário** (mantém os prejuízos)."""
    for tabela in ("operacoes", "notas", "proventos", "darf_pagamentos"):
        conexao.execute(f"DELETE FROM {tabela} WHERE usuario_id = ?", (int(usuario_id),))
    conexao.commit()


def remover_notas(conexao: sqlite3.Connection, usuario_id: int,
                  chaves: list[tuple[str, str]]) -> int:
    """
    Apaga as notas indicadas e as operações que vieram delas.

    ``chaves`` é uma lista de ``(corretora, número da nota)`` — a mesma chave
    que identifica a nota na importação. Retorna quantas notas foram removidas.
    """
    removidas = 0
    for corretora, numero in chaves:
        cur = conexao.execute(
            "DELETE FROM notas WHERE usuario_id = ? AND corretora = ? AND numero = ?",
            (int(usuario_id), str(corretora), str(numero)),
        )
        removidas += cur.rowcount
        conexao.execute(
            "DELETE FROM operacoes WHERE usuario_id = ? AND corretora = ? AND nota = ?",
            (int(usuario_id), str(corretora), str(numero)),
        )
    conexao.commit()
    return removidas


def carregar_operacoes(conexao: sqlite3.Connection, usuario_id: int) -> pd.DataFrame:
    """DataFrame com as operações do usuário."""
    return pd.read_sql_query(
        "SELECT data, tipo, ticker, quantidade, preco, valor_total, mercado, "
        "       taxas, irrf, resultado, day_trade, nota, corretora, arquivo, obs "
        "FROM operacoes WHERE usuario_id = ? ORDER BY data, nota, id",
        conexao, params=(int(usuario_id),),
    )


def carregar_notas(conexao: sqlite3.Connection, usuario_id: int) -> pd.DataFrame:
    """DataFrame com as notas do usuário (usado para o IRRF retido)."""
    return pd.read_sql_query(
        "SELECT numero, corretora, data, arquivo, despesas, irrf, categoria_irrf "
        "FROM notas WHERE usuario_id = ? ORDER BY data, numero",
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


__all__ = [
    "CAMINHO_PADRAO", "VERSAO_ESQUEMA", "PLANOS_PADRAO", "agora", "conectar",
    "garantir_esquema",
    "criar_usuario", "obter_usuario", "obter_por_login", "obter_por_email",
    "listar_usuarios", "atualizar_usuario", "contar_usuarios",
    "listar_planos", "obter_plano",
    "criar_assinatura", "assinatura_ativa", "listar_assinaturas", "cancelar_assinatura",
    "registrar_pagamento", "listar_pagamentos", "faturamento_total",
    "criar_cupom", "listar_cupons", "obter_cupom", "definir_cupom_ativo",
    "registrar_uso_cupom",
    "registrar_nota_fiscal", "listar_notas_fiscais",
    "obter_config_pagamento", "gravar_config_pagamento",
    "salvar_notas", "limpar_dados", "remover_notas",
    "carregar_operacoes", "carregar_notas",
    "resumo_importacao", "contar_notas",
    "ler_prejuizos", "gravar_prejuizos",
    "carregar_proventos", "salvar_proventos", "adicionar_provento", "remover_provento",
    "carregar_darf_pagamentos", "gravar_darf_pagamento",
    "carregar_parametros_fiscais", "gravar_parametros_fiscais",
    "carregar_monitor_legislacao", "gravar_monitor_legislacao",
]
