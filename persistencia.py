"""
persistencia.py
---------------
Armazenamento local das operações em **SQLite**.

Motivação (item 1 do checklist de reconstrução): antes, tudo vivia apenas em
``st.session_state`` e era perdido ao recarregar a página. Aqui as notas e as
operações são gravadas em disco, com **deduplicação por número de nota**, o que
é indispensável porque as notas exportadas pela corretora se sobrepõem entre os
arquivos (verificado: 33 notas únicas em 4 PDFs, com 24 repetidas).

Também guarda:

* o saldo de prejuízo anterior a compensar (item 2);
* os proventos/lançamentos informados manualmente.

Uso:
    from persistencia import conectar, salvar_notas, carregar_operacoes
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pandas as pd

from parser import Nota

#: Banco criado ao lado dos módulos do projeto.
CAMINHO_PADRAO = Path(__file__).with_name("dados.db")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS notas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    numero          TEXT    NOT NULL,
    corretora       TEXT    NOT NULL,
    data            TEXT,
    arquivo         TEXT,
    despesas        REAL    NOT NULL DEFAULT 0,
    irrf            REAL    NOT NULL DEFAULT 0,
    categoria_irrf  TEXT    NOT NULL DEFAULT 'SwingTrade',
    UNIQUE (corretora, numero)
);

CREATE TABLE IF NOT EXISTS operacoes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    hash         TEXT    NOT NULL UNIQUE,
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
    arquivo      TEXT
);

CREATE TABLE IF NOT EXISTS prejuizos_anteriores (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    data                TEXT,
    previous_loss_fii   REAL NOT NULL DEFAULT 0,
    previous_loss_swing REAL NOT NULL DEFAULT 0,
    previous_loss_day   REAL NOT NULL DEFAULT 0,
    ir_swing            REAL NOT NULL DEFAULT 0,
    ir_day              REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS proventos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    data       TEXT NOT NULL,
    ticker     TEXT NOT NULL,
    tipo       TEXT NOT NULL,
    quantidade REAL NOT NULL DEFAULT 0,
    valor      REAL NOT NULL DEFAULT 0
);
"""


def conectar(caminho: Path | str | None = None) -> sqlite3.Connection:
    """Abre (criando se necessário) o banco SQLite do projeto."""
    destino = Path(caminho) if caminho else CAMINHO_PADRAO
    if destino.parent and not destino.parent.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)

    conexao = sqlite3.connect(str(destino), check_same_thread=False)
    conexao.row_factory = sqlite3.Row
    conexao.executescript(_ESQUEMA)
    conexao.commit()
    return conexao


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------

def _hash_operacao(chave: str, ocorrencia: int) -> str:
    return hashlib.sha1(f"{chave}#{ocorrencia}".encode("utf-8")).hexdigest()


def salvar_notas(conexao: sqlite3.Connection, notas: list[Nota]) -> tuple[int, int]:
    """
    Grava as notas e suas operações.

    Retorna ``(notas_novas, operacoes_novas)``. Notas já existentes (mesma
    corretora + número) são ignoradas — é isso que evita contar em dobro as
    notas que aparecem em mais de um PDF exportado.
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
            "(numero, corretora, data, arquivo, despesas, irrf, categoria_irrf) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
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
                "(hash, corretora, nota, data, tipo, ticker, quantidade, preco, "
                " valor_total, mercado, taxas, irrf, resultado, day_trade, obs, arquivo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
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


def limpar_dados(conexao: sqlite3.Connection) -> None:
    """Apaga notas, operações e proventos (mantém os prejuízos informados)."""
    conexao.executescript("DELETE FROM operacoes; DELETE FROM notas; DELETE FROM proventos;")
    conexao.commit()


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def carregar_operacoes(conexao: sqlite3.Connection) -> pd.DataFrame:
    """DataFrame com todas as operações persistidas."""
    return pd.read_sql_query(
        "SELECT data, tipo, ticker, quantidade, preco, valor_total, mercado, "
        "       taxas, irrf, resultado, day_trade, nota, corretora, arquivo, obs "
        "FROM operacoes ORDER BY data, nota, id",
        conexao,
    )


def carregar_notas(conexao: sqlite3.Connection) -> pd.DataFrame:
    """DataFrame com as notas persistidas (usado para o IRRF retido)."""
    return pd.read_sql_query(
        "SELECT numero, corretora, data, arquivo, despesas, irrf, categoria_irrf "
        "FROM notas ORDER BY data, numero",
        conexao,
    )


def resumo_importacao(conexao: sqlite3.Connection) -> dict:
    """Contagens exibidas na aba de upload."""
    notas = conexao.execute("SELECT COUNT(*) FROM notas").fetchone()[0]
    operacoes = conexao.execute("SELECT COUNT(*) FROM operacoes").fetchone()[0]
    arquivos = conexao.execute("SELECT COUNT(DISTINCT arquivo) FROM notas").fetchone()[0]
    return {"notas": notas, "operacoes": operacoes, "arquivos": arquivos}


# ---------------------------------------------------------------------------
# Prejuízos anteriores a compensar (espelho de PreviousLoss.aspx)
# ---------------------------------------------------------------------------

def ler_prejuizos(conexao: sqlite3.Connection) -> dict:
    """Saldo de prejuízo anterior a compensar, por bucket."""
    linha = conexao.execute("SELECT * FROM prejuizos_anteriores WHERE id = 1").fetchone()
    if linha is None:
        return {
            "data": None,
            "DayTrade": 0.0,
            "SwingTrade": 0.0,
            "FII": 0.0,
            "ir_swing": 0.0,
            "ir_day": 0.0,
        }
    return {
        "data": linha["data"],
        "DayTrade": linha["previous_loss_day"],
        "SwingTrade": linha["previous_loss_swing"],
        "FII": linha["previous_loss_fii"],
        "ir_swing": linha["ir_swing"],
        "ir_day": linha["ir_day"],
    }


def gravar_prejuizos(conexao: sqlite3.Connection, dados: dict) -> None:
    """Grava (substituindo) o saldo de prejuízo anterior a compensar."""
    conexao.execute(
        "INSERT INTO prejuizos_anteriores "
        "(id, data, previous_loss_fii, previous_loss_swing, previous_loss_day, ir_swing, ir_day) "
        "VALUES (1, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "  data = excluded.data,"
        "  previous_loss_fii = excluded.previous_loss_fii,"
        "  previous_loss_swing = excluded.previous_loss_swing,"
        "  previous_loss_day = excluded.previous_loss_day,"
        "  ir_swing = excluded.ir_swing,"
        "  ir_day = excluded.ir_day",
        (
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
# Proventos
# ---------------------------------------------------------------------------

def carregar_proventos(conexao: sqlite3.Connection) -> pd.DataFrame:
    """Proventos informados manualmente."""
    return pd.read_sql_query(
        "SELECT id, data, ticker, tipo, quantidade, valor FROM proventos ORDER BY data",
        conexao,
    )


def adicionar_provento(conexao: sqlite3.Connection, data: str, ticker: str,
                       tipo: str, quantidade: float, valor: float) -> None:
    """Registra um provento (dividendo, JCP, rendimento ou amortização)."""
    conexao.execute(
        "INSERT INTO proventos (data, ticker, tipo, quantidade, valor) VALUES (?, ?, ?, ?, ?)",
        (data, ticker.upper(), tipo, float(quantidade), float(valor)),
    )
    conexao.commit()


def remover_provento(conexao: sqlite3.Connection, identificador: int) -> None:
    """Remove um provento pelo seu id."""
    conexao.execute("DELETE FROM proventos WHERE id = ?", (int(identificador),))
    conexao.commit()


__all__ = [
    "CAMINHO_PADRAO", "conectar", "salvar_notas", "limpar_dados",
    "carregar_operacoes", "carregar_notas", "resumo_importacao",
    "ler_prejuizos", "gravar_prejuizos",
    "carregar_proventos", "adicionar_provento", "remover_provento",
]
