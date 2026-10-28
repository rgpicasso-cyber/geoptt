---
name: mobile-background-resilience
description: Diretrizes e padrões de código para manter o app vivo contra swipe-away, doze mode e otimização de bateria.
---

# Mobile Background Resilience Skill

## Quando usar esta Skill
Sempre que for alterar o `AndroidManifest.xml`, implementar handlers do Firebase Messaging em background, configurar Foreground Services ou solicitar permissões de bateria no Flutter.

## Regras de Ouro
1. **FCM Data Message:** Nunca use mensagens do tipo "Notification" no backend para o gatilho PTT. Sempre envie "Data Messages" com `priority: high` e `ttl: 0`.
2. **Isolate Entry-Point:** O handler `_firebaseMessagingBackgroundHandler` no Flutter DEVE estar anotado com `@pragma('vm:entry-point')` e fora de qualquer classe.
3. **Android 14+ Compliance:** Todo `Foreground Service` no Android Manifest deve declarar seu tipo explícito (`android:foregroundServiceType="microphone|mediaPlayback|location"`).
4. **Isenção de Bateria:** A permissão `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` deve ser solicitada de forma graciosa na UI do Flutter antes de ligar o serviço PTT.

## Modelo do AndroidManifest.xml (Trecho Essencial)
```xml
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MICROPHONE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_LOCATION" />
<uses-permission android:name="android.permission.WAKE_LOCK" />
<uses-permission android:name="android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" />
<uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
```
