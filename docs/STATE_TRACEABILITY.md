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
| Fase em andamento | **Fase 2 — Backend FastAPI** (base + migration prontas; auth/REST pendentes) |
| Última atualização | 2026-10-28 |
| Stack | Flutter · FastAPI (Python 3.12) · PostgreSQL/PostGIS · SQLite · WebSockets · FCM · OSM/`flutter_map` · `just_audio` · Opus |
| Infra de produção | VPS Ubuntu `163.176.229.20`, usuário `ubuntu`, acesso por chave SSH |
| Código de produção | `backend/` — 31 módulos, 42 arquivos formatados, **100 testes** |
| Qualidade | `ruff check` ✅ · `ruff format --check` ✅ · `mypy --strict` ✅ (31 arquivos) |
| Migration | `0001_initial` — 9 tabelas, PostGIS + pgcrypto, validada em modo **offline** |
| Repositório Git | **inicializado** em `main`; Fase 1 em `e1c1379`, Fase 2 commitada (entrada #003) |
| Segredos no repositório | **nenhum** (verificado no index e no histórico) |
| Chave SSH | `C:\Nexo\ssh-key-2026-09-24.key` — presente no disco, **ignorada pelo Git** |

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

### 2026-10-28 — Entrada #002 — Inicialização do repositório Git

**Contexto:** a Fase 1 estava concluída, mas `C:\Nexo` ainda não era um repositório
Git — o `.gitignore` não protegia nada de fato. O usuário também informou que a chave
`ssh-key-2026-09-24.key` **não foi exposta** em chat/log (permanece válida, sem
necessidade de rotação) e que ela foi movida para o diretório raiz do projeto.

**O que foi feito**

1. **Verificação prévia da chave:** listagem de metadados (nome/tamanho) em `C:\Nexo`
   confirmou `ssh-key-2026-09-24.key` (1.679 bytes) na raiz. **Conteúdo não foi
   aberto nem impresso** em nenhum momento.
2. **`.gitattributes`** criado: `* text=auto eol=lf`, regras por extensão, binários
   marcados (`*.aab`, `*.apk`, `*.ipa`, mídia) e segredos (`*.key`, `*.pem`, `*.p12`,
   `*.jks`) tratados como binários para não vazar conteúdo em diff de CI.
3. **`git init -b main`** executado na raiz.
4. **Proteção em duas camadas** contra versionamento da chave:
   - camada 1 (versionada): `.gitignore` linha 34 → `ssh-key-*.key`;
   - camada 2 (local, não versionada): `.git/info/exclude` com `ssh-key-*.key`,
     `*.key`, `*.pem`, `.env`. Sobrevive a uma edição acidental do `.gitignore`.
5. **Identidade Git local** configurada (apenas neste repo, não altera a global):
   `GeoPTT TechLead <techlead@geoptt.local>`.
6. **Varredura pré-commit** do index com regex de segredos → 0 ocorrências.
7. **Commit `912c390`** — `docs: bootstrap fase 1 - arquitetura, modelo de dados,
   roadmap e protecao de credenciais` (16 arquivos).

**Decisões técnicas tomadas**

| # | Decisão | Justificativa |
|---|---|---|
| D10 | Branch inicial `main` | padrão moderno; evita renomear depois |
| D11 | `.git/info/exclude` além do `.gitignore` | defesa em profundidade contra edição acidental do ignore |
| D12 | Identidade **local** e neutra (`techlead@geoptt.local`) | não polui a config global da máquina; trivial trocar com `--amend --reset-author` |
| D13 | `.gitattributes` com `eol=lf` | repositório consistente entre Windows (dev) e Ubuntu (VPS) |
| D14 | Chave **mantida** na raiz (decisão do usuário), não movida | usuário confirmou que não houve exposição; risco residual aceito e documentado |

**Verificações executadas**

- [x] `git check-ignore -v -- ssh-key-2026-09-24.key` →
      `.gitignore:34:ssh-key-*.key` (regra que casa).
- [x] `git add -A` + inspeção do index: 16 arquivos, **nenhum** `.key`/`.pem`/`.env`.
- [x] `git ls-files` → nenhuma chave rastreada.
- [x] `git log --all --diff-filter=A --name-only` → **nenhuma chave em nenhum commit**.
- [x] `git status --short --branch` → `## main` (árvore limpa).
- [x] Chave ainda presente no disco após o commit (1.679 bytes) — o Git não a tocou.

**Bugs conhecidos**

- Nenhum.
- **Risco residual aceito (R6.1):** a chave privada vive dentro da árvore do projeto.
  Um `git add -f ssh-key-2026-09-24.key` a forçaria para o index. Mitigação atual:
  dupla camada de ignore + varredura pré-commit + regra §9 do `rules.md`.
  **Recomendação futura:** mover para `C:\Users\<usuario>\.ssh\` (fora do repo) e
  ajustar o comando de deploy.

**Próximo passo exato (Fase 2 — Backend FastAPI)**

> Criar `backend/pyproject.toml` (Python 3.12, `ruff`, `mypy --strict`, `pytest`,
> `pytest-asyncio`, `httpx`), `backend/app/core/config.py` (`pydantic-settings`),
> `backend/app/main.py` (factory + `lifespan`), `backend/.env.example` sem valores e
> a migration inicial Alembic com o DDL de `docs/DATA_MODEL.md` §3
> (`CREATE EXTENSION postgis` incluído).

**Arquivos criados/alterados nesta entrada**

```
.gitattributes                  (novo)
.git/info/exclude               (alterado — camada 2 de proteção, local)
docs/STATE_TRACEABILITY.md      (alterado — snapshot + esta entrada)
```

**Commits**

```
912c390  docs: bootstrap fase 1 - arquitetura, modelo de dados, roadmap e protecao de credenciais
```

---

### 2026-10-28 — Entrada #003 — Base do backend FastAPI e migration PostGIS

**Contexto:** Fase 2 autorizada pelo usuário com escopo explícito: gerar a base do
backend (config, app factory, hub WebSocket, fallback FCM), a migration inicial com
PostGIS, os testes e a atualização da rastreabilidade. Fechamento pedido pelo usuário:
*"Me avise quando a base do FastAPI e a migration estiverem prontas."*

**O que foi feito**

1. **`backend/pyproject.toml`** — Python 3.12, deps de runtime (`fastapi`,
   `uvicorn[standard]`, `websockets`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`,
   `geoalchemy2`, `firebase-admin`, `passlib[bcrypt]`, `bcrypt`, `pyjwt`,
   `pydantic-settings`) e de dev (`pytest`, `pytest-asyncio`, `httpx`, `aiosqlite`,
   `ruff`, `mypy`, `types-passlib`). Configuração de `ruff` (line-length 100,
   E/W/F/I/N/UP/B/C4/ASYNC/S/RET/SIM/TID/PL/RUF), `mypy --strict` e `pytest`.
2. **`app/core/config.py`** — `Settings` com `pydantic-settings`, normalização de
   `DATABASE_URL` (`postgres://` → `postgresql+asyncpg://`), `JWT_SECRET` em
   `SecretStr`, validadores que **recusam** subir `ENV=production` com segredo de dev,
   `DEBUG=true` ou `FCM_ENABLED=true` sem credenciais; `masked_database_url`.
3. **`app/core/logging.py`** — `JsonFormatter` + `RedactionFilter` com regexes para
   JWT, pares `token=/password=/fcm_token=` e coordenadas com 5+ casas decimais.
4. **`app/core/security.py`** — bcrypt via `passlib`, JWT (`create_token`,
   `decode_token`, `TokenType` ACCESS/REFRESH), `hash_token` (SHA-256) para refresh
   tokens persistidos, `generate_opaque_token`.
5. **`app/db/base.py` / `app/db/session.py`** — `Base` com *naming convention*
   explícita (`pk_`, `fk_`, `ux_`, `ix_`, `ck_`) e `Database` com engine async.
6. **`app/models/`** — 9 tabelas 2.0-style (`Mapped[]` + `mapped_column()`):
   `users`, `circles`, `circle_members`, `locations`, `location_history`,
   `ptt_channels`, `ptt_channel_members`, `ptt_sessions`, `refresh_tokens`.
   Colunas geoespaciais em `GEOGRAPHY(POINT, 4326)` com índice GiST.
7. **`alembic/versions/0001_initial_schema.py`** — migration inicial **escrita à mão**
   (não autogerada): `CREATE EXTENSION IF NOT EXISTS postgis` + `pgcrypto`, 3 enums,
   9 tabelas, índice parcial único `ux_circle_single_owner`, `ux_history_user_seq`
   (idempotência de reenvio) e 2 índices GiST. `upgrade()` levanta `RuntimeError` se o
   dialeto não for `postgresql`; `downgrade()` **não** remove as extensões.
8. **`app/services/connection_manager.py`** — `Connection` com **writer task única**
   (o Starlette não suporta `send` concorrente no mesmo socket), fila de controle
   (cheia → fecha a conexão, nunca perde mensagem) e fila de áudio limitada com
   **drop-oldest**. `ConnectionManager` com presença por usuário, múltiplos devices,
   `send_to_user`, `broadcast`, `send_audio_to_user`, `stats` e `close_all`.
9. **`app/services/ptt_service.py`** — half-duplex por canal com lock, hierarquia de
   erros (`PttBusyError`, `PttNotMemberError`, `PttCannotSpeakError`,
   `PttChannelNotFoundError`, `PttChannelInactiveError`, `PttNotSpeakingError`),
   watchdog de locutor e `PTT_SPEAKER_START/STOP`.
10. **`app/services/fcm_service.py`** — `FcmService` (firebase-admin),
    `SlidingWindowLimiter` por usuário, `build_message` **data-only** com
    `android.priority="high"`, `apns-push-type=background`, `apns-priority=5`,
    `content-available: 1`; detecção de token `UNREGISTERED` e `mask_token` para log.
11. **`app/api/ws/ptt.py`** — `/ws` com auth por `?token=` ou frame `AUTH` em até
    `WS_AUTH_TIMEOUT_SECONDS` (3 s), close `4401`/`4402` **após** `accept` (para o
    cliente ler o código), heartbeat `4408`, dispatch de `PING`/`PTT_DOWN`/`PTT_UP`,
    frames binários encaminhados como áudio do locutor.
12. **`app/main.py`** — `create_app()` com `lifespan` moderno (DB → FCM → serviços em
    `app.state`), CORS, routers `/health` e `/health/ready`, `/docs` desabilitado em
    produção.
13. **Testes (100)** — `test_connection_manager.py` (backpressure, fila de controle,
    concorrência), `test_fcm_service.py` (payload, rate limit, UNREGISTERED, erros
    transitórios), `test_security.py` (bcrypt, JWT, redação, validadores de produção),
    `test_ws_auth.py` (handshake, timeouts, envelope), `test_schema_metadata.py`
    (**drift guard** ORM × migration).

**Decisões técnicas tomadas**

| # | Decisão | Justificativa |
|---|---|---|
| D15 | **Sem** `sqlalchemy.ext.mypy.plugin` | SQLAlchemy 2.1 removeu o plugin. Modelos 2.0-style (`Mapped[]`) passam em `mypy --strict` sem ele. |
| D16 | `bcrypt>=4.2,<5` (pin de teto) | `passlib` 1.7.4 faz self-test do backend com senha > 72 bytes; `bcrypt` 5.x levanta `ValueError` e **quebra a inicialização** do `CryptContext`. 4.3.0 validado. |
| D17 | `PyJWT` em vez de `python-jose` | manutenção ativa e API menor; `python-jose` está estagnado. |
| D18 | FCM wake-up **1× por `PTT_DOWN`** | disparar por chunk de áudio inundaria o FCM e estouraria quota/latência. |
| D19 | Estado de canal PTT **em memória** | MVP single-node; Redis/pub-sub exige ADR-001 antes de escalar horizontalmente. |
| D20 | `Connection` com writer task + filas | `WebSocket.send_*` concorrente corrompe o frame no Starlette; a fila de áudio descarta o frame mais antigo (latência > integridade para voz). |
| D21 | Migration escrita à mão | o autogenerate não produz `CREATE EXTENSION`, `geography(POINT,4326)` nem índice parcial único de forma confiável. |
| D22 | `Message.token` mantido (deprecado em firebase-admin 7.7) | `fid` (Firebase Installation ID) precisa ser validado contra a API real do FCM antes da troca; warning filtrado no pytest. |
| D23 | `known-third-party = ["alembic"]` no Ruff | o diretório local `alembic/` fazia o isort tratar o pacote do PyPI como first-party, gerando agrupamento de imports incorreto. |
| D24 | Constraint names de `CheckConstraint` **sem** prefixo na migration | a naming convention `ck_%(constraint_name)s` re-prefixa; passar `ck_locations_lat_range` produzia `ck_locations_ck_locations_lat_range`. |
| D25 | UUID PKs com `server_default=text("gen_random_uuid()")` | paridade com o DDL aplicado; sem isso o `autogenerate` proporia `DROP DEFAULT` espúrio. |
| D26 | `UniqueConstraint(circle_id, user_id)` removida de `circle_members` | a PK composta já garante unicidade; a constraint extra criaria índice redundante. |

**Verificações executadas**

- [x] `ruff check .` → **All checks passed!**
- [x] `ruff format --check .` → **42 files already formatted**
- [x] `mypy app` → **Success: no issues found in 31 source files**
- [x] `pytest` → **100 passed in 3.72s**
- [x] `alembic upgrade head --sql` (offline, sem PostgreSQL) → 166 linhas: PostGIS +
      pgcrypto, 3 enums, 9 tabelas, `geography(POINT,4326)` ×2, `USING gist (geom)` ×2
- [x] `tests/test_schema_metadata.py` → nomes de constraints e índices do ORM **idênticos**
      aos da migration (bidirecional); 9 tabelas mapeadas; `gen_random_uuid()` presente
- [x] `git check-ignore -v` → `backend/.env`, `backend/.venv`, `serviceAccountKey.json`,
      `__pycache__` todos ignorados; `git add -n backend/.env.example` → **adicionável**
- [x] `migration_preview.sql` (artefato temporário da validação) removido
- [x] Nenhum `.env`, `.key`, `.pem` ou credencial no index

**Bugs conhecidos**

- **`passlib` 1.7.4 sem manutenção.** Loga `(trapped) error reading bcrypt version`
  na primeira utilização (não afeta o hash). Candidato a ADR: substituir por `pwdlib`.
- **`Message.token` deprecado** no firebase-admin 7.7 em favor de `fid`. Migração
  pendente de validação contra a API real.
- **Migration não executada de verdade.** O ambiente atual não tem PostgreSQL, Docker
  nem `psql`. A validação foi *offline* (`--sql`) + drift guard. **O DDL real precisa
  rodar no VPS ou no ambiente do usuário** antes de considerar 2.2 fechada.
- **`LOCATION_BATCH`/`LOCATION_UPDATE`** existem apenas como enum; o handler ainda não
  os processa (depende do `LocationRepository`, que não existe).
- **4 de 5 repositories pendentes** (`User`, `Circle`, `Location`, `Token`).
- **Risco residual R6.1** (chave SSH dentro da árvore do projeto) permanece; mitigação
  por dupla camada de ignore + varredura pré-commit.

**Próximo passo exato (incremento seguinte da Fase 2)**

> Criar os routers REST e os repositories que faltam:
> `app/repositories/{user,circle,location,token}_repository.py`,
> `app/api/routers/{auth,circles,location,users}.py` com
> `POST /auth/register|login|refresh|logout`, `GET|PATCH /users/me`,
> `POST|DELETE /users/me/fcm-token`, `POST /circles`, `POST /circles/join`,
> `GET /circles`, `GET /circles/{id}/members`,
> `DELETE /circles/{id}/members/{user_id}` e `POST /location/batch` (até 50 pontos,
> `ON CONFLICT DO NOTHING` por `client_seq`). Fechar com testes de auth (registro
> duplicado, senha fraca, refresh reutilizado, 403 cross-circle) e gerar
> `docs/openapi.yaml`.

**Arquivos criados/alterados nesta entrada**

```text
backend/pyproject.toml
backend/README.md
backend/.env.example
backend/alembic.ini
backend/alembic/env.py
backend/alembic/script.py.mako
backend/alembic/versions/0001_initial_schema.py
backend/app/__init__.py
backend/app/main.py
backend/app/core/{__init__,config,container,logging,security}.py
backend/app/db/{__init__,base,session}.py
backend/app/models/{__init__,enums,user,circle,location,ptt,token}.py
backend/app/schemas/{__init__,ws}.py
backend/app/services/{__init__,connection_manager,fcm_service,ptt_service}.py
backend/app/repositories/{__init__,ptt_channel_repository}.py
backend/app/api/{__init__,deps}.py
backend/app/api/routers/{__init__,health}.py
backend/app/api/ws/{__init__,ptt}.py
backend/tests/{__init__,conftest,helpers}.py
backend/tests/{test_connection_manager,test_fcm_service,test_security,
                test_ws_auth,test_schema_metadata}.py
docs/TASKS.md                    (alterado — Fase 2 parcialmente marcada)
docs/STATE_TRACEABILITY.md       (alterado — snapshot + esta entrada)
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
