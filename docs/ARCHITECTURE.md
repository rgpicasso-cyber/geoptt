# GeoPTT — Arquitetura do Sistema

> **Documento de verdade arquitetural.** Alterações de fluxo, contrato ou infraestrutura
> exigem atualização deste arquivo **antes** do código (ver `.opencode/rules.md` §8).
>
> Versão: 1.0 · Última atualização: 2026-10-28 · Fase: 1 (Bootstrap)

---

## 1. Visão Geral

GeoPTT é um aplicativo híbrido que combina duas capacidades de tempo real sobre a
**mesma sessão autenticada e o mesmo canal de transporte**:

| Capacidade | Referência de mercado | Requisito central |
|---|---|---|
| Rastreamento de localização contínuo | Life360 | posição + bateria + velocidade visíveis no círculo |
| Push-To-Talk em grupo/P2P | Zello | latência de fala ≤ ~400 ms, half-duplex por canal |
| Resiliência de segundo plano | — | **o app não pode morrer no swipe-away** |

O sistema é composto por três camadas de execução:

1. **Cliente Flutter** (Android/iOS) — UI, captura de GPS, captura/reprodução de áudio,
   fila offline local (SQLite) e serviços de segundo plano nativos.
2. **Backend FastAPI** (Python 3.12, async) — autenticação, presença, hub WebSocket,
   fan-out de áudio, ingestão geoespacial e disparo de wake-up via FCM.
3. **Persistência PostgreSQL + PostGIS** — usuários, círculos, canais PTT e histórico
   de localização com índices geoespaciais.

---

## 2. Princípios Arquiteturais (não negociáveis)

1. **Servidor é a autoridade de presença.** O cliente nunca decide se "está online".
   O `ConnectionManager` do FastAPI é a única fonte de verdade sobre sockets ativos.
2. **Estado sobrevive ao processo do cliente.** Matar o app não apaga o usuário, o
   círculo, o canal nem o histórico — apenas a conexão. Tudo é reconstruível no
   reconnect.
3. **Wake-up é barato, áudio é caro.** O FCM Data Message carrega **apenas** o
   ponteiro (`type`, `channel_id`, `sender_id`, `call_id`). Nunca transporta áudio.
4. **Nenhum I/O bloqueante no event loop.** Rotas, handlers de WebSocket e acesso a
   banco são `async`. Chamadas ao Firebase Admin SDK rodam em `run_in_threadpool`
   quando a SDK for síncrona.
5. **Half-duplex por canal PTT.** Um canal tem no máximo **um locutor ativo** por vez,
   garantido por *lock* no servidor (não por confiança no cliente).
6. **Offline-first no cliente.** Toda posição/evento é gravada localmente antes de ser
   enviada; a fila é drenada em ordem no reconnect.
7. **Stack fechada.** Introduzir Redis, RabbitMQ, Kafka, Google Maps ou qualquer novo
   runtime exige **ADR aprovado**. O MVP escala verticalmente em um único nó.

---

## 3. Componentes

### 3.1 Cliente Flutter

```
app/
└── lib/
    ├── core/                 # DI, http client, ws client, erros, tema, config
    ├── features/
    │   ├── auth/             # login, refresh token, sessão
    │   ├── location/         # GPS, smart ping, fila offline, sync
    │   ├── map/              # flutter_map + tiles OSM + markers do círculo
    │   ├── ptt/              # captura Opus, chunks, reprodução, canais
    │   ├── circle/           # círculos, membros, convites
    │   └── background/       # bridge nativo, FCM handler, foreground service
    └── main.dart
```

- **Estado:** Riverpod (único gerenciador aprovado).
- **Camadas por feature:** `presentation → domain → data`. Sem import cruzado direto
  entre features; comunicação via `core` ou providers compartilhados.
- **Ponte nativa:** `MethodChannel`/`EventChannel` tipados (`geoptt/background`,
  `geoptt/audio`). Nada de lógica de negócio no Kotlin/Swift — só ciclo de vida.

### 3.2 Backend FastAPI

```
backend/
└── app/
    ├── main.py               # app factory, lifespan, CORS, routers
    ├── core/                 # settings (pydantic-settings), security, logging
    ├── api/
    │   ├── routers/          # auth, users, circles, location, ptt, health
    │   └── ws/               # /ws (hub), /ws/ptt (áudio)
    ├── services/             # regras de negócio (presence, fanout, geo, wakeup)
    ├── repositories/         # SQLAlchemy async, queries PostGIS
    ├── models/               # ORM
    ├── schemas/              # Pydantic v2 (request/response)
    └── integrations/         # firebase_admin (FCM), storage
```

Fluxo de dependência: `routers → services → repositories → models`.
Router **não** contém regra de negócio. Service **não** monta SQL cru.

### 3.3 Infraestrutura de execução

```
Flutter (wss/https) ──TLS──▶ Nginx (443) ──▶ Uvicorn (127.0.0.1:8000) ──▶ PostgreSQL/PostGIS (5432)
                                   │
                                   └──▶ Firebase Admin SDK ──▶ FCM ──▶ dispositivo
```

---

## 4. Fluxo Crítico — Wake-Up após Swipe-Away

Este é o fluxo que define o produto. Ele precisa funcionar com o app **removido da
lista de recentes**.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. APP EM FOREGROUND                                                     │
│    Flutter mantém WebSocket wss:// + heartbeat ping/pong (25 s)          │
│    + FCM token registrado em POST /users/me/fcm-token                    │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ usuário faz swipe-away
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 2. PROCESSO MORTO PELO OS                                                │
│    Android: socket fecha, isolate morre, Foreground Service é encerrado  │
│    iOS: app suspenso/terminado; socket fecha                             │
│    → ConnectionManager.remove(user_id) → presença = OFFLINE              │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ outro membro aperta PTT no canal
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 3. FASTAPI DETECTA AUSÊNCIA DE SOCKET                                    │
│    route_ptt_payload(sender, channel, chunk):                            │
│      socket = manager.get_connection(target)                             │
│      if socket is None:  → wakeup_service.send_data_message(...)         │
└───────────────────────────────┬──────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 4. FCM DATA MESSAGE (silencioso)                                         │
│    { "type": "PTT_WAKEUP", "channel_id": "...", "sender_id": "...",      │
│      "call_id": "...", "ts": 1730000000 }                                │
│    android.priority = high · ttl = 0 · data-only (SEM notification)      │
└───────────────────────────────┬──────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 5. DESPERTAR NATIVO                                                      │
│    ANDROID                                                                 │
│      _firebaseMessagingBackgroundHandler (@pragma vm:entry-point)         │
│        → startForegroundService(BackgroundRelayService)                   │
│        → service declara foregroundServiceType=                            │
│          "microphone|mediaPlayback|location" + notificação persistente     │
│    iOS                                                                     │
│      PushKit VoIP push (ou content-available:1) → BGTask                    │
│      + background modes: audio, voip, location, remote-notification        │
└───────────────────────────────┬──────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 6. RECONEXÃO DO WEBSOCKET                                                │
│    wss://geoptt/ws?token=<JWT>  (ou 1º frame {"type":"AUTH"})             │
│    → backoff exponencial + jitter (1s,2s,4s… máx 30s)                     │
│    → drena fila offline (SQLite) de posições/eventos                      │
│    → reentra no canal PTT e retoma áudio                                  │
└───────────────────────────────┬──────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 7. ESTADO RECONCILIADO                                                   │
│    FastAPI devolve snapshot: membros do círculo, posições recentes,       │
│    canais, quem está falando. Cliente re-renderiza o mapa.                │
└──────────────────────────────────────────────────────────────────────────┘
```

**Limites conhecidos deste fluxo (aceitos e documentados):**

- A entrega do FCM **não é garantida** — é *best effort*. Por isso o cliente também
  faz reconnect proativo ao voltar ao foreground e ao receber qualquer push.
- O FCM tem limite prático de **4 KB** por payload. Áudio nunca trafega por push.
- Android pode atrasar Data Messages em Doze Mode se o app não estiver isento de
  otimização de bateria → a UI pede `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` de forma
  graciosa antes de ativar o modo PTT.
- iOS é mais restritivo: PushKit VoIP exige justificativa de revisão (uso real de
  chamada). Estratégia aceita: **áudio em background + VoIP push**, com fallback para
  notificação visível quando o sistema bloquear o despertar silencioso. Risco de
  rejeição na App Store está registrado em §10.

---

## 5. Fluxo de Áudio PTT (half-duplex)

```
[Cliente A]                         [FastAPI]                       [Cliente B]
    │                                   │                                │
    │ PTT_DOWN (channel_id)             │                                │
    ├──────────────────────────────────▶│ lock(channel)  ─── ok ───▶     │
    │                                   │ PTT_SPEAKER_START (A)           │
    │                                   ├───────────────────────────────▶│
    │ frames Opus (binário, ~200 ms)    │                                │
    ├──────────────────────────────────▶│ fan-out binário (sem decode)    │
    │                                   ├───────────────────────────────▶│
    │                                   │  buffer + just_audio (B)        │
    │ PTT_UP                            │                                │
    ├──────────────────────────────────▶│ unlock(channel)                 │
    │                                   │ PTT_SPEAKER_STOP                │
    │                                   ├───────────────────────────────▶│
```

Regras de implementação:

- **Codec:** Opus, mono, 16 kHz (voz), bitrate 16–24 kbps, frame de 20 ms agregado
  em chunks de ~200 ms antes do envio.
- **Transporte:** frames **binários** no WebSocket; controle em JSON. Nunca
  base64 de áudio (custo de 33% + CPU).
- **Sessão de áudio:** `audio_session` configurada como `PlayAndRecord` (iOS) /
  `USAGE_VOICE_COMMUNICATION` (Android) para ducking e roteamento correto.
- **Backpressure:** se o socket do destinatário estiver lento, o servidor **descarta
  frames antigos** (áudio é perecível) em vez de acumular memória.
- **Locutor único:** `asyncio.Lock` por canal; segundo `PTT_DOWN` recebe
  `PTT_BUSY` com o `speaker_id` atual.

---

## 6. Fluxo de Localização (Smart Ping)

Objetivo: mapa atualizado sem drenar bateria.

| Situação | Gatilho de envio |
|---|---|
| Em movimento (> 1,5 m/s) | a cada **10 s** ou **25 m** de deslocamento |
| Parado | heartbeat a cada **120 s** |
| Mudança de círculo/canal | envio imediato |
| Sem rede | enfileira no SQLite; drena em lote no reconnect |

- Payload mínimo: `lat`, `lng`, `accuracy`, `speed`, `heading`, `battery_level`,
  `recorded_at`, `client_seq` (idempotência).
- Precisão adaptativa: `high` quando em movimento, `balanced/low` quando parado.
- **Batch:** até 50 pontos por requisição REST (`POST /location/batch`) ou por frame
  WS `LOCATION_BATCH` — reduz overhead de TLS em 10–30×.
- Deduplicação no servidor por `(user_id, client_seq)`.
- Retenção do histórico: **30 dias** (configurável), com job de expurgo.

---

## 7. Contrato de Tempo Real (envelope)

Todo frame **textual** usa o mesmo envelope; frames **binários** são exclusivamente
áudio Opus.

```jsonc
{ "v": 1, "type": "LOCATION_BATCH", "id": "uuid-opcional", "ts": 1730000000, "data": { } }
```

| `type` | Direção | `data` |
|---|---|---|
| `AUTH` | C→S | `{ "token": "..." }` (obrigatório se não veio por query) |
| `AUTH_OK` | S→C | `{ "user_id": "...", "server_ts": 0 }` |
| `PING` / `PONG` | ambos | `{}` |
| `LOCATION_BATCH` | C→S | `{ "points": [...] }` |
| `LOCATION_UPDATE` | S→C | `{ "user_id", "lat", "lng", "speed", "heading", "battery_level", "ts" }` |
| `PTT_DOWN` / `PTT_UP` | C→S | `{ "channel_id": "..." }` |
| `PTT_BUSY` | S→C | `{ "channel_id", "speaker_id" }` |
| `PTT_SPEAKER_START` / `STOP` | S→C | `{ "channel_id", "user_id" }` |
| `PTT_WAKEUP` | FCM | `{ "channel_id", "sender_id", "call_id" }` |
| `ERROR` | S→C | `{ "code": "...", "message": "..." }` |

Versionamento: campo `v` no envelope. Mudança incompatível → `v: 2` + período de
coexistência. Contrato HTTP versionado em `docs/openapi.yaml` (Fase 2).

---

## 8. Segurança

- **Auth:** OAuth2 password flow → `access_token` (15 min) + `refresh_token` (30 d,
  rotativo, revogável por dispositivo). Hash de senha com bcrypt (`passlib`).
- **WebSocket:** token via query (`?token=`) **ou** primeiro frame `AUTH` com
  timeout de 3 s. Sem `AUTH_OK`, o servidor fecha com código `4401`.
- **Autorização:** toda operação PTT/localização valida associação ao círculo/canal.
  Nunca confiar em `user_id` vindo do payload — usar o `sub` do JWT.
- **Transporte:** `wss://` e `https://` obrigatórios em produção (OS móvel bloqueia
  cleartext). HSTS no Nginx.
- **Logs:** proibido logar coordenadas exatas, tokens, `fcm_token` completo ou
  conteúdo de áudio. Redigir/truncar (`fcm_token[:8] + "…"`).
- **Rate limit:** login/registro (5/min/IP), refresh (10/min), FCM wake-up
  (10/min/usuário) para evitar *push bombing*.

---

## 9. Infraestrutura de Produção

> ## 🚨 **ALERTA DE SEGURANÇA — LEIA ANTES DE QUALQUER DEPLOY**
>
> **É TERMINANTEMENTE PROIBIDO colocar chaves SSH privadas, `.env` de produção,
> `serviceAccountKey.json` ou qualquer credencial real neste repositório — incluindo
> commits, branches, issues, PRs, prints de tela e prompts de IA.**
> A chave privada da VPS (`ssh-key-2026-09-24.key`) **NÃO** pertence ao projeto: ela
> deve viver fora da árvore do repositório, com permissão `600`.
> Se uma chave for exposta, considere-a **comprometida**: revogue, gere outra e
> registre o incidente em `docs/STATE_TRACEABILITY.md`. O `.gitignore` é apenas uma
> rede de segurança, **não** substitui disciplina.

### 9.1 Servidor

| Item | Valor |
|---|---|
| Provedor | VPS (Ubuntu Server LTS) |
| IP público | **163.176.229.20** |
| Usuário de deploy | **`ubuntu`** (sudo, sem login direto de `root`) |
| Método de acesso | **SSH por chave** — `ssh -i <caminho-fora-do-repo>/ssh-key-2026-09-24.key ubuntu@163.176.229.20` |
| Portas expostas | `22` (SSH), `80` (redirect), `443` (TLS) — **somente** |
| Portas internas | `8000` Uvicorn, `5432` PostgreSQL — apenas `127.0.0.1` / rede privada |
| Diretório da aplicação | `/opt/geoptt/` |
| Serviço | `systemd` unit `geoptt-api.service` |
| Proxy reverso | Nginx com TLS (Let's Encrypt / certbot) |

### 9.2 Hardening mínimo (Fase 6)

- `ufw` com *default deny incoming*, liberando apenas 22/80/443.
- `PermitRootLogin no`, `PasswordAuthentication no` no `sshd_config`.
- `fail2ban` para SSH.
- Usuário de aplicação sem privilégios; `systemd` com `NoNewPrivileges=true`,
  `PrivateTmp=true`, `ProtectSystem=strict`.
- Segredos via `EnvironmentFile=/opt/geoptt/.env` (modo `600`, dono `ubuntu`).
- Backup diário do PostgreSQL + teste de restore mensal.
- Renovação automática de certificado (`certbot.timer`).

### 9.3 Nginx — pontos obrigatórios para WebSocket

```nginx
location /ws {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 3600s;   # socket de longa duração
    proxy_send_timeout 3600s;
}
```

Sem `Upgrade`/`Connection`, o handshake falha com `400` e o app nunca conecta.

### 9.4 Ambientes

| Ambiente | Host | Banco | FCM | Uso |
|---|---|---|---|---|
| `local` | `127.0.0.1:8000` | SQLite ou Postgres local | emulador / desabilitado | desenvolvimento |
| `staging` | VPS (porta/subdomínio separado) | Postgres de staging | projeto Firebase de teste | validação de build |
| `production` | `163.176.229.20` (443) | Postgres + PostGIS | projeto Firebase de produção | usuários reais |

---

## 10. Riscos e Limites Conhecidos

| # | Risco | Impacto | Mitigação |
|---|---|---|---|
| R1 | FCM pode atrasar/entregar fora de ordem | wake-up lento | reconnect proativo no foreground + TTL curto + `call_id` para descartar obsoleto |
| R2 | Fabricantes (Xiaomi/Huawei/Samsung) matam serviços agressivamente | app morre de fato | guia de isenção de bateria por fabricante + serviço persistente + `RECEIVE_BOOT_COMPLETED` |
| R3 | PushKit VoIP no iOS pode ser rejeitado na revisão | bloqueio de release | justificar uso de voz real; fallback com notificação visível |
| R4 | Hub em memória = nó único | sem HA | MVP single-node; escala horizontal exige ADR (pub/sub) |
| R5 | Áudio sobre WS sofre em 3G instável | fala picotada | Opus 16–24 kbps, jitter buffer, descarte de frames antigos |
| R6 | Vazamento de chave SSH / SA JSON | comprometimento total | `.gitignore` + regra §9 + rotação imediata |
| R7 | PostGIS ausente no início (SQLite) | queries geo diferentes | abstrair em `GeoRepository`; Haversine no SQLite, PostGIS em prod |

---

## 11. Decisões Pendentes (exigem ADR antes de implementar)

| ADR | Tema | Fase |
|---|---|---|
| ADR-001 | Estratégia de escala do hub WS (in-memory vs pub/sub) | 6 |
| ADR-002 | PushKit VoIP vs notificação visível no iOS | 3 |
| ADR-003 | Retenção e anonimização do `location_history` (LGPD) | 2 |
| ADR-004 | Armazenamento de áudio: só streaming ou gravação opcional | 5 |
| ADR-005 | Multi-tenant de círculos vs instância única por organização | 4 |

---

## 12. Referências Internas

- `.opencode/rules.md` — stack fechada, padrões de código, gate documental.
- `docs/DATA_MODEL.md` — entidades, colunas, índices.
- `docs/TASKS.md` — roadmap em 6 fases.
- `docs/STATE_TRACEABILITY.md` — histórico de decisões e estado.
- `docs/openapi.yaml` — contrato HTTP (criado na Fase 2).
