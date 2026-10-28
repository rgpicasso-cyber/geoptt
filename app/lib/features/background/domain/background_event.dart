import 'package:flutter/foundation.dart';

import 'platform_map.dart';

/// Origem de um start do relay — espelha `RelayContract.SOURCE_*` no Kotlin.
enum RelayStartSource {
  ui,
  fcm,
  boot,
  restart,
  unknown;

  static RelayStartSource fromWire(String? value) => switch (value) {
    'ui' => RelayStartSource.ui,
    'fcm' => RelayStartSource.fcm,
    'boot' => RelayStartSource.boot,
    'restart' => RelayStartSource.restart,
    _ => RelayStartSource.unknown,
  };
}

/// Eventos do `EventChannel("geoptt/background/events")`.
///
/// `sealed` de propósito: um `switch` sobre [BackgroundEvent] sem `default` falha em
/// tempo de compilação quando um evento novo aparece no Kotlin — é o que impede o Dart
/// de ignorar silenciosamente um wake-up.
@immutable
sealed class BackgroundEvent {
  const BackgroundEvent();

  /// Converte o mapa cru do canal. Payload inesperado **não** derruba o stream:
  /// vira [UnknownBackgroundEvent] e é reportado como aviso.
  factory BackgroundEvent.fromMap(Map<Object?, Object?> map) {
    try {
      final String? name = map.stringOrNull('event');
      if (name == null) return UnknownBackgroundEvent(map);

      return switch (name) {
        'wakeup' => PttWakeupEvent.fromMap(map),
        'relayStarted' => RelayStartedEvent.fromMap(map),
        'relayStopped' => RelayStoppedEvent.fromMap(map),
        'relayStartDenied' => RelayStartDeniedEvent.fromMap(map),
        'batteryExemptionChanged' => BatteryExemptionChangedEvent.fromMap(map),
        'notificationPermission' => NotificationPermissionEvent.fromMap(map),
        _ => UnknownBackgroundEvent(map),
      };
    } on FormatException {
      return UnknownBackgroundEvent(map);
    }
  }
}

/// `PTT_WAKEUP` recebido com a UI possivelmente morta.
final class PttWakeupEvent extends BackgroundEvent {
  const PttWakeupEvent({
    required this.channelId,
    required this.senderId,
    required this.callId,
    required this.timestampSeconds,
    required this.protocolVersion,
    required this.source,
  });

  factory PttWakeupEvent.fromMap(Map<Object?, Object?> map) => PttWakeupEvent(
    channelId: map.requireString('channelId'),
    senderId: map.stringOrNull('senderId'),
    callId: map.stringOrNull('callId'),
    timestampSeconds: map.intOr('timestampSeconds', fallback: 0),
    protocolVersion: map.intOr('protocolVersion', fallback: 1),
    source: RelayStartSource.fromWire(map.stringOrNull('source')),
  );

  final String channelId;
  final String? senderId;
  final String? callId;
  final int timestampSeconds;
  final int protocolVersion;
  final RelayStartSource source;
}

/// O serviço entrou em foreground; [foregroundTypes] diz o que o SO autorizou.
final class RelayStartedEvent extends BackgroundEvent {
  const RelayStartedEvent({required this.foregroundTypes, required this.source});

  factory RelayStartedEvent.fromMap(Map<Object?, Object?> map) => RelayStartedEvent(
    foregroundTypes: map.stringList('foregroundTypes'),
    source: RelayStartSource.fromWire(map.stringOrNull('source')),
  );

  final List<String> foregroundTypes;
  final RelayStartSource source;
}

/// O serviço parou (ação do usuário, do sistema ou `onDestroy`).
final class RelayStoppedEvent extends BackgroundEvent {
  const RelayStoppedEvent({required this.source});

  factory RelayStoppedEvent.fromMap(Map<Object?, Object?> map) =>
      RelayStoppedEvent(source: map.stringOrNull('source') ?? 'desconhecido');

  final String source;
}

/// O Android recusou subir o foreground service (isenção de bateria ausente,
/// restrição de background start, etc.).
final class RelayStartDeniedEvent extends BackgroundEvent {
  const RelayStartDeniedEvent({required this.source});

  factory RelayStartDeniedEvent.fromMap(Map<Object?, Object?> map) =>
      RelayStartDeniedEvent(source: RelayStartSource.fromWire(map.stringOrNull('source')));

  final RelayStartSource source;
}

/// Usuário voltou da tela de isenção de bateria com o estado alterado.
final class BatteryExemptionChangedEvent extends BackgroundEvent {
  const BatteryExemptionChangedEvent({required this.ignoring});

  factory BatteryExemptionChangedEvent.fromMap(Map<Object?, Object?> map) =>
      BatteryExemptionChangedEvent(ignoring: map.requireBool('ignoringBatteryOptimizations'));

  final bool ignoring;
}

/// Resultado do diálogo de `POST_NOTIFICATIONS`.
final class NotificationPermissionEvent extends BackgroundEvent {
  const NotificationPermissionEvent({required this.granted});

  factory NotificationPermissionEvent.fromMap(Map<Object?, Object?> map) =>
      NotificationPermissionEvent(granted: map.requireBool('granted'));

  final bool granted;
}

/// Evento que este cliente ainda não conhece (versão nova do nativo, por exemplo).
final class UnknownBackgroundEvent extends BackgroundEvent {
  const UnknownBackgroundEvent(this.raw);

  final Map<Object?, Object?> raw;
}
