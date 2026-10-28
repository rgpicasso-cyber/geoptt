---
name: ptt-audio-engine
description: Padrões e bibliotecas para streaming de áudio PTT bidirecional de baixa latência (WebSockets) no Flutter.
---

# PTT Audio Engine Skill

## Quando usar esta Skill
Sempre que for implementar a captura de microfone, envio de pacotes de voz, recebimento de stream de áudio via WebSocket ou configuração do player de áudio no Flutter.

## Regras de Ouro
1. **Compressão (Codec):** O áudio DEVE ser capturado e transmitido utilizando o codec **Opus**. Ele é essencial para aplicações PTT devido à altíssima compressão com baixa latência, fundamental em conexões 3G/4G instáveis.
2. **Audio Foco (Audio Session):** Antes de iniciar qualquer gravação ou reprodução, o app DEVE configurar o pacote `audio_session`. O tipo de sessão deve ser configurado como `AVAudioSessionCategoryPlayAndRecord` (iOS) ou `USAGE_VOICE_COMMUNICATION` (Android) para que o áudio do PTT reduza o volume de músicas (ducking) ou pause outras mídias.
3. **Streaming em Chunks:** Nunca grave o áudio inteiro para só então enviar. O áudio deve ser particionado e enviado em pequenos "chunks" (pedaços) via WebSocket (ex: a cada 200ms) para que a outra ponta escute em tempo real.
4. **Reprodução Contínua:** No recebimento, os chunks devem ser enfileirados em um *buffer* e reproduzidos sequencialmente usando pacotes como `just_audio` (com `StreamAudioSource`).
