package com.geoptt.background

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Religa o relay depois de reboot ou atualização do app.
 *
 * Só age quando `relay_enabled` está persistido como `true` — ou seja, quando o próprio
 * usuário ativou o modo PTT. Religar sem essa flag significaria transmitir localização
 * sem consentimento, o que é inaceitável em produto de rastreamento.
 *
 * **Android 15+:** receivers de `BOOT_COMPLETED` não podem subir FGS de `mediaPlayback`
 * nem `microphone`. A escada de tipos usada aqui vem de [RelayPolicy.typeLadder], que
 * reduz o conjunto a `location` a partir da API 35.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action !in SUPPORTED_ACTIONS) return

        val preferences = RelayPreferences(context)
        if (!RelayPolicy.shouldRestartOnBoot(preferences.relayEnabled)) {
            Log.i(TAG, "boot ($action): relay desabilitado pelo usuário; nada a fazer")
            return
        }

        val started = BackgroundRelayService.start(context, RelayContract.SOURCE_BOOT)
        Log.i(TAG, "boot ($action): relay solicitado (aceito=$started)")
    }

    companion object {
        private const val TAG = "GeoPttBoot"

        /**
         * Apenas ações **protegidas** do sistema.
         *
         * `QUICKBOOT_POWERON` (Xiaomi/HTC) ficou de fora de propósito: não é broadcast
         * protegido, então qualquer app instalado poderia enviá-lo explicitamente a este
         * receiver exportado e forçar um start de FGS. Os fabricantes cobertos também
         * emitem `BOOT_COMPLETED`.
         */
        private val SUPPORTED_ACTIONS: Set<String> = setOf(
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
        )
    }
}
