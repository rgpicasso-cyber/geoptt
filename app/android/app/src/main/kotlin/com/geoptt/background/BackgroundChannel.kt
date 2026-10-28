package com.geoptt.background

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.util.Log
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * Ponte tipada entre o Dart e o ciclo de vida nativo (`docs/ARCHITECTURE.md` §4.1).
 *
 * Nenhuma regra de negócio mora aqui: só tradução de intenção da UI em chamadas ao SO.
 * O canal existe apenas enquanto a Activity está viva; quando a UI morre, o serviço
 * continua rodando e os eventos ficam retidos em [RelayController] até o próximo
 * `attach`.
 */
internal class BackgroundChannel(
    private val activity: Activity,
    messenger: BinaryMessenger,
) : MethodChannel.MethodCallHandler, EventChannel.StreamHandler {

    private val methodChannel = MethodChannel(messenger, RelayContract.METHOD_CHANNEL)
    private val eventChannel = EventChannel(messenger, RelayContract.EVENT_CHANNEL)
    private val mainHandler = Handler(Looper.getMainLooper())

    private var pendingStartResult: MethodChannel.Result? = null
    private var startObserver: ((Boolean) -> Unit)? = null
    private var notificationRequested: Boolean = false
    private var lastBatteryExemption: Boolean = false

    fun attach() {
        methodChannel.setMethodCallHandler(this)
        eventChannel.setStreamHandler(this)
        lastBatteryExemption = isIgnoringBatteryOptimizations()
    }

    fun detach() {
        methodChannel.setMethodCallHandler(null)
        eventChannel.setStreamHandler(null)
        RelayController.detachSink()

        // Um `startRelay` ainda pendente precisa de resposta: deixar a `Future` do Dart
        // aberta trava a UI (spinner eterno) quando a Activity é recriada. O helper também
        // cancela o timeout agendado — ele responderia um `Result` de canal já desregistrado.
        clearPendingStart(
            RelayContract.ERROR_ACTIVITY_DETACHED,
            "A tela foi encerrada antes de o serviço confirmar o start.",
        )
    }

    // ------------------------------------------------------------------ MethodChannel

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            METHOD_START_RELAY -> handleStartRelay(result)
            METHOD_STOP_RELAY -> handleStopRelay(result)
            METHOD_GET_STATUS -> result.success(statusPayload())
            METHOD_IS_IGNORING_BATTERY -> result.success(isIgnoringBatteryOptimizations())
            METHOD_REQUEST_IGNORE_BATTERY -> requestIgnoreBatteryOptimizations(result)
            METHOD_REQUEST_NOTIFICATION -> result.success(
                mapOf(KEY_STATUS to ensureNotificationPermission()),
            )
            METHOD_OPEN_NOTIFICATION_SETTINGS -> openNotificationSettings(result)
            METHOD_CONSUME_WAKEUP -> result.success(RelayController.consumePendingWakeup())
            else -> result.notImplemented()
        }
    }

    private fun handleStartRelay(result: MethodChannel.Result) {
        // A intenção do usuário é registrada antes de qualquer coisa: se o app morrer no
        // meio, o boot receiver ainda sabe que o modo PTT estava ativo.
        RelayPreferences(activity).relayEnabled = true
        val notificationStatus = ensureNotificationPermission()

        if (RelayController.isRunning()) {
            result.success(startPayload(notificationStatus))
            return
        }

        // Um pedido anterior ainda pendente não pode simplesmente ser descartado: a
        // `Future` correspondente no Dart ficaria órfã (o `Result` nunca respondido).
        clearPendingStart(
            RelayContract.ERROR_START_SUPERSEDED,
            "Um pedido de start mais recente substituiu este.",
        )
        pendingStartResult = result

        val observer: (Boolean) -> Unit = { started -> resolvePendingStart(started) }
        startObserver = observer
        RelayController.addStartObserver(observer)
        mainHandler.postDelayed(startTimeout, START_TIMEOUT_MS)

        // `startForegroundService` é assíncrono: a resposta sai quando o serviço
        // realmente entra em foreground (ou quando o SO recusa).
        if (!BackgroundRelayService.start(activity, RelayContract.SOURCE_UI)) {
            resolvePendingStart(false)
        }
    }

    private fun handleStopRelay(result: MethodChannel.Result) {
        RelayPreferences(activity).relayEnabled = false
        // O retorno diz se o SO **aceitou** a ordem de parada — a parada efetiva é
        // assíncrona. Reportar `stopped: true` sempre seria mentir para a UI quando o
        // `startService` falha (app em restrição de background, por exemplo).
        val accepted = BackgroundRelayService.stop(activity)
        result.success(mapOf(KEY_STOPPED to accepted))
    }

    private fun requestIgnoreBatteryOptimizations(result: MethodChannel.Result) {
        if (isIgnoringBatteryOptimizations()) {
            result.success(mapOf(KEY_REQUESTED to false, KEY_ALREADY_GRANTED to true))
            return
        }

        val direct = Intent(
            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
            Uri.parse("package:${activity.packageName}"),
        )
        try {
            activity.startActivity(direct)
            result.success(mapOf(KEY_REQUESTED to true, KEY_ALREADY_GRANTED to false))
            return
        } catch (exc: ActivityNotFoundException) {
            Log.w(TAG, "fabricante sem ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS; usando fallback")
        }

        try {
            activity.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            result.success(mapOf(KEY_REQUESTED to true, KEY_ALREADY_GRANTED to false))
        } catch (exc: ActivityNotFoundException) {
            result.error(
                RelayContract.ERROR_UNSUPPORTED,
                "Este aparelho não expõe a tela de isenção de bateria.",
                null,
            )
        }
    }

    private fun openNotificationSettings(result: MethodChannel.Result) {
        val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, activity.packageName)
        try {
            activity.startActivity(intent)
            result.success(null)
        } catch (exc: ActivityNotFoundException) {
            result.error(
                RelayContract.ERROR_UNSUPPORTED,
                "Este aparelho não expõe as configurações de notificação.",
                null,
            )
        }
    }

    // ------------------------------------------------------------------ resolução do start

    private val startTimeout = Runnable { resolvePendingStart(false) }

    /**
     * Abandona o start pendente respondendo erro.
     *
     * Só é chamado na main thread (Activity `detach` e `onMethodCall`). Não usar em
     * `resolvePendingStart`: lá a resposta de sucesso é que fecha o ciclo.
     */
    private fun clearPendingStart(code: String, message: String) {
        mainHandler.removeCallbacks(startTimeout)

        startObserver?.let(RelayController::removeStartObserver)
        startObserver = null

        val result = pendingStartResult ?: return
        pendingStartResult = null
        try {
            result.error(code, message, null)
        } catch (exc: RuntimeException) {
            // `Result` já respondido (canal morto) não pode derrubar a Activity.
            Log.w(TAG, "não foi possível responder o start pendente", exc)
        }
    }

    /**
     * Pode ser chamado de qualquer thread (o serviço roda na main, mas o handler de FCM
     * roda em background): a resposta do `MethodChannel` **precisa** sair na main thread.
     */
    private fun resolvePendingStart(started: Boolean) {
        mainHandler.post {
            mainHandler.removeCallbacks(startTimeout)

            startObserver?.let(RelayController::removeStartObserver)
            startObserver = null

            val result = pendingStartResult ?: return@post
            pendingStartResult = null

            if (started) {
                result.success(startPayload(currentNotificationStatus()))
            } else {
                result.error(
                    RelayContract.ERROR_RELAY_START_DENIED,
                    "O Android recusou o foreground service; verifique a isenção de bateria.",
                    null,
                )
            }
        }
    }

    private fun startPayload(notificationStatus: String): Map<String, Any?> = mapOf(
        KEY_STARTED to true,
        RelayContract.KEY_FOREGROUND_TYPES to RelayController.currentForegroundTypes(),
        KEY_NOTIFICATION_PERMISSION to notificationStatus,
    )

    private fun statusPayload(): Map<String, Any?> = mapOf(
        KEY_RUNNING to RelayController.isRunning(),
        KEY_ENABLED to RelayPreferences(activity).relayEnabled,
        KEY_IGNORING_BATTERY to isIgnoringBatteryOptimizations(),
        KEY_SDK_INT to Build.VERSION.SDK_INT,
        KEY_MANUFACTURER to Build.MANUFACTURER,
        RelayContract.KEY_FOREGROUND_TYPES to RelayController.currentForegroundTypes(),
        KEY_NOTIFICATION_PERMISSION to currentNotificationStatus(),
    )

    // ------------------------------------------------------------------ permissões / bateria

    private fun isIgnoringBatteryOptimizations(): Boolean {
        val powerManager = activity.getSystemService(Context.POWER_SERVICE) as? PowerManager
            ?: return false
        return powerManager.isIgnoringBatteryOptimizations(activity.packageName)
    }

    private fun currentNotificationStatus(): String {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return STATUS_GRANTED
        val granted = ContextCompat.checkSelfPermission(
            activity,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
        return if (granted) STATUS_GRANTED else STATUS_DENIED
    }

    /**
     * Pede `POST_NOTIFICATIONS` no máximo uma vez por sessão: insistir a cada start do
     * relay é hostil e o Android já não mostra o diálogo depois da segunda negativa.
     */
    private fun ensureNotificationPermission(): String {
        val status = currentNotificationStatus()
        if (status == STATUS_GRANTED) return status
        if (notificationRequested) return STATUS_DENIED

        notificationRequested = true
        ActivityCompat.requestPermissions(
            activity,
            arrayOf(Manifest.permission.POST_NOTIFICATIONS),
            REQUEST_CODE_NOTIFICATIONS,
        )
        return STATUS_REQUESTED
    }

    /** Retorna `true` quando consumiu o resultado. */
    fun onRequestPermissionsResult(requestCode: Int, grantResults: IntArray): Boolean {
        if (requestCode != REQUEST_CODE_NOTIFICATIONS) return false

        val granted = grantResults.isNotEmpty() &&
            grantResults[0] == PackageManager.PERMISSION_GRANTED
        RelayController.emit(
            mapOf(
                RelayContract.KEY_EVENT to RelayContract.EVENT_NOTIFICATION_PERMISSION,
                RelayContract.KEY_GRANTED to granted,
            ),
        )
        return true
    }

    /** Chamado no `onResume`: detecta que o usuário voltou da tela de isenção. */
    fun onActivityResumed() {
        val ignoring = isIgnoringBatteryOptimizations()
        if (ignoring == lastBatteryExemption) return

        lastBatteryExemption = ignoring
        RelayController.emit(
            mapOf(
                RelayContract.KEY_EVENT to RelayContract.EVENT_BATTERY_EXEMPTION,
                KEY_IGNORING_BATTERY to ignoring,
            ),
        )
    }

    // ------------------------------------------------------------------ EventChannel

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        RelayController.attachSink(events)
    }

    override fun onCancel(arguments: Any?) {
        RelayController.detachSink()
    }

    private companion object {
        private const val TAG = "GeoPttChannel"

        private const val METHOD_START_RELAY = "startRelay"
        private const val METHOD_STOP_RELAY = "stopRelay"
        private const val METHOD_GET_STATUS = "getStatus"
        private const val METHOD_IS_IGNORING_BATTERY = "isIgnoringBatteryOptimizations"
        private const val METHOD_REQUEST_IGNORE_BATTERY = "requestIgnoreBatteryOptimizations"
        private const val METHOD_REQUEST_NOTIFICATION = "requestNotificationPermission"
        private const val METHOD_OPEN_NOTIFICATION_SETTINGS = "openNotificationSettings"
        private const val METHOD_CONSUME_WAKEUP = "consumePendingWakeup"

        private const val KEY_STARTED = "started"
        private const val KEY_STOPPED = "stopped"
        private const val KEY_RUNNING = "running"
        private const val KEY_ENABLED = "enabled"
        private const val KEY_IGNORING_BATTERY = "ignoringBatteryOptimizations"
        private const val KEY_SDK_INT = "sdkInt"
        private const val KEY_MANUFACTURER = "manufacturer"
        private const val KEY_NOTIFICATION_PERMISSION = "notificationPermission"
        private const val KEY_REQUESTED = "requested"
        private const val KEY_ALREADY_GRANTED = "alreadyGranted"
        private const val KEY_STATUS = "status"

        private const val STATUS_GRANTED = "granted"
        private const val STATUS_DENIED = "denied"
        private const val STATUS_REQUESTED = "requested"

        private const val REQUEST_CODE_NOTIFICATIONS = 4104
        private const val START_TIMEOUT_MS = 5_000L
    }
}
