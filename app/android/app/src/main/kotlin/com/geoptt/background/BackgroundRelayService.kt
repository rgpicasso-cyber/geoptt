package com.geoptt.background

import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.geoptt.R

/**
 * Foreground Service que mantém o canal PTT vivo com o app removido da lista de
 * recentes.
 *
 * Três decisões merecem destaque (ver `docs/ARCHITECTURE.md` §4.1):
 *
 *  1. **`foregroundServiceType` é negociado em cascata** ([RelayPolicy.typeLadder]).
 *     O manifest declara o superconjunto `microphone|location|mediaPlayback`, mas o
 *     Android 14+ recusa `microphone` quando o serviço nasce em background e o Android 15
 *     proíbe `mediaPlayback`/`microphone` a partir do boot. Em vez de estourar
 *     `SecurityException` e derrubar o processo, tentamos do mais permissivo ao mais
 *     restrito: receber áudio é mais importante do que falar.
 *  2. **Reentrada não renegocia tipos.** `startForeground` **substitui** o conjunto de
 *     tipos; reexecutar a escada a cada wake-up (origem `fcm`) rebaixaria o relay de
 *     `microphone` para `location|mediaPlayback` e o usuário perderia a fala sem ver erro.
 *     Com o serviço já em foreground, só renovamos o WakeLock — e aceitamos um upgrade
 *     explícito quando o start vem da UI (que está em foreground).
 *  3. **WakeLock sempre com timeout.** `START_STICKY` + lock infinito é a receita de
 *     denúncia por consumo de bateria.
 */
class BackgroundRelayService : Service() {

    private lateinit var preferences: RelayPreferences
    private lateinit var wakeLock: PowerManager.WakeLock

    /** `true` enquanto o serviço está efetivamente em estado de foreground. */
    private var foregroundActive: Boolean = false

    /** Tipos que o SO **concedeu** — não confundir com os que o manifest declara. */
    private var grantedTypes: Int = 0

    override fun onCreate() {
        super.onCreate()
        preferences = RelayPreferences(this)
        wakeLock = newWakeLock()
        RelayNotifications.ensureChannel(this)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == RelayContract.ACTION_STOP) {
            stopRelay(userInitiated = true)
            return START_NOT_STICKY
        }

        // `START_STICKY` recria o serviço com intent nulo. Só continuamos se o usuário
        // havia ativado o modo PTT — religar sozinho seria transmissão sem consentimento.
        if (intent == null && !RelayPolicy.shouldRestartOnBoot(preferences.relayEnabled)) {
            Log.i(TAG, "recriação do SO sem relay habilitado; encerrando")
            stopSelf()
            return START_NOT_STICKY
        }

        val source = intent?.getStringExtra(RelayContract.EXTRA_START_SOURCE)
            ?: RelayContract.SOURCE_RESTART

        if (!startRelay(source)) {
            return START_NOT_STICKY
        }
        return START_STICKY
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Swipe-away não pode derrubar o relay. O log serve de evidência no
        // `adb logcat` durante a validação manual da Fase 3.
        Log.i(TAG, "tarefa removida da lista de recentes; relay permanece ativo")
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        releaseWakeLock()
        if (foregroundActive) {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            foregroundActive = false
        }
        grantedTypes = 0

        if (RelayController.isRunning()) {
            RelayController.setRunning(false)
            RelayController.emit(
                mapOf(
                    RelayContract.KEY_EVENT to RelayContract.EVENT_RELAY_STOPPED,
                    RelayContract.KEY_SOURCE to SOURCE_DESTROY,
                ),
            )
        }
        super.onDestroy()
    }

    // ------------------------------------------------------------------ start/stop

    private fun startRelay(source: String): Boolean {
        // Já em foreground: NUNCA renegociar tipos para baixo (ver KDoc, item 2).
        if (foregroundActive) {
            val upgraded = source == RelayContract.SOURCE_UI && tryUpgradeToFullTypes()
            acquireWakeLock()

            val typeNames = describeGrantedTypes()
            RelayController.setRunning(true, typeNames)
            if (upgraded) {
                RelayController.emit(
                    mapOf(
                        RelayContract.KEY_EVENT to RelayContract.EVENT_RELAY_STARTED,
                        RelayContract.KEY_FOREGROUND_TYPES to typeNames,
                        RelayContract.KEY_SOURCE to source,
                    ),
                )
            }
            RelayController.resolveStart(true)
            Log.i(TAG, "relay já ativo; wake lock renovado (source=$source, types=$typeNames)")
            return true
        }

        val contentText = getString(R.string.relay_notification_text)

        for (types in RelayPolicy.typeLadder(source, Build.VERSION.SDK_INT)) {
            if (!tryStartForeground(types, contentText)) continue

            foregroundActive = true
            grantedTypes = types
            acquireWakeLock()

            val typeNames = describeGrantedTypes()
            RelayController.setRunning(true, typeNames)
            RelayController.emit(
                mapOf(
                    RelayContract.KEY_EVENT to RelayContract.EVENT_RELAY_STARTED,
                    RelayContract.KEY_FOREGROUND_TYPES to typeNames,
                    RelayContract.KEY_SOURCE to source,
                ),
            )
            RelayController.resolveStart(true)
            Log.i(TAG, "relay ativo (source=$source, types=$typeNames)")
            return true
        }

        Log.e(TAG, "SO recusou o foreground service (source=$source)")
        RelayController.setRunning(false)
        RelayController.emit(
            mapOf(
                RelayContract.KEY_EVENT to RelayContract.EVENT_RELAY_START_DENIED,
                RelayContract.KEY_SOURCE to source,
            ),
        )
        RelayController.resolveStart(false)
        stopSelf()
        return false
    }

    /**
     * O relay nasceu por FCM/boot e o usuário abriu o app e tocou "Ativar": agora o
     * processo está em foreground e o Android 14 aceita `microphone`. Só nesse caso vale
     * reexecutar `startForeground` — e apenas se ele conceder mais do que já temos.
     */
    private fun tryUpgradeToFullTypes(): Boolean {
        val full = RelayPolicy.fullTypes(Build.VERSION.SDK_INT)
        if (full == 0 || grantedTypes == full) return false
        if (!tryStartForeground(full, getString(R.string.relay_notification_text))) return false

        grantedTypes = full
        Log.i(TAG, "relay promovido para types=${describeGrantedTypes()}")
        return true
    }

    private fun stopRelay(userInitiated: Boolean) {
        if (userInitiated) {
            preferences.relayEnabled = false
        }

        releaseWakeLock()
        if (foregroundActive) {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            foregroundActive = false
        }
        grantedTypes = 0

        RelayController.setRunning(false)
        RelayController.emit(
            mapOf(
                RelayContract.KEY_EVENT to RelayContract.EVENT_RELAY_STOPPED,
                RelayContract.KEY_SOURCE to if (userInitiated) SOURCE_USER else SOURCE_SYSTEM,
            ),
        )
        RelayController.resolveStart(false)
        stopSelf()
    }

    private fun tryStartForeground(types: Int, contentText: String): Boolean =
        try {
            ServiceCompat.startForeground(
                this,
                RelayContract.NOTIFICATION_ID,
                RelayNotifications.build(this, contentText),
                types,
            )
            true
        } catch (exc: RuntimeException) {
            // Cobre SecurityException (while-in-use do Android 14),
            // ForegroundServiceStartNotAllowedException (Android 12/15) e
            // MissingForegroundServiceTypeException (Android 14) — todas RuntimeException.
            Log.w(TAG, "startForeground recusado (types=$types): ${exc.javaClass.simpleName}")
            false
        }

    private fun describeGrantedTypes(): List<String> =
        RelayPolicy.describeTypes(grantedTypes, Build.VERSION.SDK_INT)

    // ------------------------------------------------------------------ wake lock

    private fun newWakeLock(): PowerManager.WakeLock {
        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        return powerManager
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, RelayContract.WAKE_LOCK_TAG)
            .apply { setReferenceCounted(false) }
    }

    private fun acquireWakeLock() {
        if (wakeLock.isHeld) {
            wakeLock.release()
        }
        // Timeout obrigatório: renovado a cada start/wake-up.
        wakeLock.acquire(RelayContract.WAKE_LOCK_TIMEOUT_MS)
    }

    private fun releaseWakeLock() {
        if (wakeLock.isHeld) {
            wakeLock.release()
        }
    }

    companion object {
        private const val TAG = "GeoPttRelay"

        private const val SOURCE_DESTROY = "destroy"
        private const val SOURCE_USER = "user"
        private const val SOURCE_SYSTEM = "system"

        /**
         * Sobe o relay. Retorna `false` quando o SO recusa o start imediatamente
         * (Android 12+ lança `ForegroundServiceStartNotAllowedException` de forma
         * síncrona quando o app está em background sem allowlist).
         */
        fun start(context: Context, source: String): Boolean {
            val intent = Intent(context, BackgroundRelayService::class.java)
                .setAction(RelayContract.ACTION_START)
                .putExtra(RelayContract.EXTRA_START_SOURCE, source)

            return try {
                ContextCompat.startForegroundService(context, intent)
                true
            } catch (exc: RuntimeException) {
                Log.e(TAG, "não foi possível iniciar o relay (source=$source)", exc)
                RelayController.resolveStart(false)
                false
            }
        }

        /**
         * Pede o encerramento. Retorna `true` quando o SO **aceitou** a ordem — a parada
         * efetiva é assíncrona (`onStartCommand`), por isso o retorno não é "já parou".
         */
        fun stop(context: Context): Boolean {
            val intent = Intent(context, BackgroundRelayService::class.java)
                .setAction(RelayContract.ACTION_STOP)
            return try {
                context.startService(intent)
                true
            } catch (exc: RuntimeException) {
                Log.e(TAG, "não foi possível pedir a parada do relay", exc)
                false
            }
        }

        fun isRunning(): Boolean = RelayController.isRunning()
    }
}
