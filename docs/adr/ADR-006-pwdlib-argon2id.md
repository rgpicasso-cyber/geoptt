# ADR-006 — Trocar `passlib` por `pwdlib` com Argon2id

- **Status:** Aceito
- **Data:** 2026-10-28
- **Fase:** 2 (Backend FastAPI)
- **Substitui:** o uso de `passlib[bcrypt]` + `bcrypt>=4.2,<5` registrado na entrada #003

---

## Contexto

A base do backend (entrada #003) usava `passlib` 1.7.4 com o backend `bcrypt`.
Durante a validação apareceram dois problemas:

1. **`passlib` está sem manutenção desde 2020.** O último release é 1.7.4.
2. **Quebra com `bcrypt` 5.x.** No *self-test* do backend, `passlib` chama
   `bcrypt.hashpw` com uma senha de mais de 72 bytes. A partir do `bcrypt` 5.0 esse
   caso passou a levantar `ValueError`, o que **impede a inicialização do
   `CryptContext`** — ou seja, a aplicação não sobe.
   Foi necessário fixar `bcrypt>=4.2,<5` para contornar.
3. Mesmo com o pin, `passlib` loga `(trapped) error reading bcrypt version` na
   primeira utilização, porque lê `bcrypt.__about__` (removido no `bcrypt` 4.1+).

O pin de teto é uma dívida: impede receber correções de segurança do `bcrypt`.

## Decisão

Substituir `passlib` por **`pwdlib` 0.3.x** e trocar o algoritmo de **bcrypt** para
**Argon2id** (`PasswordHash.recommended()`).

Consequências diretas no código:

- `app/core/security.py` usa `pwdlib.PasswordHash` em vez de `passlib.CryptContext`.
- `BCRYPT_MAX_PASSWORD_BYTES = 72` deixa de existir. O limite passa a ser uma
  **política de aplicação**: `MAX_PASSWORD_BYTES = 128` (defensivo, contra DoS de
  hashing), não uma limitação do algoritmo.
- O pin `bcrypt<5` é removido de `pyproject.toml`.
- `logging.getLogger("passlib.handlers.bcrypt")` deixa de ser silenciado.
- `types-passlib` sai das dependências de desenvolvimento.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Manter `passlib` + `bcrypt<5` | Dívida permanente; sem manutenção; impede atualizações de segurança do `bcrypt`. |
| `bcrypt` direto (sem `passlib`) | Resolve o bug, mas mantém o bcrypt (limite de 72 bytes, custo fixo) e exige escrever o `verify_and_update` à mão. |
| `argon2-cffi` direto | Boa biblioteca, mas `pwdlib` já entrega a fachada com `verify_and_update` e migração de hash pronta. |
| `pwdlib` com `BcryptHasher` | Preservaria o limite de 72 bytes sem ganho algum — não há hashes legados em produção. |

## Consequências

**Positivas**

- Sem pin de teto no `bcrypt`; superfície de dependências menor.
- Argon2id é o vencedor da Password Hashing Competition e a recomendação atual da
  OWASP para novos sistemas (resistente a GPU/ASIC).
- `verify_and_update()` permite re-hash transparente no login se os parâmetros de
  custo mudarem no futuro.
- Sem senha truncada silenciosamente aos 72 bytes.

**Negativas / custos**

- Argon2id consome mais memória por hash (`m=65536` KiB, `t=3`, `p=4` no default do
  `pwdlib`). Em um VPS pequeno isso limita a taxa de logins concorrentes. Mitigação:
  o rate limit de 5 req/min/IP em `/auth/*` já limita a pressão.
- Hashes bcrypt antigos **não** seriam verificáveis. Como não existe base de usuários
  em produção (a Fase 2 é a primeira migration), não há migração de dados.
- `pwdlib` é um projeto jovem (0.3.x). Mitigação: API minúscula (`hash`, `verify`,
  `verify_and_update`) isolada atrás de `app/core/security.py` — trocar de biblioteca
  no futuro afeta um único módulo.

## Verificação

- `tests/test_security.py` cobre roundtrip, salt, senha longa (128 bytes), hash
  corrompido e política de senha.
- Um hash gerado deve começar com `$argon2id$`.
- `pip install -e ".[dev]"` não deve mais resolver `passlib` nem `bcrypt`.

## Referências

- `docs/STATE_TRACEABILITY.md` entrada #003 (origem do problema).
- `docs/ARCHITECTURE.md` §7.1 (regras transversais de autenticação).
- OWASP Password Storage Cheat Sheet — Argon2id como primeira escolha.
