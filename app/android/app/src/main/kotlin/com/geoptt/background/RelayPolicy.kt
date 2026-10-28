package com.geoptt.background

import android.content.pm.ServiceInfo

/**
 * Regras puras de negócio do relay — **sem `Context`, sem `Service`**.
 *
 * Existe para ser testável em JVM: a negociação de `foregroundServiceType` e as decisões
 * de consentimento são exatamente onde erros silenciosos acontecem (rebaixar `microphone`
 * a cada wake-up, religar no boot sem permissão do usuário). Com `sdkInt` injetado, o
 * teste cobre API 28→35 sem emulador.
 *
 * As constantes de `ServiceInfo` são `static final int` do Java: o Kotlin as inlina, então
 * nada disso carrega `android.jar` em tempo de execução do teste.
 */
internal object RelayPolicy {

    private const val SDK_Q = 29
    private const val SDK_R = 30

    /**
     * Android 15 (API 35) proíbe que um receiver de `BOOT_COMPLETED` suba FGS dos tipos
     * `mediaPlayback`, `microphone`, `dataSync`, `camera`, `phoneCall` e
     * `mediaProjection`. Como o `mediaPlayback` faz parte do nosso superconjunto, a
     * escada de boot **precisa** ser só `location` a partir dessa API — caso contrário
     * todas as tentativas lançam `ForegroundServiceStartNotAllowedException` e o relay
     * nunca volta depois do reboot.
     */
    private const val SDK_BOOT_RESTRICTIONS = 35

    /** Tipos usados por cada origem, do mais permissivo ao mais restrito. */
    fun typeLadder(source: String, sdkInt: Int): List<Int> {
        if (sdkInt < SDK_Q) {
            // Antes do Android 10 não existe tipo declarado; `ServiceCompat` ignora.
            return listOf(0)
        }

        val location = ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
        val playback = ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
        val withoutMicrophone = location or playback

        return when (source) {
            RelayContract.SOURCE_UI -> listOf(fullTypes(sdkInt), withoutMicrophone, playback)

            RelayContract.SOURCE_BOOT ->
                if (sdkInt >= SDK_BOOT_RESTRICTIONS) {
                    listOf(location)
                } else {
                    listOf(withoutMicrophone, location, playback)
                }

            // FCM e recriação pelo SO: o app não está em foreground, então `microphone`
            // (regra while-in-use do Android 14) fica como última tentativa.
            else -> listOf(withoutMicrophone, playback, fullTypes(sdkInt))
        }.distinct()
    }

    fun fullTypes(sdkInt: Int): Int {
        if (sdkInt < SDK_Q) return 0

        var types = ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION or
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
        if (sdkInt >= SDK_R) {
            types = types or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        }
        return types
    }

    fun describeTypes(types: Int, sdkInt: Int): List<String> {
        if (types == 0) return emptyList()

        val names = mutableListOf<String>()
        if (types and ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK != 0) {
            names += "mediaPlayback"
        }
        if (types and ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION != 0) {
            names += "location"
        }
        if (sdkInt >= SDK_R && types and ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE != 0) {
            names += "microphone"
        }
        return names
    }

    /**
     * `relay_enabled` é **consentimento**, não preferência de UI.
     *
     * Se o usuário desligou o canal PTT, um Data Message de wake-up não pode ressuscitar o
     * serviço: seria voltar a transmitir localização sem autorização — a mesma regra que
     * vale para o boot.
     */
    fun shouldStartRelayOnWakeup(relayEnabled: Boolean): Boolean = relayEnabled

    fun shouldRestartOnBoot(relayEnabled: Boolean): Boolean = relayEnabled
}
