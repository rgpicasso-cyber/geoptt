---
name: fastapi-websocket-hub
description: Padrões de arquitetura para o servidor FastAPI com WebSockets e fallback de FCM.
---

# FastAPI WebSocket Hub Skill

## Quando usar esta Skill
Sempre que estiver desenvolvendo endpoints no backend, gerenciadores de salas/canais PTT, controle de estado de conexão e disparo de Push via Firebase Admin SDK.

## Regras de Ouro
1. **Connection Manager:** Mantenha um dicionário de conexões ativas `active_connections: Dict[str, WebSocket]`.
2. **Fallback FCM Automático:** Se `target_user_id` não estiver em `active_connections`, execute IMEDIATAMENTE a função de disparo de FCM Data Message.
3. **Não bloqueante:** Todas as rotas de envio de áudio e localização devem ser totalmente assíncronas (`async/await`).

## Lógica do Fallback (Pseudocódigo de Referência)
```python
async def route_ptt_payload(sender_id: str, target_id: str, audio_chunk: bytes):
    target_socket = manager.get_connection(target_id)
    if target_socket:
        await target_socket.send_bytes(audio_chunk)
    else:
        # Usuário está offline ou app fechado (swipe-away)
        await fcm_service.send_wakeup_push(
            user_id=target_id,
            data={"type": "PTT_WAKEUP", "sender_id": sender_id}
        )
```
