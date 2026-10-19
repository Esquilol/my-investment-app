"""
saas.py
-------
Regras de negócio do SaaS: planos, limites do plano gratuito, cupons de
desconto, checkout simulado (Pix/cartão) e as métricas do painel administrativo.

O pagamento é **simulado**: não há integração com gateway. O checkout gera a
assinatura, o pagamento e a nota fiscal no banco, exatamente como um gateway
real faria via webhook — o ponto de troca por uma integração de verdade é
:func:`assinar`.

Uso:
    from saas import plano_do_usuario, assinar, validar_cupom
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

import persistencia as bd

#: Formas de pagamento oferecidas no checkout.
FORMAS_PAGAMENTO = ["Pix", "Cartão de crédito"]

#: Ambiente padrão do provedor de pagamento.
AMBIENTE_PADRAO = "simulado"


def _moeda(valor: float) -> str:
    texto = f"{float(valor or 0.0):,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# Planos e limites
# ---------------------------------------------------------------------------

def plano_do_usuario(conexao: sqlite3.Connection, usuario_id: int):
    """Plano vigente do usuário (linha da tabela ``planos``)."""
    usuario = bd.obter_usuario(conexao, usuario_id)
    codigo = usuario["plano_codigo"] if usuario else "free"
    return bd.obter_plano(conexao, codigo)


def eh_pro(conexao: sqlite3.Connection, usuario_id: int) -> bool:
    plano = plano_do_usuario(conexao, usuario_id)
    return bool(plano and plano["codigo"] != "free")


def rotulo_plano(conexao: sqlite3.Connection, usuario_id: int) -> str:
    """Texto do selo do plano exibido na barra lateral."""
    plano = plano_do_usuario(conexao, usuario_id)
    if plano is None:
        return "Gratuito"
    return f"{plano['nome']}" + ("" if plano["codigo"] == "free"
                                 else f" · {_moeda(plano['preco_mensal'])}/mês")


def limite_notas(conexao: sqlite3.Connection, usuario_id: int) -> int:
    """Limite de notas do plano; ``-1`` significa ilimitado."""
    plano = plano_do_usuario(conexao, usuario_id)
    return int(plano["limite_notas"]) if plano else 20


def pode_importar(conexao: sqlite3.Connection, usuario_id: int,
                  quantidade: int) -> tuple[bool, str]:
    """
    Verifica se o usuário ainda tem espaço no plano para ``quantidade`` notas.

    Devolve ``(permitido, mensagem)``.
    """
    limite = limite_notas(conexao, usuario_id)
    if limite < 0:
        return True, ""
    usadas = bd.contar_notas(conexao, usuario_id)
    if usadas + quantidade <= limite:
        return True, ""
    return False, (
        f"Seu plano permite {limite} notas e você já importou {usadas}. "
        "Assine o plano PRO para importar sem limite."
    )


def pode_exportar_excel(conexao: sqlite3.Connection, usuario_id: int) -> bool:
    plano = plano_do_usuario(conexao, usuario_id)
    return bool(plano and plano["exporta_excel"])


# ---------------------------------------------------------------------------
# Cupons de desconto
# ---------------------------------------------------------------------------

def validar_cupom(conexao: sqlite3.Connection, codigo: str):
    """
    Valida um cupom e devolve ``(ok, cupom, mensagem)``.

    Um cupom é recusado se não existir, estiver desativado, vencido ou já tiver
    atingido o limite de usos.
    """
    if not codigo or not codigo.strip():
        return False, None, "Informe o código do cupom."
    cupom = bd.obter_cupom(conexao, codigo)
    if cupom is None:
        return False, None, "Cupom não encontrado."
    if not cupom["ativo"]:
        return False, None, "Cupom desativado."
    if cupom["validade"]:
        try:
            if datetime.fromisoformat(cupom["validade"]).date() < date.today():
                return False, None, "Cupom vencido."
        except ValueError:
            return False, None, "Cupom com validade inválida."
    if cupom["uso_maximo"] and cupom["usos"] >= cupom["uso_maximo"]:
        return False, None, "Cupom esgotado (limite de usos atingido)."
    return True, cupom, f"Cupom aplicado: {cupom['desconto_pct']:.0f}% de desconto."


def calcular_preco(plano, cupom) -> dict:
    """Valores do checkout: original, desconto e final."""
    original = float(plano["preco_mensal"])
    percentual = float(cupom["desconto_pct"]) if cupom else 0.0
    desconto = round(original * percentual / 100.0, 2)
    return {
        "original": original,
        "percentual": percentual,
        "desconto": desconto,
        "final": round(original - desconto, 2),
    }


# ---------------------------------------------------------------------------
# Checkout (simulado)
# ---------------------------------------------------------------------------

def assinar(conexao: sqlite3.Connection, usuario_id: int, plano_codigo: str,
            forma: str = "Pix", codigo_cupom: str | None = None,
            meses: int = 1) -> dict:
    """
    Efetiva a assinatura: valida o cupom, grava a assinatura, o pagamento, a
    nota fiscal e atualiza o plano do usuário.

    Levanta ``ValueError`` quando o plano não existe, o valor é inválido, a
    forma de pagamento é desconhecida ou o cupom informado é recusado.
    """
    plano = bd.obter_plano(conexao, plano_codigo)
    if plano is None:
        raise ValueError("Plano não encontrado.")
    if plano_codigo == "free":
        raise ValueError("O plano gratuito não passa por checkout.")
    if float(plano["preco_mensal"]) <= 0:
        raise ValueError("Plano sem preço definido.")
    if forma not in FORMAS_PAGAMENTO:
        raise ValueError("Forma de pagamento inválida.")

    cupom = None
    if codigo_cupom and codigo_cupom.strip():
        ok, cupom, mensagem = validar_cupom(conexao, codigo_cupom)
        if not ok:
            raise ValueError(mensagem)

    valores = calcular_preco(plano, cupom)
    assinatura_id = bd.criar_assinatura(
        conexao, usuario_id, plano_codigo, valor_pago=valores["final"],
        forma=forma, cupom_codigo=cupom["codigo"] if cupom else None, meses=meses,
    )
    referencia = f"SIM-{datetime.now():%Y%m%d%H%M%S}-{usuario_id}"
    pagamento_id = bd.registrar_pagamento(
        conexao, usuario_id, assinatura_id, valor=valores["original"],
        desconto=valores["desconto"], valor_final=valores["final"],
        forma=forma, referencia=referencia,
    )
    numero_nf = bd.registrar_nota_fiscal(conexao, usuario_id, pagamento_id,
                                         valores["final"])
    if cupom:
        bd.registrar_uso_cupom(conexao, cupom["codigo"])

    return {
        "assinatura_id": assinatura_id,
        "pagamento_id": pagamento_id,
        "nota_fiscal": numero_nf,
        "referencia": referencia,
        "plano": plano["nome"],
        "forma": forma,
        **valores,
    }


# ---------------------------------------------------------------------------
# Painel administrativo
# ---------------------------------------------------------------------------

def metricas(conexao: sqlite3.Connection) -> dict:
    """Indicadores do dashboard administrativo."""
    contagem = bd.contar_usuarios(conexao)
    ativas = conexao.execute(
        "SELECT COUNT(*) FROM assinaturas WHERE status = 'ativa'").fetchone()[0]
    canceladas = conexao.execute(
        "SELECT COUNT(*) FROM assinaturas WHERE status = 'cancelada'").fetchone()[0]
    faturamento = bd.faturamento_total(conexao)
    ticket = faturamento / contagem["pagos"] if contagem["pagos"] else 0.0
    cupons_ativos = conexao.execute(
        "SELECT COUNT(*) FROM cupons WHERE ativo = 1").fetchone()[0]
    return {
        "usuarios_total": contagem["total"],
        "usuarios_pagos": contagem["pagos"],
        "usuarios_free": contagem["free"],
        "usuarios_ativos": contagem["ativos"],
        "usuarios_inativos": contagem["inativos"],
        "assinaturas_ativas": ativas,
        "assinaturas_canceladas": canceladas,
        "faturamento": faturamento,
        "ticket_medio": ticket,
        "cupons_ativos": cupons_ativos,
    }


def definir_status_usuario(conexao: sqlite3.Connection, usuario_id: int,
                           ativo: bool) -> None:
    """Ativa ou inativa uma conta (usado pelo administrador)."""
    bd.atualizar_usuario(conexao, usuario_id, ativo=int(ativo))


def definir_admin(conexao: sqlite3.Connection, usuario_id: int, admin: bool) -> None:
    """Concede ou revoga o perfil de administrador."""
    bd.atualizar_usuario(conexao, usuario_id, is_admin=int(admin))
