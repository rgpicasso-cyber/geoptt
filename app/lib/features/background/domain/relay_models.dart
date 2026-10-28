import 'package:flutter/foundation.dart';

import 'platform_map.dart';

/// Permissão de notificação (Android 13+) — mapeada do nativo.
enum NotificationPermissionStatus {
  granted,
  denied,
  requested,
  unknown;

  static NotificationPermissionStatus fromWire(String? value) => switch (value) {
    'granted' => NotificationPermissionStatus.granted,
    'denied' => NotificationPermissionStatus.denied,
    'requested' => NotificationPermissionStatus.requested,
    _ => NotificationPermissionStatus.unknown,
  };
}

/// Snapshot do estado do relay nativo (`MethodChannel#getStatus`).
@immutable
class RelayStatus {
  const RelayStatus({
    required this.running,
    required this.enabled,
    required this.ignoringBatteryOptimizations,
    required this.foregroundTypes,
    required this.notificationPermission,
    required this.sdkInt,
    required this.manufacturer,
  });

  factory RelayStatus.fromMap(Map<Object?, Object?> map) => RelayStatus(
    running: map.requireBool('running'),
    enabled: map.requireBool('enabled'),
    ignoringBatteryOptimizations: map.requireBool('ignoringBatteryOptimizations'),
    foregroundTypes: map.stringList('foregroundTypes'),
    notificationPermission: NotificationPermissionStatus.fromWire(
      map.stringOrNull('notificationPermission'),
    ),
    sdkInt: map.intOr('sdkInt', fallback: 0),
    manufacturer: map.stringOrNull('manufacturer') ?? 'desconhecido',
  );

  /// `true` quando o serviço está em foreground neste momento.
  final bool running;

  /// `true` quando o usuário ativou o modo PTT (persistido; sobrevive a reboot).
  final bool enabled;

  final bool ignoringBatteryOptimizations;

  /// Tipos efetivamente concedidos pelo SO: `mediaPlayback`, `location`, `microphone`.
  final List<String> foregroundTypes;

  final NotificationPermissionStatus notificationPermission;
  final int sdkInt;
  final String manufacturer;

  /// Receber áudio não exige microfone; **falar** com o app fechado, sim.
  bool get canSpeakInBackground => foregroundTypes.contains('microphone');

  bool get isDegraded => running && foregroundTypes.isEmpty;
}

/// Resultado de `startRelay` — só resolve depois que o serviço realmente subiu.
@immutable
class RelayStartResult {
  const RelayStartResult({
    required this.started,
    required this.foregroundTypes,
    required this.notificationPermission,
  });

  factory RelayStartResult.fromMap(Map<Object?, Object?> map) => RelayStartResult(
    started: map.requireBool('started'),
    foregroundTypes: map.stringList('foregroundTypes'),
    notificationPermission: NotificationPermissionStatus.fromWire(
      map.stringOrNull('notificationPermission'),
    ),
  );

  final bool started;
  final List<String> foregroundTypes;
  final NotificationPermissionStatus notificationPermission;
}

/// Resultado de `requestIgnoreBatteryOptimizations`.
@immutable
class BatteryExemptionRequest {
  const BatteryExemptionRequest({
    required this.requested,
    required this.alreadyGranted,
  });

  factory BatteryExemptionRequest.fromMap(Map<Object?, Object?> map) =>
      BatteryExemptionRequest(
        requested: map.requireBool('requested'),
        alreadyGranted: map.requireBool('alreadyGranted'),
      );

  /// `true` quando a tela de isenção foi aberta (o usuário ainda pode recusar).
  final bool requested;

  /// `true` quando o app já estava isento — nada foi aberto.
  final bool alreadyGranted;
}
