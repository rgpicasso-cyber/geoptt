# GeoPTT — Registro de Estado e Rastreabilidade

> **Arquivo append-only.** Nunca apague ou edite entradas antigas. Cada sessão de
> trabalho adiciona uma entrada nova no topo da seção "Histórico" (ou ao final,
> mantendo a ordem cronológica) com data, o que foi feito, decisões, bugs conhecidos
> e o próximo passo exato.

---

## Estado Atual (snapshot)

| Item | Valor |
|---|---|
| Fase concluída | **Fase 1 — Setup e Rastreabilidade** |
| Fase em andamento | **nenhuma** (aguardando aprovação para Fase 2) |
| Última atualização | 2026-10-28 |
| Stack | Flutter · FastAPI (Python 3.12) · PostgreSQL/PostGIS · SQLite · WebSockets · FCM · OSM/`flutter_map` · `just_audio` · Opus |
| Infra de produção | VPS Ubuntu `163.176.229.20`, usuário `ubuntu`, acesso por chave SSH |
| Código de produção | **zero linhas** (por decisão de processo) |
| Segredos no repositório | **nenhum** (verificado) |

---

## Histórico

### 2026-10-28 — Entrada #001 — Bootstrap documental e blindagem de credenciais

**Contexto:** início do projeto. Sessão dedicada exclusivamente a estruturar o
"cérebro" do projeto (Spec-Driven Development) e proteger as credenciais da VPS,
**sem escrever código de produção** (Python ou Dart), conforme instrução do usuário.

**O que foi feito**

1. **`.gitignore` (raiz)** criado com 9 blocos: segredos/chaves privadas (`.env`,
   `*.pem`, `*.key`, `*.rsa`, `*.ppk`, `*.p12`, `*.jks`, keystores, `id_rsa*`,
   `ssh-key-2026-09-24.key`), credenciais Firebase (`serviceAccountKey.json`,
   `google-services.json`, `GoogleService-Info.plist`), certificados TLS, segredos de
   deploy, Python/FastAPI, Flutter/Dart, bancos locais, logs, IDEs, arquivos de SO e
   estado local do OpenCode.
2. **`.opencode/rules.md`** consolidado (arquivo já existia e foi preservado):
   stack fechada, padrões Flutter/FastAPI, rastreabilidade obrigatória, testes por
   fase, commits convencionais. **Acréscimos desta sessão:** `just_audio` +
   `audio_session` na linha de áudio; §8 *Gate Documental (docs-first)*; §9
   *Credenciais e Infraestrutura de Produção*; §10 *Definition of Done*.
3. **`docs/ARCHITECTURE.md`** criado: visão geral, 7 princípios arquiteturais,
   componentes (Flutter/FastAPI/infra), diagrama ASCII completo do fluxo crítico
   **App → FCM Wakeup → Foreground Service → WebSocket → FastAPI → estado
   reconciliado**, fluxo de áudio PTT half-duplex, fluxo de localização (smart ping),
   envelope de contrato WS, segurança, **§9 Infraestrutura de Produção** com VPS
   Ubuntu `163.176.229.20` / usuário `ubuntu` / acesso por chave e **ALERTA EM
   NEGRITO** contra chaves no repositório, hardening, Nginx (`Upgrade`/`Connection`),
   matriz de ambientes, tabela de riscos (R1–R7) e 5 ADRs pendentes.
4. **`docs/DATA_MODEL.md`** criado: diagrama de entidades, definição de `users`
   (**`fcm_token`**, **`battery_level`**, `platform`, `is_sharing_location`),
   `circles`, `circle_members`, `locations` (posição atual), `location_history`
   (série temporal com `client_seq` para idempotência), `ptt_channels`,
   `ptt_channel_members`, `ptt_sessions`, `refresh_tokens`; DDL PostgreSQL 16 +
   PostGIS 3 completa, equivalência SQLite (fila offline), regras transversais,
   queries de referência (ST_DWithin, distância percorrida) e resumo LGPD.
5. **`docs/TASKS.md`** criado: painel das 6 fases + detalhamento tarefa-por-tarefa
   com critério de saída por fase. Fase 1 marcada `[X]`; Fases 2–6 em `[ ]`.
6. **`docs/STATE_TRACEABILITY.md`** (este arquivo) criado.

**Decisões técnicas tomadas**

| # | Decisão | Justificativa |
|---|---|---|
| D1 | `.gitignore` na **raiz** com padrões amplos de chaves | rede de segurança em profundidade; cobre nomes futuros de chave |
| D2 | `lat/lng` como fonte de verdade + `geom` derivado em `locations` | portabilidade (SQLite) + índice GiST sem depender de coluna gerada |
| D3 | `locations` (atual) separada de `location_history` | mapa rápido sem varrer série temporal |
| D4 | `UNIQUE (user_id, client_seq)` no histórico | reenvio de fila offline idempotente, sem duplicar trilha |
| D5 | Estado de fala PTT **em memória**, não em tabela | fala é efêmera; restart do processo deve liberar canais |
| D6 | Hub WS single-node no MVP (sem Redis/pub-sub) | stack fechada; escala horizontal exige ADR-001 |
| D7 | `fcm_token` único em `users` no MVP | simplicidade; multi-device vira ADR/tabela `user_devices` depois |
| D8 | FCM carrega apenas ponteiro, nunca áudio | limite de 4 KB e áudio perecível |
| D9 | Nenhum código de produção nesta sessão | instrução explícita do usuário; evita retrabalho de contrato |

**Verificações executadas**

- [x] Árvore do projeto inspecionada: existia apenas `.opencode/` (rules + 8 skills +
      agente `geoptt_techlead`). Nenhuma pasta `docs/` preexistente.
- [x] `C:\Nexo` **não** é um repositório Git ainda (`git status` → *not a git
      repository*). O `.gitignore` já está pronto para o `git init`.
- [x] Busca por `*ssh*` em `C:\Nexo`, `%USERPROFILE%\.ssh`, `Downloads`, `Desktop` e
      `%TEMP%`: **nenhum arquivo de chave foi localizado dentro da árvore do
      projeto**. A chave `ssh-key-2026-09-24.key` permanece fora do repositório,
      conforme exigido.

**Bugs conhecidos**

- Nenhum bug de código (não há código ainda).
- **Pendência de segurança:** se a chave `ssh-key-2026-09-24.key` foi exposta em
  chat, print ou log durante a obtenção do acesso, ela deve ser considerada
  comprometida → gerar novo par na VPS, revogar a antiga em
  `~/.ssh/authorized_keys` e registrar o incidente aqui.

**Riscos em aberto (herdados da Fase 1)**

- R2: fabricantes Android agressivos podem matar o relay → validar na Fase 3.
- R3: PushKit VoIP pode ser questionado na App Store → ADR-002 na Fase 3.
- R7: ausência de PostGIS no ambiente local → abstrair em `GeoRepository` na Fase 2.

**Próximo passo exato (Fase 2 — Backend FastAPI)**

> Iniciar em `backend/`: criar `pyproject.toml` (Python 3.12, `ruff`, `mypy --strict`,
> `pytest`, `pytest-asyncio`, `httpx`), `app/core/config.py` com `pydantic-settings`,
> `app/main.py` com factory + `lifespan`, `.env.example` sem valores, e a primeira
> migration Alembic com o DDL de `docs/DATA_MODEL.md` §3 (incluindo
> `CREATE EXTENSION postgis`). Só depois seguir para auth e o hub WebSocket.

**Arquivos criados/alterados nesta entrada**

```
.gitignore                      (novo)
.opencode/rules.md              (alterado — §8, §9, §10 + linha de áudio)
docs/ARCHITECTURE.md            (novo)
docs/DATA_MODEL.md              (novo)
docs/TASKS.md                   (novo)
docs/STATE_TRACEABILITY.md      (novo — este arquivo)
```

---

## Template para próximas entradas

```markdown
### AAAA-MM-DD — Entrada #NNN — <título curto>

**Contexto:** <por que esta sessão existiu>

**O que foi feito**
1. ...

**Decisões técnicas tomadas**
| # | Decisão | Justificativa |
|---|---|---|

**Verificações executadas**
- [x] <comando/teste> → <resultado>

**Bugs conhecidos**
- ...

**Próximo passo exato**
> ...

**Arquivos criados/alterados nesta entrada**
```text
<lista>
```
```
