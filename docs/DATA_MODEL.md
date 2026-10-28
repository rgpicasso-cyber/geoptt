# GeoPTT — Modelo de Dados

> **Fonte de verdade das entidades.** Qualquer novo campo, índice ou tabela é
> documentado **aqui primeiro** e só depois implementado (migration + ORM + schema).
>
> Versão: 1.0 · Última atualização: 2026-10-28 · Fase: 1 (Bootstrap)

---

## 1. Diagrama de Entidades

```
                        ┌─────────────────────────┐
                        │         users           │
                        │─────────────────────────│
                        │ id            UUID  PK  │
                        │ email         TEXT  UQ  │
                        │ password_hash TEXT      │
                        │ display_name  TEXT      │
                        │ fcm_token     TEXT  ◀───┼── token FCM do dispositivo
                        │ platform      ENUM      │
                        │ battery_level SMALLINT ◀┼── 0..100, exibido no mapa
                        │ is_sharing_location BOOL│
                        │ last_seen_at  TIMESTAMPTZ│
                        └───────┬─────────┬───────┘
                                │         │
             ┌──────────────────┘         └──────────────────┐
             │ 1:1                                           │ 1:N
             ▼                                               ▼
   ┌───────────────────────┐                    ┌──────────────────────────┐
   │      locations        │                    │    location_history      │
   │  (posição ATUAL)      │                    │  (série temporal)        │
   │───────────────────────│                    │──────────────────────────│
   │ user_id  UUID PK/FK   │                    │ id          BIGSERIAL PK │
   │ lat, lng  DOUBLE      │                    │ user_id     UUID FK      │
   │ geom  GEOGRAPHY(Point)│                    │ lat, lng    DOUBLE       │
   │ accuracy_m REAL       │                    │ geom GEOGRAPHY(Point)    │
   │ speed_mps  REAL       │                    │ accuracy_m, speed_mps    │
   │ heading_deg REAL      │                    │ heading_deg REAL         │
   │ battery_level SMALLINT│                    │ battery_level SMALLINT   │
   │ recorded_at TIMESTAMPTZ                    │ client_seq  BIGINT       │
   └───────────────────────┘                    │ recorded_at TIMESTAMPTZ  │
                                                └──────────────────────────┘

   ┌───────────────────────┐        ┌──────────────────────────┐
   │        circles        │ 1:N    │      circle_members      │ N:1  users
   │───────────────────────│◀──────▶│──────────────────────────│
   │ id        UUID PK     │        │ circle_id UUID PK/FK     │
   │ name      TEXT        │        │ user_id   UUID PK/FK     │
   │ owner_id  UUID FK     │        │ role ENUM(owner/admin/…) │
   │ invite_code TEXT UQ   │        │ joined_at TIMESTAMPTZ    │
   └───────────┬───────────┘        └──────────────────────────┘
               │ 1:N
               ▼
   ┌───────────────────────┐        ┌──────────────────────────┐
   │     ptt_channels      │ 1:N    │   ptt_channel_members    │ N:1 users
   │───────────────────────│◀──────▶│──────────────────────────│
   │ id        UUID PK     │        │ channel_id UUID PK/FK    │
   │ circle_id UUID FK     │        │ user_id    UUID PK/FK    │
   │ name      TEXT        │        │ can_speak  BOOLEAN       │
   │ created_by UUID FK    │        │ joined_at  TIMESTAMPTZ   │
   │ is_active BOOLEAN     │        └──────────────────────────┘
   └───────────┬───────────┘
               │ 1:N
               ▼
   ┌───────────────────────┐
   │     ptt_sessions      │  (auditoria de fala — opcional, Fase 5)
   │───────────────────────│
   │ id UUID PK            │
   │ channel_id, speaker_id│
   │ started_at, ended_at  │
   │ frames_sent, bytes    │
   └───────────────────────┘
```

---

## 2. Entidades Principais

### 2.1 `users`

Representa a pessoa. **Uma linha por conta** (não por dispositivo no MVP).

| Coluna | Tipo | Regras |
|---|---|---|
| `id` | `UUID` PK | `gen_random_uuid()` |
| `email` | `TEXT` | único (case-insensitive), validado por Pydantic `EmailStr` |
| `password_hash` | `TEXT` | **Argon2id** via `pwdlib` (ADR-006); nunca exposto em schema |
| `display_name` | `VARCHAR(60)` | 2–60 chars, sem HTML |
| `avatar_url` | `TEXT` NULL | URL https |
| **`fcm_token`** | `VARCHAR(255)` NULL | token FCM do dispositivo; atualizado em `POST /users/me/fcm-token`; **nunca logado em claro** |
| `platform` | `ENUM('android','ios')` NULL | necessário para escolher payload (APNs vs Android) |
| `battery_level` | `SMALLINT` NULL | `CHECK (0..100)`; enviado junto ao ping de localização |
| `is_sharing_location` | `BOOLEAN` | default `TRUE`; respeita privacidade do usuário |
| `last_seen_at` | `TIMESTAMPTZ` NULL | atualizado no heartbeat do WS |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | `now()`; `updated_at` por trigger/ORM |

**Regras de negócio**

- `battery_level` é dado de presença, **não** histórico: só a última leitura importa.
- Token FCM inválido (retorno `UNREGISTERED`/`INVALID_ARGUMENT`) → setar `fcm_token = NULL`
  e marcar para o cliente re-registrar.
- **Limitação conhecida:** usuário com 2 dispositivos sobrescreve o `fcm_token`.
  Multi-device exige tabela `user_devices` — decisão registrada para ADR na Fase 2.

### 2.2 `circles` (grupo)

Agrupamento social. Todo rastreamento e todo canal PTT pertencem a um círculo.

| Coluna | Tipo | Regras |
|---|---|---|
| `id` | `UUID` PK | |
| `name` | `VARCHAR(80)` | 1–80 chars |
| `owner_id` | `UUID` FK → `users.id` | `ON DELETE RESTRICT` (transferir antes de excluir) |
| `invite_code` | `VARCHAR(12)` | único, gerado no servidor, rotacionável |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

**Regras**

- Exatamente **um** `owner` em `circle_members` (índice parcial único).
- Só `owner`/`admin` rotaciona `invite_code` e remove membros.
- Máx. de membros por círculo no MVP: **50** (limite de fan-out de localização).

### 2.3 `circle_members`

| Coluna | Tipo | Regras |
|---|---|---|
| `circle_id` | `UUID` FK → `circles.id` | `ON DELETE CASCADE` |
| `user_id` | `UUID` FK → `users.id` | `ON DELETE CASCADE` |
| `role` | `ENUM('owner','admin','member')` | default `member` |
| `joined_at` | `TIMESTAMPTZ` | |

PK composta `(circle_id, user_id)`. Índice extra em `user_id` (listar "meus círculos").

### 2.4 `locations` — posição atual (1:1 com `users`)

Tabela "quente", sobrescrita a cada ping. Separada do histórico para manter o mapa
rápido (sem `ORDER BY` sobre milhões de linhas).

| Coluna | Tipo | Regras |
|---|---|---|
| `user_id` | `UUID` PK/FK → `users.id` | `ON DELETE CASCADE` |
| `lat` / `lng` | `DOUBLE PRECISION` | `CHECK (lat BETWEEN -90 AND 90)`, `lng BETWEEN -180 AND 180` |
| `geom` | `GEOGRAPHY(Point,4326)` | espelho de `lat/lng`; usado em queries de proximidade |
| `accuracy_m` | `REAL` | metros |
| `speed_mps` | `REAL` | m/s |
| `heading_deg` | `REAL` | 0–360 |
| `battery_level` | `SMALLINT` | 0–100 |
| `recorded_at` | `TIMESTAMPTZ` | hora do **dispositivo** |
| `updated_at` | `TIMESTAMPTZ` | hora do **servidor** |

> **Decisão:** `lat/lng` são a fonte de verdade (legíveis e portáveis para SQLite);
> `geom` é derivado na escrita para permitir índice GiST. Trade-off aceito: 8 bytes
> duplicados por linha em troca de queries geoespaciais rápidas.

### 2.5 `location_history`

Série temporal imutável. Alimenta trilhas no mapa e o cálculo de distância percorrida.

| Coluna | Tipo | Regras |
|---|---|---|
| `id` | `BIGSERIAL` PK | |
| `user_id` | `UUID` FK → `users.id` | `ON DELETE CASCADE` |
| `lat` / `lng` | `DOUBLE PRECISION` | mesmos checks |
| `geom` | `GEOGRAPHY(Point,4326)` | |
| `accuracy_m` / `speed_mps` / `heading_deg` | `REAL` | |
| `battery_level` | `SMALLINT` | |
| `client_seq` | `BIGINT` | sequência monotônica do cliente (idempotência) |
| `recorded_at` | `TIMESTAMPTZ` | hora do dispositivo |
| `created_at` | `TIMESTAMPTZ` | hora do servidor |

**Regras**

- `UNIQUE (user_id, client_seq)` → reenvio da fila offline **não** duplica ponto.
  Em conflito: `ON CONFLICT DO NOTHING`.
- Rejeitar pontos com `recorded_at` > 5 min no futuro ou > 30 dias no passado.
- **Retenção:** 30 dias (job noturno `DELETE ... WHERE recorded_at < now() - interval '30 days'`).
  Base legal e anonimização: ADR-003 (LGPD).
- **Particionamento** por `RANGE (recorded_at)` mensal quando passar de ~50 M linhas
  (não implementar no MVP).

### 2.6 `ptt_channels`

| Coluna | Tipo | Regras |
|---|---|---|
| `id` | `UUID` PK | |
| `circle_id` | `UUID` FK → `circles.id` | `ON DELETE CASCADE` |
| `name` | `VARCHAR(60)` | único por círculo |
| `created_by` | `UUID` FK → `users.id` | |
| `is_active` | `BOOLEAN` | default `TRUE`; canal inativo recusa `PTT_DOWN` |
| `created_at` | `TIMESTAMPTZ` | |

**Invariantes de runtime (não de schema)**

- **No máximo 1 locutor ativo por canal.** Garantido por `asyncio.Lock` no
  `PTTService` — nunca por estado do cliente.
- Estado de fala é **efêmero**: vive em memória, não em tabela. Se o processo reinicia,
  todos os canais voltam a "livre".
- Timeout de segurança: se um locutor ficar > 60 s sem `PTT_UP`, o servidor libera o
  canal (`PTT_SPEAKER_STOP` forçado).

### 2.7 `ptt_channel_members`

| Coluna | Tipo | Regras |
|---|---|---|
| `channel_id` | `UUID` PK/FK | `ON DELETE CASCADE` |
| `user_id` | `UUID` PK/FK | `ON DELETE CASCADE` |
| `can_speak` | `BOOLEAN` | default `TRUE` (permite canais "só escuta") |
| `joined_at` | `TIMESTAMPTZ` | |

### 2.8 `ptt_sessions` (opcional — Fase 5)

Auditoria leve de cada "aperto de botão". Não armazena áudio.

`id UUID PK` · `channel_id` · `speaker_id` · `started_at` · `ended_at` ·
`frames_sent INT` · `bytes_sent BIGINT`.

Uso: métricas de uso, detecção de abuso, e prova de que áudio **não** é retido.

### 2.9 `refresh_tokens` (suporte a auth — Fase 2)

| Coluna | Tipo | Regras |
|---|---|---|
| `id` | `UUID` PK | |
| `user_id` | `UUID` FK | `ON DELETE CASCADE` |
| `token_hash` | `TEXT` | SHA-256 do token; **nunca** o token em claro |
| `device_id` | `VARCHAR(120)` | identificador opaco do dispositivo |
| `expires_at` | `TIMESTAMPTZ` | 30 dias |
| `revoked_at` | `TIMESTAMPTZ` NULL | logout / rotação |
| `created_at` | `TIMESTAMPTZ` | |

Rotação: cada refresh emite um novo par e revoga o anterior (detecção de reuso →
revogar toda a família do dispositivo).

---

## 3. DDL de Referência — PostgreSQL 16 + PostGIS 3

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

CREATE TYPE user_platform   AS ENUM ('android', 'ios');
CREATE TYPE circle_role     AS ENUM ('owner', 'admin', 'member');

CREATE TABLE users (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email                TEXT NOT NULL,
    password_hash        TEXT NOT NULL,
    display_name         VARCHAR(60) NOT NULL,
    avatar_url           TEXT,
    fcm_token            VARCHAR(255),
    platform             user_platform,
    battery_level        SMALLINT CHECK (battery_level BETWEEN 0 AND 100),
    is_sharing_location  BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at         TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_users_email_lower ON users (lower(email));

CREATE TABLE circles (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR(80) NOT NULL,
    owner_id     UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    invite_code  VARCHAR(12) NOT NULL UNIQUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE circle_members (
    circle_id  UUID NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    role       circle_role NOT NULL DEFAULT 'member',
    joined_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (circle_id, user_id)
);
CREATE INDEX ix_circle_members_user ON circle_members (user_id);
CREATE UNIQUE INDEX ux_circle_single_owner
    ON circle_members (circle_id) WHERE role = 'owner';

CREATE TABLE locations (
    user_id       UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    lat           DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lng           DOUBLE PRECISION NOT NULL CHECK (lng BETWEEN -180 AND 180),
    geom          GEOGRAPHY(Point, 4326) NOT NULL,
    accuracy_m    REAL,
    speed_mps     REAL,
    heading_deg   REAL CHECK (heading_deg >= 0 AND heading_deg <= 360),
    battery_level SMALLINT CHECK (battery_level BETWEEN 0 AND 100),
    recorded_at   TIMESTAMPTZ NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_locations_geom ON locations USING GIST (geom);

CREATE TABLE location_history (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lat           DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lng           DOUBLE PRECISION NOT NULL CHECK (lng BETWEEN -180 AND 180),
    geom          GEOGRAPHY(Point, 4326) NOT NULL,
    accuracy_m    REAL,
    speed_mps     REAL,
    heading_deg   REAL,
    battery_level SMALLINT CHECK (battery_level BETWEEN 0 AND 100),
    client_seq    BIGINT NOT NULL,
    recorded_at   TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_history_user_seq UNIQUE (user_id, client_seq)
);
CREATE INDEX ix_history_user_time ON location_history (user_id, recorded_at DESC);
CREATE INDEX ix_history_geom      ON location_history USING GIST (geom);

CREATE TABLE ptt_channels (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    circle_id   UUID NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    name        VARCHAR(60) NOT NULL,
    created_by  UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (circle_id, name)
);

CREATE TABLE ptt_channel_members (
    channel_id  UUID NOT NULL REFERENCES ptt_channels(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id)         ON DELETE CASCADE,
    can_speak   BOOLEAN NOT NULL DEFAULT TRUE,
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (channel_id, user_id)
);
CREATE INDEX ix_ptt_members_user ON ptt_channel_members (user_id);

CREATE TABLE ptt_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id  UUID NOT NULL REFERENCES ptt_channels(id) ON DELETE CASCADE,
    speaker_id  UUID NOT NULL REFERENCES users(id)        ON DELETE CASCADE,
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ,
    frames_sent INTEGER NOT NULL DEFAULT 0,
    bytes_sent  BIGINT  NOT NULL DEFAULT 0
);
CREATE INDEX ix_ptt_sessions_channel_time ON ptt_sessions (channel_id, started_at DESC);

CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    device_id   VARCHAR(120) NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_refresh_user ON refresh_tokens (user_id) WHERE revoked_at IS NULL;
```

---

## 4. Equivalência SQLite (cliente e ambiente local)

O app mantém **apenas** o necessário para operar offline; o servidor é a verdade.

| Tabela remota | Equivalente local | Observação |
|---|---|---|
| `users` | `cached_users` | somente membros dos círculos do usuário |
| `circles` | `cached_circles` | |
| `locations` | `cached_locations` | última posição conhecida de cada membro (mapa offline) |
| `location_history` | `pending_locations` | **fila de saída**: `client_seq`, `lat`, `lng`, `accuracy`, `speed`, `heading`, `battery`, `recorded_at`, `synced_at` |
| `ptt_*` | `cached_channels` | metadados dos canais |
| — | `pending_events` | eventos PTT/controle enfileirados sem rede |

```sql
-- Fila offline (SQLite) — schema de referência
CREATE TABLE pending_locations (
    client_seq   INTEGER PRIMARY KEY AUTOINCREMENT,
    lat          REAL    NOT NULL,
    lng          REAL    NOT NULL,
    accuracy_m   REAL,
    speed_mps    REAL,
    heading_deg  REAL,
    battery_level INTEGER,
    recorded_at  INTEGER NOT NULL,   -- epoch millis
    synced_at    INTEGER             -- NULL = pendente
);
CREATE INDEX ix_pending_unsynced ON pending_locations (synced_at) WHERE synced_at IS NULL;
```

- `client_seq` local é enviado ao servidor e garante idempotência.
- Limite da fila: **5.000 pontos** (~48 h em movimento contínuo). Ao exceder, descartar
  os mais antigos (política *drop-oldest*) e registrar evento de telemetria.
- No SQLite **não** há PostGIS: distância por **Haversine** em SQL/Dart.
  Isolar em `GeoRepository` para trocar a implementação sem tocar na UI.

---

## 5. Regras Transversais

1. **Timestamps** sempre `TIMESTAMPTZ` (UTC) no servidor; epoch millis no cliente.
2. **IDs** são UUID v4 no servidor; o cliente nunca gera ID de entidade (só `client_seq`).
3. **Exclusão de usuário** → `ON DELETE CASCADE` em localização, histórico, tokens e
   memberships; `circles.owner_id` é `RESTRICT` (exige transferência de posse).
4. **Nunca** armazenar áudio, coordenadas em log, ou token em claro.
5. **Migrations** versionadas (Alembic) e sempre reversíveis; mudança de schema exige
   atualização deste documento no mesmo commit.
6. **Índices** obrigatórios: GiST em toda coluna `geography`; btree em toda FK;
   `(user_id, recorded_at DESC)` no histórico.

---

## 6. Consultas de Referência (PostGIS)

```sql
-- Membros de um círculo com posição, bateria e "há quanto tempo atualizaram"
SELECT u.id, u.display_name, u.battery_level,
       l.lat, l.lng, l.speed_mps, l.heading_deg,
       l.recorded_at,
       EXTRACT(EPOCH FROM (now() - l.recorded_at)) AS age_s
FROM circle_members cm
JOIN users u      ON u.id = cm.user_id
LEFT JOIN locations l ON l.user_id = u.id
WHERE cm.circle_id = :circle_id
  AND u.is_sharing_location = TRUE;

-- Membros a menos de 500 m de um ponto (alerta de proximidade)
SELECT u.id, u.display_name,
       ST_Distance(l.geom, ST_MakePoint(:lng, :lat)::geography) AS distance_m
FROM locations l
JOIN users u ON u.id = l.user_id
WHERE ST_DWithin(l.geom, ST_MakePoint(:lng, :lat)::geography, 500)
ORDER BY distance_m ASC;

-- Distância percorrida nas últimas 24 h
SELECT COALESCE(SUM(
         ST_Distance(geom, lag(geom) OVER (ORDER BY recorded_at))
       ), 0) AS meters
FROM location_history
WHERE user_id = :user_id
  AND recorded_at > now() - interval '24 hours';
```

---

## 7. LGPD / Privacidade (resumo)

- Localização é dado pessoal sensível ao contexto: coletada **somente** com
  `is_sharing_location = TRUE` e consentimento explícito no onboarding.
- Usuário pode: pausar compartilhamento, sair do círculo, solicitar exportação e
  exclusão total (cascade acima).
- Histórico expira em 30 dias por padrão.
- Visibilidade da localização é **por círculo**, nunca global.
