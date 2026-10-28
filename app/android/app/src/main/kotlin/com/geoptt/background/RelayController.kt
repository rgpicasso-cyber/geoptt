package com.geoptt.background

import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import io.flutter.plugin.common.EventChannel

/**
 * Estado do relay em escopo de processo + ponte de eventos para o Dart.
 *
 * Vive fora do `Activity`/`Service` de propósito: o `EventChannel` some quando a UI
 * morre, mas o serviço continua vivo e precisa continuar registrando o que aconteceu
 * para que o próximo `attachSink` receba o histórico relevante (wake-up pendente).
 */
internal object RelayController {

    private const val TAG = "GeoPttRelay"

    /**
     * Validade de um wake-up pendente.
     *
     * Um `PTT_DOWN` de cinco minutos atrás não é uma chamada a atender: entregá-lo faria o
     * app abrir o canal e tocar áudio de uma conversa encerrada. O relógio usado é o
     * **monotônico** (`elapsedRealtime`), imune a mudança de fuso/hora do usuário — o
     * `timestampSeconds` do payload vem do servidor e sofreria skew entre as máquinas.
     */
    private const val PENDING_WAKEUP_TTL_MS = 300_000L

    private val mainHandler = Handler(Looper.getMainLooper())
    private val lock = Any()

    @Volatile
    private var running: Boolean = false

    @Volatile
    private var foregroundTypes: List<String> = emptyList()

    private var sink: EventChannel.EventSink? = null

    private data class PendingWakeup(
        val payload: WakeupPayload,
        val source: String,
        val receivedAtMillis: Long,
    )

    private var pendingWakeup: PendingWakeup? = null

    private val startObservers = mutableListOf<(Boolean) -> Unit>()

    // ------------------------------------------------------------------ sink de eventos

    fun attachSink(newSink: EventChannel.EventSink?) {
        synchronized(lock) { sink = newSink }
    }

    fun detachSink() {
        synchronized(lock) { sink = null }
    }

    /** Emite sempre na main thread: `EventSink` não é thread-safe. */
    fun emit(event: Map<String, Any?>) {
        val current = synchronized(lock) { sink } ?: return
        mainHandler.post {
            try {
                current.success(event)
            } catch (exc: RuntimeException) {
                // Sink morto (engine descartada) não pode derrubar o serviço.
                Log.w(TAG, "falha ao emitir evento ${event[RelayContract.KEY_EVENT]}", exc)
                detachSink()
            }
        }
    }

    // ------------------------------------------------------------------ estado

    fun isRunning(): Boolean = running

    fun currentForegroundTypes(): List<String> = foregroundTypes

    fun setRunning(value: Boolean, types: List<String> = emptyList()) {
        running = value
        foregroundTypes = if (value) types else emptyList()
    }

    // ------------------------------------------------------------------ wake-up

    fun publishWakeup(payload: WakeupPayload, source: String) {
        synchronized(lock) {
            pendingWakeup = PendingWakeup(payload, source, SystemClock.elapsedRealtime())
        }
        emit(
            mapOf(
                RelayContract.KEY_EVENT to RelayContract.EVENT_WAKEUP,
                RelayContract.KEY_CHANNEL_ID to payload.channelId,
                RelayContract.KEY_SENDER_ID to payload.senderId,
                RelayContract.KEY_CALL_ID to payload.callId,
                RelayContract.KEY_TIMESTAMP to payload.timestampSeconds,
                RelayContract.KEY_PROTOCOL_VERSION to payload.protocolVersion,
                RelayContract.KEY_SOURCE to source,
            ),
        )
    }

    /**
     * Entrega o último wake-up e o descarta — o Dart só precisa reagir uma vez.
     *
     * A leitura e a limpeza acontecem **sob o mesmo lock**: em dois blocos separados, um
     * `publishWakeup` concorrente (FCM roda fora da main thread) poderia trocar o
     * `pendingWakeupSource` entre a leitura do payload e a do source, e o Dart receberia
     * um wake-up com origem errada.
     *
     * Wake-up expirado é descartado e devolve `null`.
     */
    fun consumePendingWakeup(): Map<String, Any?>? {
        val pending = synchronized(lock) {
            val current = pendingWakeup
            pendingWakeup = null
            current
        } ?: return null

        val ageMs = SystemClock.elapsedRealtime() - pending.receivedAtMillis
        if (ageMs > PENDING_WAKEUP_TTL_MS) {
            Log.i(TAG, "wake-up pendente expirado (${ageMs}ms); descartado")
            return null
        }

        return mapOf(
            RelayContract.KEY_CHANNEL_ID to pending.payload.channelId,
            RelayContract.KEY_SENDER_ID to pending.payload.senderId,
            RelayContract.KEY_CALL_ID to pending.payload.callId,
            RelayContract.KEY_TIMESTAMP to pending.payload.timestampSeconds,
            RelayContract.KEY_PROTOCOL_VERSION to pending.payload.protocolVersion,
            RelayContract.KEY_SOURCE to pending.source,
        )
    }

    // ------------------------------------------------------------------ resolução do start

    /**
     * `startForegroundService` é assíncrono: o `MethodChannel` só pode responder
     * `started` depois que o serviço realmente subiu (ou foi recusado pelo SO).
     */
    fun addStartObserver(observer: (Boolean) -> Unit) {
        synchronized(lock) { startObservers += observer }
    }

    fun removeStartObserver(observer: (Boolean) -> Unit) {
        synchronized(lock) { startObservers -= observer }
    }

    fun resolveStart(started: Boolean) {
        val observers = synchronized(lock) {
            val snapshot = startObservers.toList()
            startObservers.clear()
            snapshot
        }
        observers.forEach { observer -> observer(started) }
    }
}
