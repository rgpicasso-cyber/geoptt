# GeoPTT — Backend (FastAPI)

API de **rastreamento em tempo real** e **Push-To-Talk** do GeoPTT.

- **REST** — autenticação, círculos, localização em lote, canais PTT.
- **WebSocket `/ws`** — presença, áudio Opus (frames binários) e controle (JSON).
- **FCM** — quando o destinatário não tem socket ativo, o servidor dispara uma
  *Data Message* de alta prioridade para acordar o app.

> Documentação de arquitetura, modelo de dados e protocolo: `docs/ARCHITECTURE.md`,
> `docs/DATA_MODEL.md` e `docs/STATE_TRACEABILITY.md` na raiz do repositório.

---

## Requisitos

| Item | Versão | Observação |
|---|---|---|
| Python | **3.12+** | `requires-python = ">=3.12"` |
| PostgreSQL | **13+** | Obrigatório: as tabelas geoespaciais exigem **PostGIS** |
| PostGIS | **3.x** | `CREATE EXTENSION postgis` é executado pela migration |
| Firebase | service account JSON | Opcional em local (`FCM_ENABLED=false`) |

> **SQLite não é suportado para o schema completo.** As tabelas `locations` e
> `location_history` usam `GEOGRAPHY(POINT, 4326)`. A migration aborta
> explicitamente se o dialeto não for `postgresql`.

---

## Setup local

### 1. Ambiente virtual

```bash
cd backend
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Linux/macOS
source .venv/bin/activate
```

### 2. Dependências

```bash
pip install -e ".[dev]"
```

### 3. Variáveis de ambiente

```bash
cp .env.example .env
```

Edite `.env`:

- `DATABASE_URL` — driver assíncrono **obrigatório** (`postgresql+asyncpg://`).
  Os formatos `postgres://` e `postgresql://` são normalizados automaticamente.
- `JWT_SECRET` — mínimo 32 caracteres. Gere com:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- `FCM_ENABLED=false` em desenvolvimento (não exige credenciais).

> `ENV=production` ativa validadores que **recusam** subir com o `JWT_SECRET`
> padrão de desenvolvimento, `DEBUG=true` ou `FCM_ENABLED=true` sem
> `FCM_CREDENTIALS_PATH`.

### 4. Banco de dados

```bash
# Criar o banco (o usuário precisa de permissão para CREATE EXTENSION postgis)
createdb -U postgres geoptt

# Aplicar o schema
alembic upgrade head

# Conferir
alembic current
```

**PostGIS:** `CREATE EXTENSION postgis` exige superusuário (ou um usuário com
`SUPERUSER`/`CREATEDB`). Em produção, rode a extensão uma única vez como
superusuário e depois execute as migrations com o usuário da aplicação:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- necessário para gen_random_uuid() no PG < 13
```

### 5. Subir a API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

| Endpoint | Descrição |
|---|---|
| `GET /health` | Liveness — não toca no banco |
| `GET /health/ready` | Readiness — banco + FCM + estatísticas de WebSocket |
| `GET /docs` | Swagger UI (desabilitado em `ENV=production`) |
| `WS /ws` | Socket principal do app |

---

## WebSocket — contrato resumido

Autenticação por **query string** ou **primeiro frame**:

```
ws://localhost:8000/ws?token=<JWT>&device_id=<uuid>
```

```json
{ "v": 1, "type": "AUTH", "data": { "token": "<JWT>" } }
```

- Falha de autenticação → close `4401` (após `accept`, para o cliente ler o código).
- Sem `AUTH` em `WS_AUTH_TIMEOUT_SECONDS` (3 s) → close `4402`.
- Sem tráfego em `WS_HEARTBEAT_TIMEOUT_SECONDS` (60 s) → close `4408`.
- Frames **binários** são exclusivamente áudio Opus do locutor atual.
- Frames **textuais** seguem o envelope `{v, type, id?, ts, data}`.

Sequência de fala:

```
cliente A: {"type":"PTT_DOWN","data":{"channel_id":"..."}}
servidor : {"type":"PTT_SPEAKER_START","data":{...}}   (broadcast)
cliente A: <frames binários Opus>
servidor : {"type":"PTT_SPEAKER_STOP","data":{...,"reason":"user_released"}}
```

Se outro membro já estiver falando, o servidor responde `PTT_BUSY` com o
`speaker_id` atual. O canal é liberado automaticamente após
`PTT_SPEAKER_TIMEOUT_SECONDS` se o cliente esquecer o `PTT_UP`.

---

## Qualidade de código

```bash
ruff check .            # lint
ruff format --check .   # formatação
mypy app                # tipagem estrita
pytest                  # testes (não exigem banco)
```

Configuração em `pyproject.toml`:

- **Ruff** — `line-length = 100`, regras `E/W/F/I/N/UP/B/C4/ASYNC/S/RET/SIM/TID/PL/RUF`.
- **Mypy** — `strict = true`, plugin do Pydantic.
- **Pytest** — `asyncio_mode = "auto"`.

---

## Estrutura

```
backend/
├── alembic/
│   ├── env.py                      # URL vem de DATABASE_URL, nunca do .ini
│   └── versions/0001_initial_schema.py
├── app/
│   ├── api/
│   │   ├── deps.py                 # dependências HTTP
│   │   ├── routers/health.py       # probes
│   │   └── ws/ptt.py               # endpoint /ws
│   ├── core/
│   │   ├── config.py               # Settings (pydantic-settings)
│   │   ├── container.py            # Services (app.state)
│   │   ├── logging.py              # JSON + redação de segredos
│   │   └── security.py             # bcrypt + JWT
│   ├── db/
│   │   ├── base.py                 # Base + naming convention
│   │   └── session.py              # Database (engine async)
│   ├── models/                     # ORM (users, circles, locations, ptt...)
│   ├── repositories/               # acesso a dados
│   ├── schemas/ws.py               # envelope do protocolo
│   ├── services/
│   │   ├── connection_manager.py   # presença + writer com backpressure
│   │   ├── fcm_service.py          # wake-up Data Message
│   │   └── ptt_service.py          # half-duplex por canal
│   └── main.py                     # application factory + lifespan
└── tests/
```

---

## Segurança — regras não negociáveis

- `.env`, `serviceAccountKey.json` e `*.key` **nunca** são versionados.
- Senhas: bcrypt. Refresh tokens: armazenados apenas como SHA-256.
- Logs passam por `RedactionFilter` (JWT, `token=`, senhas e coordenadas
  com 5+ casas decimais são mascarados).
- `JWT_SECRET` em `SecretStr` — não aparece em `repr()` nem em tracebacks.

---

## Problemas conhecidos

| Problema | Impacto | Mitigação |
|---|---|---|
| `passlib` 1.7.4 sem manutenção | Aviso de versão do `bcrypt` no startup | Migração para `pwdlib` avaliada em ADR futura |
| Estado de canal PTT em memória | Não escala horizontalmente | MVP single-node; Redis/ADR-001 antes de escalar |
| `FCM` no iOS pode atrasar background push | Wake-up não garantido | PushKit/VoIP avaliado em ADR-002 (Fase 3) |
| Sem Docker/psql no ambiente de dev atual | Migration não executada localmente | Validar no VPS (`163.176.229.20`) ou ambiente do usuário |
