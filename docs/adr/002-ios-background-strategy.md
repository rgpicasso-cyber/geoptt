# ADR-002 — Estratégia de Background / Push no iOS (PTT)

- **Status:** Aceito
- **Data:** 2026-10-28
- **Fase:** 3.2 (iOS nativo)
- **Contexto:** O GeoPTT precisa receber áudio PTT e manter localização em background no iOS, sem que o app seja morto pelo *swipe-away*. O Android já usa FCM Data Message + Foreground Service (Fase 3.1). No iOS a abordagem é diferente porque não existe *Foreground Service* equivalente; o SO controla estritamente o que pode rodar em background.

---

## Contexto Técnico

| Requisito | Detalhe |
|---|---|
| **Wake-up confiável** | O servidor deve conseguir acordar o app (mesmo fechado) para entregar um frame de áudio Opus (≈200 ms) e/ou pedir atualização de localização. |
| **Latência** | ≤ 1 s do envio do push até o app começar a reproduzir/processar. |
| **Experiência do usuário** | Sem tela cheia de chamada a cada mensagem PTT (o Zello hoje mostra apenas o ícone de rádio azul na Dynamic Island / barra superior). |
| **Política da App Store** | Guideline 2.5.4: *apps que declaram `UIBackgroundModes = audio`/`voip` devem de fato oferecer a funcionalidade correspondente*. Uso indevido de VoIP ⇒ rejeição. |
| **Entitlements** | `com.apple.developer.push-to-talk` (PTT Framework) exige pedido à Apple; `com.apple.developer.pushkit.unrestricted-voip` foi desabilitado no iOS 26 SDK. |
| **Integração com backend** | O backend já envia FCM Data Message no Android. No iOS **FCM não consegue enviar push tipo `voip`/`pushtotalk`** – precisa chamar APNs direto (token APNs, JWT, header `apns-push-type: pushtotalk` e topic `bundle-id.voip-ptt`). |

---

## Opções Analisadas

### OPÇÃO A — PushKit + CallKit (VoIP clássico)

| Aspecto | Detalhe |
|---|---|
| **Como funciona** | App registra `PKPushRegistry` para *VoIP pushes*. Ao receber push, **obrigatoriamente** reporta `CXProvider.reportNewIncomingCall` → exibe a tela de chamada nativa do iOS (lock screen, banner, Dynamic Island). O usuário aceita/recusa; só então o áudio flui. |
| **Prós** | • API estável desde iOS 8. <br>• Funciona em *qualquer* iOS suportado (iOS 12+). <br>• Push de alta prioridade (APNs `voip`) – entrega praticamente imediata. |
| **Contras** | • **Tela cheia de chamada a cada PTT** – experiência ruim para walkie-talkie (o Zello abandonou). <br>• CallKit exige *audio session* de chamada telefônica; não permite áudio *half-duplex* estilo PTT sem UI de chamada. <br>• A partir do **iOS 26 SDK**, apps que recebem VoIP push e **não** reportam CallKit são *terminados* pelo sistema (entitlement `unrestricted-voip.ptt` removido). |
| **Risco de rejeição (Guideline 2.5.4)** | **ALTO** – se o app não for *realmente* um app de chamadas de voz/vídeo (ex.: PTT half-duplex sem UI de chamada), a Apple rejeita por *misuse of VoIP background mode*. Vários relatos de rejeição de apps “walkie-talkie” que usavam CallKit só para ganhar background. |
| **Entitlements** | `com.apple.developer.pushkit.voip` (standard) – concedido automaticamente ao ativar *Voice over IP* em *Signing & Capabilities*. |
| **Integração backend** | Backend precisa manter **dois caminhos de push**: FCM (Android) + APNs VoIP (iOS). Token APNs VoIP é diferente do token FCM. |

---

### OPÇÃO B — iOS 16+ PushToTalk Framework (PTT Framework)

| Aspecto | Detalhe |
|---|---|
| **Como funciona** | App usa `PTChannelManager` para *join/leave channel*. Ao entrar no canal, o framework solicita um **token efêmero APNs** (`receivedEphemeralPushToken`). O servidor envia push **tipo `pushtotalk`** (header `apns-push-type: pushtotalk`, topic `bundle-id.voip-ptt`, priority 10, expiration 0). O sistema acorda o app em background, entrega o push ao delegate `PTChannelManagerDelegate`, o app reproduz áudio **sem exibir tela de chamada** – apenas o ícone de rádio azul na Dynamic Island / barra superior. |
| **Prós** | • **UX nativa de PTT** (igual ao Zello 7.7+). <br>• Sem tela cheia; usuário ouve e pode responder via *PTT Shortcut* ou app. <br>• Push de alta prioridade, entrega garantida enquanto canal ativo. <br>• Framework gerencia *audio session*, *interruptions*, *ducking*, *battery*. <br>• **Recomendado pela Apple** para novos apps walkie-talkie (WWDC22 “you should use the PushToTalk framework now”). |
| **Contras** | • **Requer iOS 16+** (mínimo). <br>• **Entitlement `com.apple.developer.push-to-talk`** só liberado após *request* à Apple (formulário + justificativa de uso operacional / segurança pública / saúde). Processo pode levar dias/semanas. <br>• Token APNs é *por canal* e expira ao sair do canal → backend deve gerenciar tokens efêmeros. <br>• Não funciona em watchOS/macOS/tvOS. |
| **Risco de rejeição** | **BAIXO** – é a API *desenhada* para PTT. Desde que o entitlement seja aprovado e o app de fato implemente PTT (canais, áudio half-duplex), a Apple aprova. Zello, Motorola Wave, ESChat já usam em produção. |
| **Entitlements** | `com.apple.developer.push-to-talk` (restrito). <br>Opcional: `com.apple.developer.networking.local-push-connectivity` para ambientes sem internet (rede local). |
| **Integração backend** | Backend **precisa chamar APNs diretamente** (não via FCM). Payload mínimo: `aps` vazio + chaves custom (ex.: `speaker_id`, `channel_id`, `call_id`). Header `apns-push-type: pushtotalk`, `apns-topic: ${BUNDLE_ID}.voip-ptt`, `apns-priority: 10`, `apns-expiration: 0`. |

---

### OPÇÃO C — APNs Silencioso (`content-available: 1`) + Notification Service Extension

| Aspecto | Detalhe |
|---|---|
| **Como funciona** | Envia push *background* (`content-available: 1`, `apns-push-type: background`). O *Notification Service Extension* (NSE) acorda, pode baixar áudio, gravar no *App Group* e sinalizar o app principal via *Darwin notification* / *CoreData* / *SQLite*. O app principal **não garante execução** – o SO decide se concede tempo de CPU (budget ~30 s por dia, throttling severo se usuário não abre o app). |
| **Prós** | • Não precisa de entitlement restrito. <br>• Funciona em qualquer iOS 10+. |
| **Contras** | • **Entrega não confiável**: Apple limita *silent pushes* a ~2-3 por hora por app se o usuário não interagir. <br>• NSE tem **30 s** de tempo de execução, sem garantia de áudio contínuo. <br>• Não há *audio session* background → não consegue reproduzir áudio enquanto app está suspended. <br>• Não há ícone de rádio / UI de sistema; experiência “push silencioso” é invisível. |
| **Risco de rejeição** | **MÉDIO-ALTO** – se o app declara `UIBackgroundModes = remote-notification` mas não oferece *content refresh* real, a Apple pode rejeitar (2.5.4). Além disso, a experiência de PTT **não funciona** (áudio não toca). |
| **Entitlements** | Nenhum especial além de *Background Modes → Remote notifications*. |
| **Integração backend** | Mesmo endpoint APNs usado para push normal; apenas `content-available: 1`. |

---

## Comparação Resumida

| Critério | A – PushKit+CallKit | B – PushToTalk Framework | C – Silent APNs + NSE |
|---|---|---|---|
| **Experiência PTT (sem tela cheia)** | ❌ | ✅ | ❌ |
| **Entrega garantida/baixa latência** | ✅ | ✅ | ❌ (throttling) |
| **Suporte iOS mínimo** | 12+ | **16+** | 10+ |
| **Entitlement restrito** | Não (VoIP padrão) | **Sim** (`push-to-talk`) | Não |
| **Tempo para aprovação entitlement** | Imediato | Dias–semanas (formulário Apple) | Imediato |
| **Risco rejeição 2.5.4** | **ALTO** (misuse VoIP) | **BAIXO** (API oficial) | **MÉDIO-ALTO** (background abuse) |
| **Complexidade backend** | Dois caminhos (FCM + APNs VoIP) | **APNs direto** (token efêmero por canal) | APNs background (simples) |
| **Futuro-proof (iOS 26+)** | ❌ (unrestricted-voip.ptt removido) | ✅ (framework nativo) | ❌ (silent push cada vez mais restrito) |

---

## Recomendação

**Adotar a OPÇÃO B – iOS 16+ PushToTalk Framework.**

**Justificativa**

1. **Experiência do usuário alinhada ao produto** – ícone de rádio azul, sem tela de chamada, atalhos de PTT na Dynamic Island. É exatamente o que o Zello (referência de mercado) migrou.
2. **Conformidade com Guideline 2.5.4** – a Apple *espera* que apps walkie-talkie usem este framework; uso de VoIP/CallKit para PTT é considerado *misuse* e gera rejeições documentadas.
3. **Roadmap da Apple** – a partir do iOS 26 SDK o entitlement `unrestricted-voip.ptt` foi desabilitado; apps que continuarem no caminho A serão terminados ao receber push VoIP sem reportar CallKit.
4. **Arquitetura limpa** – o framework abstrai *audio session*, *interruptions*, *ducking*, *battery*; menos código nativo proprietário.
5. **Nosso backend já é assíncrono (FastAPI)** – adicionar um cliente APNs (token-based auth, HTTP/2) é trivial; já temos `httpx`/`aiohttp`. O token efêmero por canal encaixa no modelo de *channel* que já existe no domínio.

**Passos seguintes (após aprovação deste ADR)**

1. Submeter *Entitlement Request* para `com.apple.developer.push-to-talk` no Apple Developer Portal (justificativa: “operational push-to-talk for field teams, public safety, logistics”).
2. Atualizar `Info.plist` com `UIBackgroundModes = audio, voip, push-to-talk` (chave `UIBackgroundModes` inclui `push-to-talk` a partir do iOS 16) + `NSMicrophoneUsageDescription` + `NSLocationWhenInUseUsageDescription` + `NSLocationAlwaysAndWhenInUseUsageDescription`.
3. Implementar `AppDelegate` / `PTChannelManagerDelegate` em Swift (iOS native module) + `MethodChannel`/`EventChannel` espelhando o contrato Android (`geoptt/background`).
4. Estender `backend/app/services/fcm_service.py` → novo `ApnsPttService` que envia `pushtotalk` pushes usando *APNs auth key* (JWT) e topic `bundle-id.voip-ptt`.
5. Testes em dispositivo físico (TestFlight) + validação de wake-up, áudio background, Dynamic Island, reconexão WebSocket.
6. Atualizar `docs/ARCHITECTURE.md` §4.2 (contrato nativo iOS), `docs/TASKS.md` §3.2 itens `[X]` e `docs/STATE_TRACEABILITY.md`.

---

## Decisão Pendente do Usuário

> **Aprovar esta ADR (mudar Status para “Aceito”) para que a Fase 3.2 (iOS) possa iniciar.**  
> Caso discorde, indicar qual opção (A ou C) e justificativa; a ADR será revisada.

---

## Referências

- WWDC22 – *“Enhance voice communication with Push to Talk”* (session 10117).
- Apple Developer Documentation – *Creating a Push to Talk app*.
- APNs `pushtotalk` push type spec – `apns-push-type: pushtotalk`, topic suffix `.voip-ptt`.
- Zello Blog – *“What to know about Apple’s PTT framework and Zello”*.
- Apple Developer Forums – *PushKit unrestricted-voip.ptt disabled in iOS 26 SDK*.
- App Store Review Guideline 2.5.4 – *Background modes misuse*.

---