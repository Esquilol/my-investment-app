"""
auth.py
-------
Login **local** com senha, sem dependências externas.

A senha não é gravada em claro: o banco guarda apenas o *hash* PBKDF2-HMAC-SHA256
com sal aleatório por usuário, no formato ``algoritmo$iteracoes$sal$hash``. A
verificação usa ``secrets.compare_digest`` para não vazar informação por tempo de
comparação.

Como é um app de uso pessoal, há **um único usuário** (linha de ``id = 1`` na
tabela ``usuarios``). O banco (``dados.db``) fica fora do versionamento, de modo
que a credencial nunca vai para o repositório.

Uso:
    from auth import tem_usuario, definir_senha, verificar_senha
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3

#: Algoritmo identificado no registro gravado.
ALGORITMO = "pbkdf2_sha256"

#: Número de iterações do PBKDF2. Alto o bastante para encarecer a força bruta
#: e baixo o bastante para não travar o login em máquina comum.
ITERACOES = 200_000

#: Tamanho mínimo aceito para a senha.
TAMANHO_MINIMO = 6


def gerar_hash(senha: str, sal: bytes | None = None,
               iteracoes: int = ITERACOES) -> str:
    """Devolve o registro ``algoritmo$iteracoes$sal$hash`` para a senha."""
    sal = sal or secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, iteracoes)
    return f"{ALGORITMO}${iteracoes}${sal.hex()}${derivado.hex()}"


def conferir_senha(senha: str, registro: str) -> bool:
    """Compara a senha com o registro gravado, em tempo constante."""
    try:
        algoritmo, iteracoes, sal_hex, esperado_hex = registro.split("$")
        if algoritmo != ALGORITMO:
            return False
        derivado = hashlib.pbkdf2_hmac(
            "sha256", senha.encode("utf-8"), bytes.fromhex(sal_hex), int(iteracoes)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(derivado.hex(), esperado_hex)


def tem_usuario(conexao: sqlite3.Connection) -> bool:
    """Indica se já existe uma senha configurada."""
    return conexao.execute("SELECT 1 FROM usuarios WHERE id = 1").fetchone() is not None


def definir_senha(conexao: sqlite3.Connection, usuario: str, senha: str) -> None:
    """Cria (ou substitui) a credencial de acesso."""
    from datetime import datetime

    conexao.execute(
        "INSERT INTO usuarios (id, usuario, hash, criado_em) VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET usuario = excluded.usuario, "
        "hash = excluded.hash, criado_em = excluded.criado_em",
        (usuario.strip() or "investidor", gerar_hash(senha),
         datetime.now().isoformat(timespec="seconds")),
    )
    conexao.commit()


def verificar_senha(conexao: sqlite3.Connection, usuario: str, senha: str) -> bool:
    """Confere usuário e senha contra o registro gravado."""
    linha = conexao.execute(
        "SELECT usuario, hash FROM usuarios WHERE id = 1"
    ).fetchone()
    if linha is None:
        return False
    if usuario.strip().casefold() != str(linha["usuario"]).casefold():
        return False
    return conferir_senha(senha, linha["hash"])
