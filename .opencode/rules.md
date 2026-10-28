# GeoPTT — Regras do Projeto (`.opencode/rules.md`)

> **Fonte de verdade para conduta de código.** Todo agente/sessão do OpenCode que
> trabalhar neste repositório DEVE obedecer a este arquivo. Em caso de conflito com
> instrução de sessão pontual, **este arquivo prevalece**.

---

## 1. Objetivo do Produto

App híbrido que une duas funcionalidades de tempo real:

1. **Rastreamento estilo Life360** — mapas OpenStreetMap, Círculos/Grupos,
   localização contínua em segundo plano, otimização de bateria.
2. **Push-To-Talk estilo Zello** — áudio de baixa latência em grupo e P2P.

Requisito crítico: **o app não pode morrer no swipe-away**. A arquitetura usa
**FCM Data Message + Foreground Service** (Android) e **PushKit/VoIP + Background
Modes** (iOS) para reconectar o socket e retomar áudio/localização.

---

## 2. Stack Tecnológica (FECHADA — não substituir sem ADR)

| Camada | Tecnologia | Notas |
|--------|-----------|-------|
| Frontend mobile | **Flutter (Dart)** | `strict-casts`, `strict-inference`, null-safety |
| Mapas | **OpenStreetMap** via `flutter_map` (tile OSM) | sem Google Maps/SDK proprietário |
| Backend | **Python 3.12 + FastAPI** | async/await de ponta a ponta, Pydantic v2 |
| Banco (servidor) | **PostgreSQL + PostGIS** | geoespacial, índices GiST |
| Banco (offline mobile) | **SQLite** (Drift/sqflite) | fila offline de eventos |
| Tempo real | **WebSockets** (`fastapi` + `websockets`) | backoff exponencial + jitter |
| Push | **Firebase FCM** (Data Messages) | wake-up silencioso |
| Áudio | **Codec Opus** + `just_audio` + `audio_session` | frames sobre WebSocket (grupo/P2P), chunks de ~200 ms |
| Auth | **JWT (OAuth2 password flow)** | access + refresh tokens |

> Proibido introduzir framework, SDK ou biblioteca nova sem aprovação explícita do
> usuário **e** registro em ADR. Ex.: não trocar `flutter_map` por Google Maps, não
> trocar FastAPI por Django, não trocar Opus por AAC.

---

## 3. Diretrizes de Código Limpo — Flutter (Dart)

- **Tipagem estrita**: habilitar no `analysis_options.yaml`:
  `strict-casts: true`, `strict-inference: true`, `strict-raw-types: true`.
  Nada de `dynamic` em contratos de rede.
- **Imutabilidade**: models de domínio com `final` + `const` construtores sempre
  que possível. Preferir classes `immutable` (freezed/valuetypes) para DTOs.
- **Gerenciamento de estado**: usar **Riverpod**. NÃO introduzir outro
  (GetX/BLoC/Provider) sem aprovação.
- **Camadas** por feature:
  `lib/features/<feature>/{data,domain,presentation}` — dependência aponta para
  dentro (presentation → domain → data). Nunca importar de outra feature diretamente.
- **Tratamento de erros**: exceptions de domínio tipadas; nenhum `print()` de
  coordenada ou token. Usar `debugPrint` somente em DEBUG, redigido.
- **Assincronismo**: `async/await`; streams para localização/áudio; cancelar
  `StreamSubscription`/`Timer` no `dispose`.
- **Natividade**: código Kotlin/Swift isolado em `android/` e `ios/`, acessado via
  `MethodChannel`/`EventChannel` nomeado e tipado.

## 4. Diretrizes de Código Limpo — FastAPI (Python)

- **Tipagem estrita**: type hints em TODAS as assinaturas; `mypy --strict` no CI;
  Pydantic **v2** para todos os schemas de request/response.
- **Assincronismo**: `async def` em rotas, handlers de WebSocket e acesso a DB
  (driver asyncpg/SQLAlchemy async). Nada de I/O bloqueante no event loop.
- **Contrato de API**: o **OpenAPI é a fonte verdade**. Schema gerado versionado em
  `/docs/openapi.yaml`; mudança de contrato exige atualizar docs + clientes.
- **Separacao de camadas**: `routers/` (HTTP/WS) → `services/` (regras de negócio) →
  `repositories/` (acesso a dados). Routers não contêm regra de negócio.
- **Segurança**: validar e autenticar todo endpoint; nunca logar token ou coordenada
  em claro; rate-limit em endpoints de auth e push.
- **Resiliência**: WebSocket com heartbeat (ping/pong); reconexão com backoff no
  cliente; fila DLQ para FCM que falhar.

## 5. Regra Inquebrável de Rastreabilidade

> **TODA nova alteração, feature ou módulo DEVE atualizar a documentação em `/docs`.**

Checklist obrigatório por mudança:

- [ ] `docs/ARCHITECTURE.md` — se a estrutura/fluxo/contrato mudou.
- [ ] `docs/DATA_MODEL.md` — se entidades, colunas ou índices mudaram.
- [ ] `docs/TASKS.md` — marcar `[X]` na tarefa concluída.
- [ ] `docs/STATE_TRACEABILITY.md` — **append** (nunca apagar histórico) com:
      o que foi feito, decisões técnicas, bugs conhecidos, próximo passo exato.
- [ ] `docs/openapi.yaml` — se o contrato HTTP/WS mudou.

Nunca apagar histórico existente. Sempre adicionar.

## 6. Testes (mínimo por fase)

- **Backend**: testes unitários de regras de negócio (pytest + httpx) e teste de
  contrato dos WebSockets.
- **Flutter**: testes de unidade (domains/usecases) + widget tests para telas
  críticas (mapa, rádio PTT).
- Nenhuma fase é marcada `[X]` sem pelo menos o teste mínimo viável passando.

## 7. Commits e Git

- Mensagens no formato Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`.
- Um commit = uma mudança coerente. Não misturar código e refatoração não relacionada.
- Nunca commitar secrets (`google-services.json`, `GoogleService-Info.plist`,
  `.env`, chaves FCM/SA). Existe `.gitignore` específico para isso.

---

## 8. Gate Documental (Docs-First) — Ordem Obrigatória de Trabalho

Nenhuma linha de código de produção é escrita antes de a mudança existir em `/docs`.
A ordem é **sempre**:

1. `docs/ARCHITECTURE.md` / `docs/DATA_MODEL.md` / `docs/TASKS.md` — descrever a mudança.
2. Código (`backend/`, `app/`).
3. Testes mínimos da fase.
4. `docs/STATE_TRACEABILITY.md` — registrar (append) o que foi feito.
5. Marcar `[X]` em `docs/TASKS.md`.

**Exceção única:** correção de bug crítica em produção pode ir direto ao código, mas
exige registro retroativo no mesmo dia em `STATE_TRACEABILITY.md` com o motivo da urgência.

## 9. Credenciais e Infraestrutura de Produção

- A VPS de produção é uma **Ubuntu** acessível por SSH (`ubuntu@163.176.229.20`).
- O acesso se dá **exclusivamente por chave SSH**. Senha/root direto é proibido.
- A chave privada (`ssh-key-2026-09-24.key`) **vive fora do repositório**, com
  permissão `600` (Linux/macOS). No Windows, restringir ACL ao usuário atual.
- **PROIBIDO** commitar, colar em issue, anexar em PR, imprimir em log ou incluir
  chave privada em prompt/documento. O `.gitignore` da raiz bloqueia os padrões
  conhecidos (`*.pem`, `*.key`, `*.rsa`, `serviceAccountKey.json`,
  `ssh-key-2026-09-24.key`), mas o `.gitignore` é rede de segurança, **não** licença
  para descuido.
- Segredos de runtime ficam em `.env` na VPS (nunca versionado) ou em variáveis de
  ambiente do `systemd`. O repositório versiona apenas `.env.example` sem valores.
- Se uma chave for exposta (commit, print, chat, log), ela é considerada
  **comprometida**: revogar no provedor, gerar nova e registrar o incidente em
  `docs/STATE_TRACEABILITY.md`.

## 10. Definition of Done de uma Fase

Uma fase só é aprovada quando, cumulativamente:

- [ ] Código compila/analisa sem erro (`flutter analyze`, `mypy --strict`).
- [ ] Testes mínimos da fase passam.
- [ ] Docs atualizados (seção 5 e 8).
- [ ] `STATE_TRACEABILITY.md` recebeu o registro do dia.
- [ ] Nenhum segredo foi introduzido no diff (`git diff` revisado).

---

*Última atualização: 2026-10-28 (Bootstrap — Fase 1: .gitignore, docs/ e regras de segurança)*
