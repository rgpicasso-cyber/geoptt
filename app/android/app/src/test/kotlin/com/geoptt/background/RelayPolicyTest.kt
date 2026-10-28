package com.geoptt.background

import android.content.pm.ServiceInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Regras puras do relay — o que os testes instrumentados não alcançam sem emulador.
 *
 * Cobre os dois pontos onde um erro é silencioso em produção: a negociação de
 * `foregroundServiceType` (rebaixar `microphone` sem avisar) e o consentimento
 * (`relay_enabled`) no caminho de wake-up/boot.
 */
class RelayPolicyTest {

    private val location = ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
    private val playback = ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
    private val microphone = ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE

    // ------------------------------------------------------------------ fullTypes

    @Test
    fun `abaixo do Android 10 nao existe tipo declarado`() {
        assertEquals(0, RelayPolicy.fullTypes(28))
        assertEquals(listOf(0), RelayPolicy.typeLadder(RelayContract.SOURCE_UI, 28))
    }

    @Test
    fun `android 10 nao tem permissao de microfone em foreground service`() {
        // API 29 não conhece FOREGROUND_SERVICE_TYPE_MICROPHONE: pedir derruba o start.
        assertEquals(location or playback, RelayPolicy.fullTypes(29))
    }

    @Test
    fun `android 11 em diante inclui microfone`() {
        assertEquals(location or playback or microphone, RelayPolicy.fullTypes(30))
        assertEquals(location or playback or microphone, RelayPolicy.fullTypes(34))
    }

    // ------------------------------------------------------------------ escada da UI

    @Test
    fun `ui tenta o conjunto completo primeiro`() {
        assertEquals(
            listOf(location or playback or microphone, location or playback, playback),
            RelayPolicy.typeLadder(RelayContract.SOURCE_UI, 34),
        )
    }

    @Test
    fun `ui nao repete tipos equivalentes no android 10`() {
        // Em API 29 `fullTypes` == sem microfone; `distinct()` evita tentar duas vezes
        // o mesmo startForeground (cada tentativa recusada custa tempo do onCreate).
        assertEquals(
            listOf(location or playback, playback),
            RelayPolicy.typeLadder(RelayContract.SOURCE_UI, 29),
        )
    }

    // ------------------------------------------------------------------ escada de FCM

    @Test
    fun `fcm tenta sem microfone antes`() {
        // O app não está em foreground: `microphone` (regra while-in-use do Android 14)
        // é a última tentativa, não a primeira.
        assertEquals(
            listOf(location or playback, playback, location or playback or microphone),
            RelayPolicy.typeLadder(RelayContract.SOURCE_FCM, 34),
        )
    }

    @Test
    fun `fcm nunca comeca por microphone`() {
        val first = RelayPolicy.typeLadder(RelayContract.SOURCE_FCM, 34).first()
        assertEquals(0, first and microphone)
    }

    @Test
    fun `restart usa a mesma escada de fcm`() {
        assertEquals(
            RelayPolicy.typeLadder(RelayContract.SOURCE_FCM, 34),
            RelayPolicy.typeLadder(RelayContract.SOURCE_RESTART, 34),
        )
    }

    // ------------------------------------------------------------------ boot

    @Test
    fun `boot no android 14 tenta location e playback antes de so playback`() {
        assertEquals(
            listOf(location or playback, location, playback),
            RelayPolicy.typeLadder(RelayContract.SOURCE_BOOT, 34),
        )
    }

    @Test
    fun `boot no android 15 so pode usar location`() {
        // API 35 proíbe mediaPlayback/microphone a partir de BOOT_COMPLETED: qualquer
        // outra tentativa lança ForegroundServiceStartNotAllowedException.
        assertEquals(
            listOf(location),
            RelayPolicy.typeLadder(RelayContract.SOURCE_BOOT, 35),
        )
        assertEquals(
            listOf(location),
            RelayPolicy.typeLadder(RelayContract.SOURCE_BOOT, 36),
        )
    }

    @Test
    fun `boot no android 15 nunca pede microphone nem playback`() {
        val prohibited = microphone or playback
        RelayPolicy.typeLadder(RelayContract.SOURCE_BOOT, 35).forEach { types ->
            assertTrue("types=$types", types and prohibited == 0)
        }
    }

    // ------------------------------------------------------------------ describeTypes

    @Test
    fun `describeTypes traduz o bitmask na ordem do relatorio`() {
        assertEquals(
            listOf("mediaPlayback", "location", "microphone"),
            RelayPolicy.describeTypes(location or playback or microphone, 34),
        )
    }

    @Test
    fun `describeTypes omite microphone abaixo do android 11`() {
        // API 30 (Android 11) é o mínimo que conhece FOREGROUND_SERVICE_TYPE_MICROPHONE.
        assertEquals(
            listOf("mediaPlayback", "location"),
            RelayPolicy.describeTypes(location or playback or microphone, 29),
        )
    }

    @Test
    fun `describeTypes devolve lista vazia para zero`() {
        assertTrue(RelayPolicy.describeTypes(0, 34).isEmpty())
    }

    // ------------------------------------------------------------------ consentimento

    @Test
    fun `wakeup so sobe o relay com consentimento persistido`() {
        assertTrue(RelayPolicy.shouldStartRelayOnWakeup(relayEnabled = true))
        assertFalse(RelayPolicy.shouldStartRelayOnWakeup(relayEnabled = false))
    }

    @Test
    fun `boot so religa com consentimento persistido`() {
        assertTrue(RelayPolicy.shouldRestartOnBoot(relayEnabled = true))
        assertFalse(RelayPolicy.shouldRestartOnBoot(relayEnabled = false))
    }
}
