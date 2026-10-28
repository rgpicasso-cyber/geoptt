package com.geoptt

import com.geoptt.background.BackgroundChannel
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

/**
 * Activity única do app.
 *
 * Responsabilidade extra: hospedar o `MethodChannel`/`EventChannel` do relay
 * (`geoptt/background`) e encaminhar eventos de ciclo de vida que o Dart não consegue
 * observar sozinho (retorno da tela de isenção de bateria, resultado do diálogo de
 * `POST_NOTIFICATIONS`).
 */
class MainActivity : FlutterActivity() {

    private var backgroundChannel: BackgroundChannel? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        backgroundChannel = BackgroundChannel(
            activity = this,
            messenger = flutterEngine.dartExecutor.binaryMessenger,
        ).also { it.attach() }
    }

    override fun cleanUpFlutterEngine(flutterEngine: FlutterEngine) {
        backgroundChannel?.detach()
        backgroundChannel = null
        super.cleanUpFlutterEngine(flutterEngine)
    }

    override fun onResume() {
        super.onResume()
        // Detecta que o usuário concedeu a isenção e voltou para o app.
        backgroundChannel?.onActivityResumed()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        backgroundChannel?.onRequestPermissionsResult(requestCode, grantResults)
    }
}
