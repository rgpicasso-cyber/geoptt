# GeoPTT — Roadmap de Desenvolvimento

> **Regra de avanço:** uma fase só começa quando a anterior está `[X]`, testada e
> **aprovada explicitamente pelo usuário**. Cada fase termina com docs atualizados e
> entrada em `docs/STATE_TRACEABILITY.md`.
>
> Última atualização: 2026-10-28 · Fase atual: **1 (concluída) → 2 (próxima)**

---

## Painel de Fases

| Fase | Escopo | Status | Bloqueia |
|:---:|---|:---:|---|
| **1** | Setup, `.gitignore`, regras, arquitetura, modelo de dados, rastreabilidade | ✅ `[X]` | tudo |
| **2** | Backend FastAPI: Auth, Database, FCM, WebSocket Hub | ⬜ `[ ]` | 3, 4, 5, 6 |
| **3** | Configuração nativa Android/iOS: permissões e background services | ⬜ `[ ]` | 4, 5 |
| **4** | Frontend Flutter: GIS Tracker + OpenStreetMap | ⬜ `[ ]` | 6 |
| **5** | Frontend Flutter: PTT Audio Engine (Opus) | ⬜ `[ ]` | 6 |
| **6** | Deploy na VPS `163.176.229.20` + testes integrados | ⬜ `[ ]` | release |

---

## Fase 1 — Setup e Arquivos de Rastreabilidade ✅

**Objetivo:** criar o "cérebro" documental do projeto e blindar credenciais antes de
qualquer linha de código de produção.

- [X] Criar `.gitignore` na raiz cobrindo `.env`, `*.pem`, `*.key`, `*.rsa`,
      `serviceAccountKey.json`, `ssh-key-2026-09-24.key`, `google-services.json`,
      `GoogleService-Info.plist`, keystores, bancos locais e artefatos de build.
- [X] Consolidar `.opencode/rules.md` com stack fechada (Flutter, FastAPI,
      PostgreSQL/SQLite, WebSockets, FCM, OpenStreetMap/`flutter_map`, `just_audio`,
      Opus), gate documental e política de credenciais.
- [X] Criar `docs/ARCHITECTURE.md` com diagrama de wake-up
      (App → FCM → Foreground Service → WebSocket → FastAPI) e seção
      "Infraestrutura de Produção" (VPS Ubuntu, `163.176.229.20`, usuário `ubuntu`,
      acesso por chave SSH, alerta em negrito contra commit de chaves).
- [X] Criar `docs/DATA_MODEL.md` com `users` (`fcm_token`, `battery_level`),
      `circles`, `circle_members`, `locations`, `location_history`, `ptt_channels`,
      `ptt_channel_members`, `ptt_sessions`, `refresh_tokens`.
- [X] Criar `docs/TASKS.md` (este arquivo) com as 6 fases.
- [X] Criar `docs/STATE_TRACEABILITY.md` com o registro inicial.
- [X] Inicializar repositório Git (`main`), `.gitattributes` e commit de bootstrap
      `912c390`; chave SSH confirmada fora do index e do histórico.

**Critério de saída:** os 4 documentos existem, são coerentes entre si e nenhum
segredo está na árvore do repositório. → **ATENDIDO**

---

## Fase 2 — Backend FastAPI (Auth, Database, FCM, WebSocket Router)

**Objetivo:** servidor funcional que autentica, persiste, mantém presença e dispara
wake-up. Ainda **sem** áudio (áudio é Fase 5), mas com o hub e o contrato prontos.

### 2.1 Scaffold e configuração

- [ ] Criar `backend/` com `pyproject.toml` (Python 3.12), `ruff`, `mypy --strict`,
      `pytest`, `pytest-asyncio`, `httpx`.
- [ ] `app/core/config.py` com `pydantic-settings` lendo `.env`
      (`DATABASE_URL`, `JWT_SECRET`, `JWT_ALG`, `ACCESS_TTL`, `REFRESH_TTL`,
      `FIREBASE_CREDENTIALS_PATH`, `CORS_ORIGINS`, `ENV`).
- [ ] `.env.example` **sem valores reais**; confirmar que `.env` está ignorado.
- [ ] `app/main.py` com factory, `lifespan` (pool DB, Firebase Admin), routers e
      `/health` (liveness) + `/health/ready` (DB + FCM).
- [ ] Logging estruturado com redação de `token`, `password`, `lat`, `lng`,
      `fcm_token`.

### 2.2 Banco de dados

- [ ] Configurar SQLAlchemy 2.x async (`asyncpg`) + Alembic.
- [ ] Migrations da Fase 1 do `DATA_MODEL.md` (users, circles, circle_members,
      locations, location_history, ptt_channels, ptt_channel_members, refresh_tokens).
- [ ] Habilitar PostGIS na migration inicial; fallback SQLite documentado para dev.
- [ ] Repositories: `UserRepository`, `CircleRepository`, `LocationRepository`,
      `PttChannelRepository`, `TokenRepository`.
- [ ] Teste: migrations sobem e descem (`alembic upgrade head` / `downgrade -1`).

### 2.3 Autenticação

- [ ] `POST /auth/register` (email, password, display_name) — bcrypt.
- [ ] `POST /auth/login` (OAuth2 password flow) → access + refresh.
- [ ] `POST /auth/refresh` com rotação e revogação por `device_id`.
- [ ] `POST /auth/logout` (revoga refresh do dispositivo).
- [ ] Dependency `get_current_user` (JWT `sub` → `users.id`).
- [ ] Rate limit em login/registro (5/min/IP).
- [ ] Testes: registro duplicado, senha fraca, token expirado, refresh reutilizado.

### 2.4 Usuários e FCM

- [ ] `GET /users/me` e `PATCH /users/me` (`display_name`, `is_sharing_location`).
- [ ] `POST /users/me/fcm-token` (token + platform) — idempotente.
- [ ] `DELETE /users/me/fcm-token` (logout do dispositivo).
- [ ] `FirebaseService.send_data_message(user_id, data, priority="high", ttl=0)`
      com tratamento de `UNREGISTERED` (limpa token) e retry/backoff.
- [ ] Teste com mock do `firebase_admin.messaging`.

### 2.5 Círculos

- [ ] `POST /circles` (cria círculo + membership `owner` + canal PTT padrão).
- [ ] `POST /circles/join` (por `invite_code`).
- [ ] `GET /circles` e `GET /circles/{id}/members` (com última posição e bateria).
- [ ] `DELETE /circles/{id}/members/{user_id}` (owner/admin).
- [ ] Autorização: nenhum acesso a círculo do qual não se é membro (teste 403).

### 2.6 Localização

- [ ] `POST /location/batch` (até 50 pontos, `ON CONFLICT DO NOTHING` por
      `client_seq`), atualiza `locations` e insere em `location_history`.
- [ ] `GET /location/circle/{id}` (snapshot para o mapa).
- [ ] Validação de faixa de lat/lng, `recorded_at` (futuro > 5 min rejeitado).
- [ ] Testes: idempotência de reenvio, rejeição de coordenada inválida, isolamento
      entre círculos.

### 2.7 WebSocket Hub

- [ ] `ConnectionManager` (`dict[user_id, set[WebSocket]]`) com `connect`,
      `disconnect`, `is_online`, `send_json`, `send_bytes`.
- [ ] `GET /ws` — auth por `?token=` **ou** frame `AUTH` em ≤ 3 s (senão `4401`).
- [ ] Heartbeat: `PING`/`PONG` com timeout de 60 s; limpeza de conexões mortas.
- [ ] `LOCATION_BATCH` via WS reaproveitando o mesmo service do REST.
- [ ] Broadcast de `LOCATION_UPDATE` para membros do círculo.
- [ ] `PTTService`: `PTT_DOWN`/`PTT_UP`, `asyncio.Lock` por canal, `PTT_BUSY`,
      timeout de 60 s, `PTT_SPEAKER_START/STOP`.
- [ ] **Fallback FCM:** destinatário offline → `send_data_message(type="PTT_WAKEUP")`.
- [ ] Teste de contrato do WS com `httpx`/`websockets`: auth inválida, busy,
      fallback disparado, reconexão.

### 2.8 Contrato

- [ ] Gerar e versionar `docs/openapi.yaml`.
- [ ] Documentar o envelope WS (`v`, `type`, `data`) em `docs/ARCHITECTURE.md` §7.

**Critério de saída:** `pytest` verde (≥ 80% nos services), `mypy --strict` sem erro,
`openapi.yaml` gerado, e um cliente de teste (`wscat`/script) completando o ciclo
login → WS → `PTT_DOWN` → fallback FCM simulado.

---

## Fase 3 — Configuração Nativa Android/iOS

**Objetivo:** garantir que o SO **não mate** o app e que o wake-up funcione.

### 3.1 Android

- [ ] `AndroidManifest.xml`: `INTERNET`, `ACCESS_FINE_LOCATION`,
      `ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE`,
      `FOREGROUND_SERVICE_LOCATION`, `FOREGROUND_SERVICE_MICROPHONE`,
      `FOREGROUND_SERVICE_MEDIA_PLAYBACK`, `WAKE_LOCK`, `RECEIVE_BOOT_COMPLETED`,
      `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`, `POST_NOTIFICATIONS`.
- [ ] `BackgroundRelayService` (Kotlin) com `foregroundServiceType` explícito,
      notificação persistente e `START_STICKY`.
- [ ] `BootReceiver` para religar o serviço após reboot.
- [ ] Canal de notificação dedicado (`geoptt_relay`, importância `LOW`).
- [ ] Handler `_firebaseMessagingBackgroundHandler` com
      `@pragma('vm:entry-point')` **fora de classe**.
- [ ] Fluxo gracioso de isenção de bateria (tela explicativa + intent).
- [ ] `MethodChannel` `geoptt/background`: `startRelay`, `stopRelay`, `isRelayRunning`.

### 3.2 iOS

- [ ] `Info.plist`: `UIBackgroundModes` = `audio`, `location`, `voip`,
      `remote-notification`, `fetch`.
- [ ] `NSMicrophoneUsageDescription`, `NSLocationWhenInUseUsageDescription`,
      `NSLocationAlwaysAndWhenInUseUsageDescription` com texto claro.
- [ ] PushKit `PKPushRegistry` + CallKit reporting (avaliar risco de review — ADR-002).
- [ ] `AppDelegate` encaminhando tokens (FCM + VoIP) ao Dart.
- [ ] Habilitar *Background Modes* e *Push Notifications* no Xcode/capabilities.

### 3.3 Validação

- [ ] Teste manual: swipe-away → PTT do outro usuário → app desperta e recebe áudio.
- [ ] Teste manual: reboot do aparelho → serviço religa.
- [ ] Matriz de fabricantes (Xiaomi, Samsung, Motorola) documentada.

**Critério de saída:** checklist de permissões completo + evidência (log/screen) de
wake-up após swipe-away em pelo menos 1 Android e 1 iOS.

---

## Fase 4 — Frontend Flutter: GIS Tracker + OpenStreetMap

**Objetivo:** mapa funcional com posições do círculo em tempo real.

- [ ] Scaffold `app/` + `analysis_options.yaml` com `strict-casts`,
      `strict-inference`, `strict-raw-types`.
- [ ] `core/` : Dio client, `WsClient` (backoff exponencial + jitter, heartbeat),
      `SecureStorage` (tokens), router, tema.
- [ ] Feature `auth`: login, refresh automático, logout.
- [ ] Feature `map`: `flutter_map` + tiles OSM (com `userAgentPackageName` e cache),
      markers com avatar, bateria e "há X min".
- [ ] Feature `location`: `geolocator` + smart ping (10 s / 25 m em movimento,
      120 s parado), precisão adaptativa.
- [ ] Fila offline em SQLite (Drift/sqflite) + drenagem em lote no reconnect.
- [ ] Permissões de localização em runtime com UI explicativa.
- [ ] Providers Riverpod: `locationStreamProvider`, `circleMembersProvider`,
      `wsConnectionProvider`.
- [ ] Testes: widget test do mapa com dados fake; unit test do smart ping e do
      backoff.

**Critério de saída:** dois emuladores/dispositivos veem a posição um do outro no mapa
em < 5 s, com consumo de bateria medido em 30 min de teste.

---

## Fase 5 — Frontend Flutter: PTT Audio Engine

**Objetivo:** falar de verdade, com latência aceitável e áudio em segundo plano.

- [ ] `audio_session` configurada (`PlayAndRecord` / `USAGE_VOICE_COMMUNICATION`).
- [ ] Captura Opus (`flutter_opus`/`opus_flutter` ou encoder nativo via
      `MethodChannel`), frames de 20 ms agregados em chunks de ~200 ms.
- [ ] Envio binário pelo WebSocket; controle via JSON (`PTT_DOWN`/`PTT_UP`).
- [ ] Recepção: jitter buffer + `just_audio` com `StreamAudioSource` (ou
      `AudioPlayer` custom source) para reprodução contínua.
- [ ] UI PTT: botão push-to-talk com estados (idle, pedindo canal, falando, ocupado,
      sem rede), feedback tátil e indicador de quem fala.
- [ ] Tratamento de `PTT_BUSY`, perda de conexão no meio da fala e reconexão.
- [ ] Integração com `BackgroundRelayService` para áudio com app fechado.
- [ ] Testes: unit test do chunker, widget test dos estados do botão, teste manual de
      latência ponta a ponta (alvo ≤ 400 ms).

**Critério de saída:** conversa PTT funcional entre 2 dispositivos, inclusive com o
app em segundo plano, sem eco e sem travar o canal.

---

## Fase 6 — Deploy na VPS + Testes Integrados

**Objetivo:** produção real em `163.176.229.20`.

- [ ] Provisionar Ubuntu: usuário `ubuntu`, chave SSH, `ufw` (22/80/443),
      `fail2ban`, `unattended-upgrades`.
- [ ] Instalar PostgreSQL 16 + PostGIS; criar DB e usuário de aplicação restrito.
- [ ] `systemd` unit `geoptt-api.service` (Uvicorn, `--workers`, `EnvironmentFile`).
- [ ] Nginx + TLS (certbot) + bloco `/ws` com `Upgrade`/`Connection`.
- [ ] Firebase Admin SDK na VPS com `serviceAccountKey.json` em `/opt/geoptt/secrets`
      (modo `600`, **fora do repo**).
- [ ] `.env` de produção com `JWT_SECRET` forte e rotacionável.
- [ ] Backup diário do Postgres + teste de restore.
- [ ] Smoke test: `https://.../health`, login, WS `wss://`, PTT entre 2 dispositivos
      reais em 4G.
- [ ] Teste de carga leve (50 usuários, 10 canais) e tuning de `worker`/pool.
- [ ] Documentar runbook em `docs/ARCHITECTURE.md` §9 / `STATE_TRACEABILITY.md`.

**Critério de saída:** app publicado apontando para `wss://` de produção, com
monitoramento básico e rollback documentado.

---

## Backlog pós-MVP (não iniciar sem aprovação)

- [ ] Multi-dispositivo por usuário (`user_devices`).
- [ ] Escala horizontal do hub (pub/sub) — ADR-001.
- [ ] Geofencing (alertas de entrada/saída de área).
- [ ] Gravação opcional de áudio — ADR-004.
- [ ] Histórico de trilha no mapa com player temporal.
- [ ] Painel web administrativo.
