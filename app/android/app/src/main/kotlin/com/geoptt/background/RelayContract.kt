package com.geoptt.background

/**
 * Constantes compartilhadas entre o serviço de relay, o bridge Dart e os receivers.
 *
 * Manter tudo num único lugar evita a clássica divergência de string entre Kotlin e
 * Dart — o contrato completo está em `docs/ARCHITECTURE.md` §4.1.
 */
internal object RelayContract {

    // ------------------------------------------------------------------ canais Dart
    const val METHOD_CHANNEL = "geoptt/background"
    const val EVENT_CHANNEL = "geoptt/background/events"

    // ------------------------------------------------------------------ notificação
    /**
     * O nome/descrição do canal vêm de `strings.xml` (`relay_channel_name` /
     * `relay_channel_description`): são texto visível ao usuário e precisam de tradução.
     */
    const val NOTIFICATION_CHANNEL_ID = "geoptt_relay"
    const val NOTIFICATION_ID = 4101

    // ------------------------------------------------------------------ actions
    const val ACTION_START = "com.geoptt.background.action.START_RELAY"
    const val ACTION_STOP = "com.geoptt.background.action.STOP_RELAY"

    const val EXTRA_START_SOURCE = "com.geoptt.background.extra.START_SOURCE"
    const val EXTRA_PTT_CHANNEL_ID = "com.geoptt.background.extra.PTT_CHANNEL_ID"

    // ------------------------------------------------------------------ persistência
    const val PREFS_NAME = "geoptt_relay_prefs"
    const val KEY_RELAY_ENABLED = "relay_enabled"
    const val KEY_LAST_WAKEUP_TS = "last_wakeup_ts"
    const val KEY_LAST_WAKEUP_CHANNEL = "last_wakeup_channel_id"

    // ------------------------------------------------------------------ eventos
    const val EVENT_WAKEUP = "wakeup"
    const val EVENT_RELAY_STARTED = "relayStarted"
    const val EVENT_RELAY_STOPPED = "relayStopped"
    const val EVENT_RELAY_START_DENIED = "relayStartDenied"
    const val EVENT_BATTERY_EXEMPTION = "batteryExemptionChanged"
    const val EVENT_NOTIFICATION_PERMISSION = "notificationPermission"

    const val KEY_EVENT = "event"
    const val KEY_SOURCE = "source"
    const val KEY_FOREGROUND_TYPES = "foregroundTypes"
    const val KEY_CHANNEL_ID = "channelId"
    const val KEY_SENDER_ID = "senderId"
    const val KEY_CALL_ID = "callId"
    const val KEY_TIMESTAMP = "timestampSeconds"
    const val KEY_PROTOCOL_VERSION = "protocolVersion"
    const val KEY_GRANTED = "granted"

    // ------------------------------------------------------------------ códigos de erro
    const val ERROR_RELAY_START_DENIED = "RELAY_START_DENIED"
    const val ERROR_SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    const val ERROR_ACTIVITY_DETACHED = "ACTIVITY_DETACHED"
    const val ERROR_UNSUPPORTED = "UNSUPPORTED"

    /** Um `startRelay` anterior foi abandonado porque outro pedido chegou antes. */
    const val ERROR_START_SUPERSEDED = "START_SUPERSEDED"

    // ------------------------------------------------------------------ origens do start
    /** Relay iniciado pela UI (app em foreground) — pode pleitear o tipo `microphone`. */
    const val SOURCE_UI = "ui"

    /** Despertar por Data Message do FCM com a UI possivelmente morta. */
    const val SOURCE_FCM = "fcm"

    /** Religa após reboot ou atualização do pacote. */
    const val SOURCE_BOOT = "boot"

    /** Recriação pelo próprio SO (`START_STICKY` com intent nulo). */
    const val SOURCE_RESTART = "restart"

    // ------------------------------------------------------------------ wake locks
    const val WAKE_LOCK_TAG = "GeoPTT:RelayWakeLock"
    const val FCM_WAKE_LOCK_TAG = "GeoPTT:FcmWakeLock"

    /**
     * O relay nunca segura a CPU indefinidamente: 10 minutos é o teto de uma sessão de
     * PTT contínua e o lock é renovado a cada evento. Bateria drenada é bug de produto.
     */
    const val WAKE_LOCK_TIMEOUT_MS = 10 * 60 * 1000L

    /**
     * Lock curto do handler de FCM: cobre o intervalo entre o broadcast e o
     * `onCreate` do serviço. Curto de propósito — não é para manter o processo vivo.
     */
    const val FCM_WAKE_LOCK_TIMEOUT_MS = 15 * 1000L
}
