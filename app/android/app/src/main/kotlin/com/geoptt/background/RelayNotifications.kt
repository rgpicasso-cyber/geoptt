package com.geoptt.background

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.geoptt.MainActivity
import com.geoptt.R

/**
 * Notificação persistente do canal PTT.
 *
 * Regras aplicadas:
 *  * canal dedicado `geoptt_relay` com importância `LOW` — o usuário precisa ver que o
 *    microfone está ativo, mas não pode ser interrompido por som a cada reconexão;
 *  * `setOngoing(true)` — swipe não remove a notificação enquanto o serviço roda;
 *  * `FOREGROUND_SERVICE_IMMEDIATE` (API 31+) — a notificação aparece imediatamente
 *    após o swipe-away, em vez dos ~10 s de atraso padrão do Android 12+.
 */
internal object RelayNotifications {

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(RelayContract.NOTIFICATION_CHANNEL_ID) != null) return

        val channel = NotificationChannel(
            RelayContract.NOTIFICATION_CHANNEL_ID,
            context.getString(R.string.relay_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = context.getString(R.string.relay_channel_description)
            setShowBadge(false)
            enableVibration(false)
            setSound(null, null)
        }
        manager.createNotificationChannel(channel)
    }

    fun build(context: Context, contentText: String): Notification {
        val stopIntent = PendingIntent.getService(
            context,
            REQUEST_CODE_STOP,
            Intent(context, BackgroundRelayService::class.java)
                .setAction(RelayContract.ACTION_STOP),
            pendingIntentFlags(),
        )

        val openIntent = PendingIntent.getActivity(
            context,
            REQUEST_CODE_OPEN,
            Intent(context, MainActivity::class.java)
                .setAction(Intent.ACTION_MAIN)
                .addCategory(Intent.CATEGORY_LAUNCHER)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            pendingIntentFlags(),
        )

        return NotificationCompat.Builder(context, RelayContract.NOTIFICATION_CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_ptt)
            .setContentTitle(context.getString(R.string.relay_notification_title))
            .setContentText(contentText)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .setSilent(true)
            .setShowWhen(false)
            .setOnlyAlertOnce(true)
            .setContentIntent(openIntent)
            .addAction(
                0,
                context.getString(R.string.relay_notification_stop),
                stopIntent,
            )
            .apply {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
                }
            }
            .build()
    }

    private fun pendingIntentFlags(): Int =
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE

    private const val REQUEST_CODE_STOP = 4102
    private const val REQUEST_CODE_OPEN = 4103
}
