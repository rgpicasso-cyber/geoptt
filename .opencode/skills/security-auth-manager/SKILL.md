---
name: security-auth-manager
description: Regras para autenticação de usuários, JWT e segurança em conexões WebSocket e REST.
---

# Security & Auth Manager Skill

## Quando usar esta Skill
Sempre que for criar endpoints de login, registro, geração de tokens, e principalmente ao proteger as rotas de WebSocket no FastAPI.

## Regras de Ouro
1. **JWT Híbrido:** Utilize JSON Web Tokens (JWT) para autenticação.
2. **WebSocket Auth:** Como clientes Flutter podem ter dificuldade em enviar Headers HTTP puros no handshake do WebSocket, a autenticação do WebSocket DEVE ser feita de duas formas aceitáveis:
   - Enviando o token como "query parameter" (ex: `ws://server/ws?token=ABC`).
   - Ou o backend aceita a conexão anônima, mas o primeiro payload obrigatório enviado pelo cliente deve ser `{"type": "AUTH", "token": "..."}`. Se não enviar em 3 segundos, o backend derruba a conexão.
3. **Criptografia:** Senhas devem obrigatoriamente ser hasheadas usando `passlib` (bcrypt) no FastAPI antes de irem para o banco (SQLite/Postgres).
