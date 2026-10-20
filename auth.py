"""
auth.py
-------
Cadastro, autenticação e perfil dos usuários, com senha protegida por
**PBKDF2-HMAC-SHA256** e sal aleatório por usuário.

A senha nunca é gravada em claro: o banco guarda apenas o *hash* no formato
``algoritmo$iteracoes$sal$hash``. A conferência usa ``secrets.compare_digest``
para não vazar informação por tempo de comparação.

A recuperação de senha é **simulada** (não há envio de e-mail): o app gera um
token de uso único e o exibe na tela, para ser informado no formulário de
redefinição.

Uso:
    from auth import criar_conta, autenticar, alterar_senha
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta

import streamlit as st

import persistencia as bd

#: Algoritmo identificado no registro gravado.
ALGORITMO = "pbkdf2_sha256"

#: Número de iterações do PBKDF2 (encarece a força bruta sem travar o login).
ITERACOES = 200_000

#: Tamanho mínimo aceito para a senha.
TAMANHO_MINIMO = 6

# ---------------------------------------------------------------------------
# Credencial padrão do administrador
# ---------------------------------------------------------------------------
# Nenhuma credencial fica no código: usuário, e-mail e senha vêm todos de
# ``st.secrets["admin"]`` — no Streamlit Cloud, defina em *App settings →
# Secrets*; localmente, em ``.streamlit/secrets.toml`` (fora do versionamento).
# Sem esses segredos, o administrador simplesmente não é semeado.
#
#     # .streamlit/secrets.toml
#     [admin]
#     usuario = "..."
#     email   = "..."
#     senha   = "..."
def _segredo_admin(campo: str) -> str | None:
    """Lê uma credencial do administrador em ``st.secrets['admin']``."""
    try:
        return str(st.secrets["admin"][campo])
    except Exception:  # sem arquivo/segredo configurado
        return None


ADMIN_PADRAO_USUARIO = _segredo_admin("usuario")
ADMIN_PADRAO_EMAIL = _segredo_admin("email")
ADMIN_PADRAO_SENHA = _segredo_admin("senha")

#: Validade do token de recuperação de senha.
VALIDADE_TOKEN_HORAS = 1

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USUARIO = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


# ---------------------------------------------------------------------------
# Hash da senha
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Validações
# ---------------------------------------------------------------------------

def validar_cadastro(usuario: str, email: str, senha: str,
                     confirmacao: str) -> str | None:
    """Retorna a mensagem de erro, ou ``None`` se o cadastro estiver válido."""
    if not _USUARIO.match(usuario.strip()):
        return ("Usuário deve ter de 3 a 32 caracteres, usando letras, números, "
                "ponto, hífen ou sublinhado.")
    if not _EMAIL.match(email.strip()):
        return "Informe um e-mail válido."
    if len(senha) < TAMANHO_MINIMO:
        return f"A senha deve ter ao menos {TAMANHO_MINIMO} caracteres."
    if senha != confirmacao:
        return "As senhas não conferem."
    return None


# ---------------------------------------------------------------------------
# Contas
# ---------------------------------------------------------------------------

def criar_conta(conexao: sqlite3.Connection, usuario: str, email: str,
                senha: str, is_admin: bool = False) -> int:
    """Cadastra um usuário (senha em hash) e devolve o ``id``."""
    return bd.criar_usuario(conexao, usuario, email, gerar_hash(senha),
                            is_admin=is_admin, plano_codigo="free")


def autenticar(conexao: sqlite3.Connection, login: str, senha: str):
    """
    Autentica por usuário **ou** e-mail.

    Devolve a linha do usuário (sem o hash) quando as credenciais conferem e a
    conta está ativa; caso contrário, ``None``.
    """
    linha = bd.obter_por_login(conexao, login or "")
    if linha is None or not conferir_senha(senha or "", linha["hash"]):
        return None
    if not linha["ativo"]:
        return None
    return bd.obter_usuario(conexao, linha["id"])


def alterar_senha(conexao: sqlite3.Connection, usuario_id: int, senha_atual: str,
                  nova_senha: str) -> bool:
    """Troca a senha do usuário, exigindo a senha atual."""
    linha = conexao.execute(
        "SELECT hash FROM usuarios WHERE id = ?", (int(usuario_id),)).fetchone()
    if linha is None or not conferir_senha(senha_atual or "", linha["hash"]):
        return False
    bd.atualizar_usuario(conexao, usuario_id, hash=gerar_hash(nova_senha))
    return True


# ---------------------------------------------------------------------------
# Recuperação de senha (simulada)
# ---------------------------------------------------------------------------

def gerar_token_recuperacao(conexao: sqlite3.Connection, email: str) -> str | None:
    """
    Cria um token de uso único para redefinir a senha.

    Como não há envio de e-mail, o token é devolvido aqui e deve ser exibido ao
    usuário pelo app. Devolve ``None`` se o e-mail não estiver cadastrado.
    """
    usuario = bd.obter_por_email(conexao, email or "")
    if usuario is None:
        return None
    token = secrets.token_hex(3).upper()
    expira = (datetime.now() + timedelta(hours=VALIDADE_TOKEN_HORAS)).isoformat(
        timespec="seconds")
    bd.atualizar_usuario(conexao, usuario["id"], reset_token=token, reset_expira=expira)
    return token


def redefinir_senha(conexao: sqlite3.Connection, email: str, token: str,
                    nova_senha: str) -> bool:
    """Redefine a senha quando o token confere e ainda não expirou."""
    usuario = bd.obter_por_email(conexao, email or "")
    if usuario is None:
        return False
    linha = conexao.execute(
        "SELECT reset_token, reset_expira FROM usuarios WHERE id = ?",
        (int(usuario["id"]),)).fetchone()
    if not linha or not linha["reset_token"]:
        return False
    if not hmac.compare_digest(str(linha["reset_token"]),
                               str(token or "").strip().upper()):
        return False
    if linha["reset_expira"] and datetime.fromisoformat(linha["reset_expira"]) < datetime.now():
        return False
    bd.atualizar_usuario(conexao, usuario["id"], hash=gerar_hash(nova_senha),
                         reset_token=None, reset_expira=None)
    return True
