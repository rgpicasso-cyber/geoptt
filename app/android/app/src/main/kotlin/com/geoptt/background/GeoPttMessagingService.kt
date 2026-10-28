package com.geoptt.background

import android.content.Context
import android.os.PowerManager
import android.util.Log
import com.google.firebase.messaging.RemoteMessage
import io.flutter.plugins.firebase.messaging.FlutterFirebaseMessagingService

/**
 * Recebe a Data Message de wake-up **no nível nativo**, antes (e independentemente) de
 * qualquer isolate Dart existir.
 *
 * Por que herdar de `FlutterFirebaseMessagingService`:
 *  * o manifest remove a declaração do serviço do plugin e declara este no lugar
 *    (`tools:node="remove"`), então só existe **um** serviço com o intent-filter
 *    `com.google.firebase.MESSAGING_EVENT` — dois serviços disputando o filtro deixariam
 *    a entrega indefinida;
 *  * a entrega ao Dart não depende deste serviço (o plugin usa
 *    `FlutterFirebaseMessagingReceiver`), mas `onNewToken`/`onRegistered` do plugin
 *    vivem aqui: chamar `super` mantém o stream de token do Dart funcionando.
 *
 * Risco de acoplamento registrado em `docs/ARCHITECTURE.md` §10 (R8).
 */
class GeoPttMessagingService : FlutterFirebaseMessagingService() {

    override fun onMessageReceived(message: RemoteMessage) {
        try {
            handleWakeup(message)
        } catch (throwable: Throwable) {
            // Uma falha nossa nunca pode impedir o FlutterFire de entregar ao Dart.
            Log.e(TAG, "falha no tratamento nativo do wake-up", throwable)
        } finally {
            super.onMessageReceived(message)
        }
    }

    override fun onNewToken(token: String) {
        // Mantém o `FlutterFirebaseTokenLiveData` do plugin alimentado. O token não é
        // persistido nativamente: quem o envia ao backend é o Dart autenticado
        // (`POST /users/me/fcm-token`).
        super.onNewToken(token)
    }

    private fun handleWakeup(message: RemoteMessage) {
        when (val result = WakeupPayloadParser.parse(message.data)) {
            is WakeupParseResult.Ignored -> Unit

            is WakeupParseResult.Rejected ->
                Log.w(TAG, "wake-up descartado: ${result.reason}")

            is WakeupParseResult.Accepted -> {
                val payload = result.payload
                val preferences = RelayPreferences(applicationContext)
                preferences.recordWakeup(payload.channelId, payload.timestampSeconds)

                // O wake-up sempre é publicado: se a UI estiver viva, o Dart decide o que
                // fazer (ex.: registrar "chamada perdida"). O que NÃO pode acontecer é
                // ressuscitar o Foreground Service quando o usuário desligou o canal —
                // `relay_enabled` é consentimento, não preferência (ver RelayPolicy).
                RelayController.publishWakeup(payload, RelayContract.SOURCE_FCM)

                if (!RelayPolicy.shouldStartRelayOnWakeup(preferences.relayEnabled)) {
                    Log.i(TAG, "wake-up PTT ignorado: canal desligado pelo usuário")
                    return
                }

                acquireShortWakeLock()
                val started = BackgroundRelayService.start(
                    applicationContext,
                    RelayContract.SOURCE_FCM,
                )
                Log.i(TAG, "wake-up PTT aceito; relay solicitado=$started")
            }
        }
    }

    /**
     * Lock curto que cobre o intervalo entre o broadcast e o `onCreate` do serviço
     * (que adquire o lock longo). Não é liberado manualmente: o timeout de 15 s garante
     * que não vaza caso o serviço seja recusado pelo SO.
     */
    private fun acquireShortWakeLock() {
        try {
            val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
            powerManager
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, RelayContract.FCM_WAKE_LOCK_TAG)
                .apply {
                    setReferenceCounted(false)
                    acquire(RelayContract.FCM_WAKE_LOCK_TIMEOUT_MS)
                }
        } catch (exc: RuntimeException) {
            Log.w(TAG, "não foi possível adquirir WakeLock curto", exc)
        }
    }

    private companion object {
        private const val TAG = "GeoPttFcm"
    }
}
