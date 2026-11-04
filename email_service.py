"""
email_service.py
----------------
Serviço de envio de e-mails transacionais (recuperação de senha e avisos de DARF).
Utiliza a biblioteca padrão do Python (smtplib) com suporte a SSL (porta 465)
e TLS/STARTTLS (porta 587).

Configuração em .streamlit/secrets.toml (local) ou App Settings -> Secrets (Streamlit Cloud):
    [smtp]
    servidor  = "smtp.gmail.com"
    porta     = 587
    usuario   = "seu-email@gmail.com"
    senha     = "sua-senha-de-app"
    remetente = "FiscoTrade <suporte@fiscotrade.com>"
    usar_tls  = true

Se o bloco [smtp] não estiver configurado nos segredos, o serviço opera em modo
simulado (fallback seguro), sem quebrar o app e exibindo o código para testes.
"""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st


def obter_config_smtp() -> dict | None:
    """Lê as credenciais SMTP de st.secrets['smtp'] se existirem."""
    try:
        conf = st.secrets.get("smtp")
        if not conf:
            return None
        servidor = str(conf.get("servidor", "")).strip()
        usuario = str(conf.get("usuario", "")).strip()
        senha = str(conf.get("senha", "")).strip()
        if not (servidor and usuario and senha):
            return None

        porta = int(conf.get("porta", 587))
        remetente = str(conf.get("remetente", usuario)).strip()
        usar_tls = bool(conf.get("usar_tls", porta != 465))
        usar_ssl = bool(conf.get("usar_ssl", porta == 465))

        return {
            "servidor": servidor,
            "porta": porta,
            "usuario": usuario,
            "senha": senha,
            "remetente": remetente,
            "usar_tls": usar_tls,
            "usar_ssl": usar_ssl,
        }
    except Exception:
        return None


def smtp_configurado() -> bool:
    """Informa se o envio real por SMTP está habilitado."""
    return obter_config_smtp() is not None


def enviar_email(destinatario: str, assunto: str, html: str, texto: str = "") -> tuple[bool, str]:
    """
    Envia um e-mail com partes HTML e texto puro.

    Retorna (sucesso: bool, mensagem: str).
    """
    config = obter_config_smtp()
    if not config:
        return False, "SMTP não configurado em st.secrets['smtp'] (modo de teste ativo)."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = assunto
        msg["From"] = config["remetente"]
        msg["To"] = destinatario

        if texto:
            msg.attach(MIMEText(texto, "plain", "utf-8"))
        if html:
            msg.attach(MIMEText(html, "html", "utf-8"))

        if config["usar_ssl"]:
            server = smtplib.SMTP_SSL(config["servidor"], config["porta"], timeout=12)
        else:
            server = smtplib.SMTP(config["servidor"], config["porta"], timeout=12)
            if config["usar_tls"]:
                server.starttls()

        server.login(config["usuario"], config["senha"])
        server.sendmail(config["remetente"], [destinatario], msg.as_string())
        server.quit()
        return True, "E-mail enviado com sucesso."
    except Exception as erro:
        return False, f"Falha no envio de e-mail: {erro}"


def enviar_codigo_recuperacao(email: str, token: str, nome: str = "") -> tuple[bool, str]:
    """Monta o template HTML e envia o código de recuperação de senha."""
    saudacao = f"Olá, {nome.split()[0]}!" if nome else "Olá!"
    assunto = f"FiscoTrade — Seu código de recuperação de senha: {token}"

    texto_puro = f"""{saudacao}

Você solicitou a recuperação de senha no FiscoTrade.
Seu código de verificação é: {token}

Este código é válido por 1 hora.
Se você não solicitou a recuperação, desconsidere esta mensagem.

Equipe FiscoTrade
"""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;line-height:1.6;color:#1F2933;background-color:#F4F6F8;margin:0;padding:24px;">
  <div style="max-width:540px;margin:0 auto;background:#FFFFFF;border-radius:12px;padding:32px;box-shadow:0 2px 8px rgba(0,0,0,0.06);border:1px solid #E5E7EB;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:20px;border-bottom:2px solid #17776C;padding-bottom:12px;">
      <h2 style="margin:0;color:#17776C;font-size:22px;letter-spacing:-0.5px;">FiscoTrade</h2>
    </div>
    <p style="font-size:15px;color:#374151;">{saudacao}</p>
    <p style="font-size:15px;color:#374151;">Recebemos uma solicitação para redefinir a senha da sua conta. Use o código abaixo para prosseguir:</p>
    <div style="text-align:center;margin:28px 0;">
      <span style="display:inline-block;background:#EAF4F2;color:#0E3B37;font-size:28px;font-weight:700;letter-spacing:6px;padding:14px 28px;border-radius:8px;border:1px dashed #17776C;">
        {token}
      </span>
    </div>
    <p style="font-size:13px;color:#6B7280;margin-bottom:24px;">
      ⏳ Este código é de uso único e expira em <b>1 hora</b>.<br>
      Se você não solicitou essa redefinição, nenhuma ação é necessária. Sua senha permanece segura.
    </p>
    <hr style="border:none;border-top:1px solid #E5E7EB;margin:24px 0;">
    <p style="font-size:12px;color:#9CA3AF;text-align:center;margin:0;">
      FiscoTrade — Apuração e Controle de DARF de Renda Variável.
    </p>
  </div>
</body>
</html>"""

    return enviar_email(email, assunto, html, texto_puro)
