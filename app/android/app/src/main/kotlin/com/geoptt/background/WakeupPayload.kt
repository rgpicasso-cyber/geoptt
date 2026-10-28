package com.geoptt.background

/**
 * Payload de wake-up PTT recebido por Data Message do FCM.
 *
 * Espelha o que `FcmService.build_message` produz no backend
 * (`backend/app/services/fcm_service.py`) — todos os valores de `data` chegam como
 * `String`, porque o FCM não transporta tipos.
 *
 * Esta classe é **Kotlin puro** (sem dependência de `android.*`) justamente para ser
 * testável em JVM, sem emulador.
 */
internal data class WakeupPayload(
    val channelId: String,
    val senderId: String?,
    val callId: String?,
    val timestampSeconds: Long,
    val protocolVersion: Int,
)

/** Resultado do parsing: aceito, ignorado (não é wake-up) ou rejeitado com motivo. */
internal sealed interface WakeupParseResult {

    data class Accepted(val payload: WakeupPayload) : WakeupParseResult

    /** Mensagem válida que não é um `PTT_WAKEUP` — segue o fluxo normal do FlutterFire. */
    data object Ignored : WakeupParseResult

    /** Mensagem de wake-up inválida ou obsoleta; descartar sem acordar o serviço. */
    data class Rejected(val reason: String) : WakeupParseResult
}

internal object WakeupPayloadParser {

    const val TYPE_PTT_WAKEUP = "PTT_WAKEUP"

    /**
     * Tolerância de relógio entre servidor e aparelho. Acima disso a mensagem é
     * considerada obsoleta: com `ttl=0` no FCM, acordar para um PTT de minutos atrás
     * só consome bateria e atrapalha o canal.
     */
    const val MAX_CLOCK_SKEW_SECONDS = 300L

    const val REASON_INVALID_CHANNEL = "invalid_channel_id"
    const val REASON_INVALID_SENDER = "invalid_sender_id"
    const val REASON_INVALID_CALL = "invalid_call_id"
    const val REASON_INVALID_TIMESTAMP = "invalid_timestamp"
    const val REASON_STALE = "stale_wakeup"
    const val REASON_INVALID_VERSION = "invalid_protocol_version"

    private val UUID_PATTERN =
        Regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

    /**
     * @param data mapa cru entregue pelo `RemoteMessage.data`.
     * @param nowSeconds relógio injetável — sem isso o teste unitário dependeria do
     *   horário da máquina e ficaria intermitente.
     */
    fun parse(data: Map<String, String>, nowSeconds: Long = currentTimeSeconds()): WakeupParseResult {
        if (data["type"] != TYPE_PTT_WAKEUP) {
            return WakeupParseResult.Ignored
        }

        val channelId = data["channel_id"].orEmpty()
        if (!isUuid(channelId)) {
            return WakeupParseResult.Rejected(REASON_INVALID_CHANNEL)
        }

        val senderId = data["sender_id"]?.takeIf { it.isNotEmpty() }
        if (senderId != null && !isUuid(senderId)) {
            return WakeupParseResult.Rejected(REASON_INVALID_SENDER)
        }

        val callId = data["call_id"]?.takeIf { it.isNotEmpty() }
        if (callId != null && !isUuid(callId)) {
            return WakeupParseResult.Rejected(REASON_INVALID_CALL)
        }

        val timestamp = data["ts"]?.toLongOrNull()
            ?: return WakeupParseResult.Rejected(REASON_INVALID_TIMESTAMP)

        if (kotlin.math.abs(nowSeconds - timestamp) > MAX_CLOCK_SKEW_SECONDS) {
            return WakeupParseResult.Rejected(REASON_STALE)
        }

        val version = data["v"]?.toIntOrNull() ?: 1
        if (version <= 0) {
            return WakeupParseResult.Rejected(REASON_INVALID_VERSION)
        }

        return WakeupParseResult.Accepted(
            WakeupPayload(
                channelId = channelId,
                senderId = senderId,
                callId = callId,
                timestampSeconds = timestamp,
                protocolVersion = version,
            ),
        )
    }

    fun isUuid(value: String): Boolean = UUID_PATTERN.matches(value)

    private fun currentTimeSeconds(): Long = System.currentTimeMillis() / 1000L
}
