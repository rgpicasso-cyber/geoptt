# Regras R8 do módulo `:app`.
#
# Ainda não são aplicadas em build de release (`isMinifyEnabled = false` na Fase 3), mas
# já ficam ligadas no `buildTypes.release` para que a virada seja só a flag — e para que
# a primeira release minificada não perca os componentes de background.
#
# Componentes citados no AndroidManifest já são mantidos automaticamente pelo AGP; as
# regras abaixo existem para o que o R8 não enxerga: nomes legíveis em stack trace de
# crash (Crashlytics/Sentry) e os overrides chamados pelo framework.

# Stack traces do relay/FCM precisam mostrar nomes reais: sem isso, um crash em produção
# vira "a.b.c()" e a investigação do swipe-away fica impossível.
-keepnames class com.geoptt.background.** { *; }

# Pontos de entrada instanciados pelo SO (manifest) — redundante com a regra do AGP, mas
# explícito para não depender de detalhe de implementação da ferramenta.
-keep class com.geoptt.background.BackgroundRelayService { *; }
-keep class com.geoptt.background.BootReceiver { *; }
-keep class com.geoptt.background.GeoPttMessagingService { *; }

# `FirebaseMessagingService` chama `onMessageReceived`/`onNewToken` por dispatch da classe
# base; manter os nomes garante que o override continue sendo encontrado mesmo se o R8
# optar por renomear a hierarquia.
-keepclassmembers class * extends com.google.firebase.messaging.FirebaseMessagingService {
    public void onMessageReceived(com.google.firebase.messaging.RemoteMessage);
    public void onNewToken(java.lang.String);
}

# Flutter embedding e plugin do Firebase Messaging têm regras próprias publicadas nos AARs.
# Não redeclarar aqui para não congelar nomes internos de terceiros.
