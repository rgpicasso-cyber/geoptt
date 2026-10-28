package com.geoptt.background

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Testes de JVM (sem emulador) do contrato de wake-up.
 *
 * O parser é o ponto onde um payload malformado poderia acordar o serviço e drenar
 * bateria — por isso ele é Kotlin puro e testado isoladamente.
 */
class WakeupPayloadParserTest {

    private val channelId = "8b6f1a2c-3d4e-4f50-9a6b-7c8d9e0f1a2b"
    private val senderId = "11111111-2222-4333-8444-555555555555"
    private val callId = "99999999-8888-4777-8666-555555555555"
    private val now = 1_730_000_000L

    private fun validData(): Map<String, String> = mapOf(
        "type" to "PTT_WAKEUP",
        "v" to "1",
        "channel_id" to channelId,
        "sender_id" to senderId,
        "call_id" to callId,
        "ts" to now.toString(),
    )

    @Test
    fun `aceita payload completo valido`() {
        val result = WakeupPayloadParser.parse(validData(), now)

        assertTrue(result is WakeupParseResult.Accepted)
        val payload = (result as WakeupParseResult.Accepted).payload
        assertEquals(channelId, payload.channelId)
        assertEquals(senderId, payload.senderId)
        assertEquals(callId, payload.callId)
        assertEquals(now, payload.timestampSeconds)
        assertEquals(1, payload.protocolVersion)
    }

    @Test
    fun `ignora mensagem que nao e wakeup`() {
        val data = validData() + ("type" to "LOCATION_UPDATE")

        assertEquals(WakeupParseResult.Ignored, WakeupPayloadParser.parse(data, now))
    }

    @Test
    fun `rejeita channel_id ausente ou invalido`() {
        val semCanal = validData() - "channel_id"
        val canalInvalido = validData() + ("channel_id" to "nao-e-uuid")

        assertEquals(
            WakeupParseResult.Rejected(WakeupPayloadParser.REASON_INVALID_CHANNEL),
            WakeupPayloadParser.parse(semCanal, now),
        )
        assertEquals(
            WakeupParseResult.Rejected(WakeupPayloadParser.REASON_INVALID_CHANNEL),
            WakeupPayloadParser.parse(canalInvalido, now),
        )
    }

    @Test
    fun `rejeita sender_id e call_id invalidos`() {
        assertEquals(
            WakeupParseResult.Rejected(WakeupPayloadParser.REASON_INVALID_SENDER),
            WakeupPayloadParser.parse(validData() + ("sender_id" to "x"), now),
        )
        assertEquals(
            WakeupParseResult.Rejected(WakeupPayloadParser.REASON_INVALID_CALL),
            WakeupPayloadParser.parse(validData() + ("call_id" to "y"), now),
        )
    }

    @Test
    fun `rejeita timestamp invalido`() {
        assertEquals(
            WakeupParseResult.Rejected(WakeupPayloadParser.REASON_INVALID_TIMESTAMP),
            WakeupPayloadParser.parse(validData() + ("ts" to "agora"), now),
        )
        assertEquals(
            WakeupParseResult.Rejected(WakeupPayloadParser.REASON_INVALID_TIMESTAMP),
            WakeupPayloadParser.parse(validData() - "ts", now),
        )
    }

    @Test
    fun `descarta wakeup obsoleto alem da tolerancia`() {
        val antigo = now - WakeupPayloadParser.MAX_CLOCK_SKEW_SECONDS - 1

        assertEquals(
            WakeupParseResult.Rejected(WakeupPayloadParser.REASON_STALE),
            WakeupPayloadParser.parse(validData() + ("ts" to antigo.toString()), now),
        )
    }

    @Test
    fun `descarta wakeup no futuro alem da tolerancia`() {
        val futuro = now + WakeupPayloadParser.MAX_CLOCK_SKEW_SECONDS + 1

        assertEquals(
            WakeupParseResult.Rejected(WakeupPayloadParser.REASON_STALE),
            WakeupPayloadParser.parse(validData() + ("ts" to futuro.toString()), now),
        )
    }

    @Test
    fun `aceita no limite da tolerancia`() {
        val limite = now - WakeupPayloadParser.MAX_CLOCK_SKEW_SECONDS

        assertTrue(
            WakeupPayloadParser.parse(validData() + ("ts" to limite.toString()), now)
                is WakeupParseResult.Accepted,
        )
    }

    @Test
    fun `assume versao 1 quando v esta ausente`() {
        val result = WakeupPayloadParser.parse(validData() - "v", now)

        assertEquals(1, (result as WakeupParseResult.Accepted).payload.protocolVersion)
    }

    @Test
    fun `rejeita versao nao positiva`() {
        assertEquals(
            WakeupParseResult.Rejected(WakeupPayloadParser.REASON_INVALID_VERSION),
            WakeupPayloadParser.parse(validData() + ("v" to "0"), now),
        )
    }

    @Test
    fun `aceita payload minimo sem sender e call`() {
        val data = validData() - "sender_id" - "call_id"
        val result = WakeupPayloadParser.parse(data, now)

        assertTrue(result is WakeupParseResult.Accepted)
        val payload = (result as WakeupParseResult.Accepted).payload
        assertNull(payload.senderId)
        assertNull(payload.callId)
    }
}
