---
name: vps-deployment-ops
description: Padrões de infraestrutura para deploy do FastAPI em servidor VPS Linux, Proxy Reverso e SSL.
---

# VPS & Deployment Ops Skill

## Quando usar esta Skill
Na configuração do ambiente de produção (Ubuntu VPS), geração de certificados SSL e configuração do Nginx ou Uvicorn.

## Regras de Ouro
1. **WebSockets Seguros (WSS):** O aplicativo Flutter DEVE ser configurado para usar `wss://` e `https://` em produção. Conexões sem criptografia serão bloqueadas pelo OS móvel.
2. **Nginx Reverse Proxy:** O FastAPI (rodando via Uvicorn/Gunicorn no IP interno/localhost) deve ficar atrás de um proxy reverso Nginx.
3. **Upgrade de Conexão Nginx:** O bloco de configuração do Nginx DEVE conter as diretivas de upgrade para suportar WebSockets:
   ```nginx
   proxy_set_header Upgrade $http_upgrade;
   proxy_set_header Connection "upgrade";
   ```
