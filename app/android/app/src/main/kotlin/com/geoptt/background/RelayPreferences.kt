package com.geoptt.background

import android.content.Context

/**
 * Estado persistido do relay.
 *
 * `relay_enabled` é a **única** fonte de verdade para religar o serviço no boot: se o
 * usuário nunca ativou o modo PTT (ou desativou), o `BootReceiver` não faz nada. Isso
 * evita transmitir localização sem consentimento explícito.
 *
 * A escrita usa `commit()` e não `apply()` de propósito: `apply()` agenda a gravação em
 * disco de forma assíncrona e o processo pode ser morto pelo SO antes do flush (é
 * exatamente o cenário de swipe-away / low-memory killer que este módulo existe para
 * sobreviver). O custo é um I/O síncrono em uma escrita raríssima — aceitável.
 */
internal class RelayPreferences(context: Context) {

    private val prefs =
        context.applicationContext.getSharedPreferences(RelayContract.PREFS_NAME, Context.MODE_PRIVATE)

    var relayEnabled: Boolean
        get() = prefs.getBoolean(RelayContract.KEY_RELAY_ENABLED, false)
        set(value) {
            prefs.edit().putBoolean(RelayContract.KEY_RELAY_ENABLED, value).commit()
        }

    fun recordWakeup(channelId: String, timestampSeconds: Long) {
        prefs.edit()
            .putString(RelayContract.KEY_LAST_WAKEUP_CHANNEL, channelId)
            .putLong(RelayContract.KEY_LAST_WAKEUP_TS, timestampSeconds)
            .commit()
    }

    fun lastWakeupChannelId(): String? = prefs.getString(RelayContract.KEY_LAST_WAKEUP_CHANNEL, null)

    fun lastWakeupTimestamp(): Long = prefs.getLong(RelayContract.KEY_LAST_WAKEUP_TS, 0L)
}
