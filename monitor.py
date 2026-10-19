"""
monitor.py
----------
Monitor das fontes oficiais que servem de base ao motor fiscal.

O painel administrativo guarda uma impressão digital (hash SHA-256) do
conteúdo de cada fonte. Ao apertar **Buscar mudanças**, o monitor baixa as
páginas de novo e compara: se o texto mudou, o app avisa — é o gatilho para
revisar a tabela de cálculo (alíquotas, isenções, código do DARF).

Não depende de nenhuma API paga: usa apenas ``urllib``, da biblioteca padrão.
A persistência do que já foi verificado fica em ``persistencia.py``.

Uso:
    import monitor
    monitor.verificar(conexao)          # baixa e compara todas as fontes
    monitor.ultima_verificacao(conexao)
"""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from datetime import date

import persistencia as bd

#: Fontes oficiais acompanhadas. A ``url`` é a chave usada no banco.
FONTES = (
    {
        "titulo": "Lei 15.270/2025 — IRRF sobre dividendos e imposto mínimo",
        "url": "https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/lei/l15270.htm",
    },
    {
        "titulo": "Lei 11.033/2004 — IR sobre renda variável (alíquotas e isenções)",
        "url": "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2004/lei/l11033.htm",
    },
    {
        "titulo": "Lei 8.668/1993 — fundos imobiliários",
        "url": "https://www.planalto.gov.br/ccivil_03/leis/l8668.htm",
    },
    {
        "titulo": "Receita Federal — IN RFB 1.585/2015 (ganhos líquidos)",
        "url": "http://normas.receita.fazenda.gov.br/sijut2consulta/link.action"
               "?visao=anotado&idAto=67466",
    },
)

#: Dias sem verificação a partir dos quais o painel exibe um alerta.
DIAS_ALERTA = 30


def _baixar(url: str, timeout: int = 20) -> bytes | None:
    """
    Baixa o conteúdo de uma fonte oficial (bytes) ou ``None`` se falhar.

    Devolve bytes para que o hash não dependa da codificação da página.
    """
    requisicao = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (MonitorLegislacao; gestor-investimentos)"},
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            return resposta.read()
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def verificar(conexao) -> list[dict]:
    """
    Baixa cada fonte e compara com a última versão conhecida.

    Devolve, por fonte, ``{"titulo", "url", "situacao"}`` onde ``situacao`` é
    ``"mudou"``, ``"igual"``, ``"primeira"`` (nunca verificada antes) ou
    ``"falhou"`` (a fonte não respondeu).
    """
    anteriores = bd.carregar_monitor_legislacao(conexao)
    resultados: list[dict] = []

    for fonte in FONTES:
        url = fonte["url"]
        anterior = anteriores.get(url)
        conteudo = _baixar(url)

        if conteudo is None:
            situacao = "falhou"
            hash_conteudo = None
        else:
            hash_conteudo = hashlib.sha256(conteudo).hexdigest()
            if anterior is None or not anterior.get("hash"):
                situacao = "primeira"
            elif anterior["hash"] != hash_conteudo:
                situacao = "mudou"
            else:
                situacao = "igual"

        if situacao != "falhou":
            bd.gravar_monitor_legislacao(
                conexao, url, fonte["titulo"], hash_conteudo,
                mudou=situacao in ("mudou", "primeira"),
            )

        resultados.append({"titulo": fonte["titulo"], "url": url,
                           "situacao": situacao})
    return resultados


def ultima_verificacao(conexao) -> date | None:
    """Data da verificação mais recente (ou ``None`` se nada foi verificado)."""
    registros = bd.carregar_monitor_legislacao(conexao)
    datas = [registro["verificado_em"] for registro in registros.values()
             if registro.get("verificado_em")]
    if not datas:
        return None
    return max(date.fromisoformat(str(data)[:10]) for data in datas)


__all__ = ["FONTES", "DIAS_ALERTA", "verificar", "ultima_verificacao"]
