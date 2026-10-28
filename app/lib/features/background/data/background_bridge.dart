import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../domain/background_event.dart';
import '../domain/platform_map.dart';
import '../domain/relay_models.dart';

/// Erro tipado da ponte nativa.
///
/// Códigos estáveis (espelham `RelayContract.ERROR_*` no Kotlin):
/// `RELAY_START_DENIED`, `SERVICE_UNAVAILABLE`, `ACTIVITY_DETACHED`, `UNSUPPORTED`.
/// `CONTRACT_VIOLATION` é local ao Dart: o nativo respondeu algo que este cliente não
/// sabe ler (payload malformado ou canal de outra versão).
@immutable
class BackgroundBridgeException implements Exception {
  const BackgroundBridgeException(this.code, this.message);

  final String code;
  final String message;

  @override
  String toString() => 'BackgroundBridgeException($code): $message';
}

/// Ponte Dart ↔ nativo do relay (`docs/ARCHITECTURE.md` §4.1).
///
/// Nenhuma regra de negócio: só tradução tipada. As strings de método/evento existem
/// duplicadas aqui e em `RelayContract.kt` — os testes desta classe mockam o canal, logo
/// **não** detectam divergência de nome; o que eles protegem é o parsing. Renomear um
/// método no Kotlin exige renomear aqui e no teste.
class BackgroundBridge {
  BackgroundBridge({
    MethodChannel? methodChannel,
    EventChannel? eventChannel,
    bool? supported,
  }) : _methodChannel = methodChannel ?? const MethodChannel(methodChannelName),
       _eventChannel = eventChannel ?? const EventChannel(eventChannelName),
       _supported =
           supported ?? (!kIsWeb && defaultTargetPlatform == TargetPlatform.android);

  static const String methodChannelName = 'geoptt/background';
  static const String eventChannelName = 'geoptt/background/events';

  final MethodChannel _methodChannel;
  final EventChannel _eventChannel;
  final bool _supported;

  Stream<BackgroundEvent>? _events;

  /// Falso em iOS/web — a Fase 3.2 cobre o lado iOS com PushKit.
  bool get isSupported => _supported;

  /// Eventos do serviço. Broadcast: pode haver mais de um listener (UI + debug).
  Stream<BackgroundEvent> get events => _events ??= _eventChannel
      .receiveBroadcastStream()
      .map(_decodeEvent);

  // ------------------------------------------------------------------ relay

  /// Sobe o Foreground Service. Só completa quando o SO confirma (ou recusa).
  Future<RelayStartResult> startRelay() async {
    _requireAndroid();
    return _decode('startRelay', RelayStartResult.fromMap);
  }

  /// Para o serviço e desmarca `relay_enabled` (não religa no próximo boot).
  ///
  /// Retorna `true` quando o Android **aceitou** a ordem de parada — a parada efetiva é
  /// assíncrona (`onStartCommand`), então `true` não significa "já parou".
  Future<bool> stopRelay() async {
    _requireAndroid();
    final Object? raw = await _invokeRaw('stopRelay');
    if (raw is Map<Object?, Object?>) {
      final Object? stopped = raw['stopped'];
      return stopped is bool && stopped;
    }
    return false;
  }

  Future<RelayStatus> getStatus() async {
    _requireAndroid();
    return _decode('getStatus', RelayStatus.fromMap);
  }

  /// Drena o wake-up recebido enquanto a UI estava morta (ou `null`).
  Future<PttWakeupEvent?> consumePendingWakeup() async {
    _requireAndroid();
    final Object? raw = await _invokeRaw('consumePendingWakeup');
    if (raw == null) return null;

    if (raw is! Map<Object?, Object?>) {
      throw BackgroundBridgeException(
        'CONTRACT_VIOLATION',
        'consumePendingWakeup devolveu ${raw.runtimeType} em vez de Map',
      );
    }
    try {
      // O método devolve só os campos do wake-up (sem a chave `event`), então o parsing
      // vai direto no modelo — não passa pelo `BackgroundEvent.fromMap`.
      return PttWakeupEvent.fromMap(raw);
    } on FormatException catch (error) {
      throw BackgroundBridgeException(
        'CONTRACT_VIOLATION',
        'consumePendingWakeup: ${error.message}',
      );
    }
  }

  // ------------------------------------------------------------------ bateria / notificação

  Future<bool> isIgnoringBatteryOptimizations() async {
    _requireAndroid();
    final Object? value = await _invokeRaw('isIgnoringBatteryOptimizations');
    return value is bool ? value : false;
  }

  /// Abre a tela de isenção de bateria. O usuário ainda pode recusar.
  Future<BatteryExemptionRequest> requestIgnoreBatteryOptimizations() async {
    _requireAndroid();
    return _decode('requestIgnoreBatteryOptimizations', BatteryExemptionRequest.fromMap);
  }

  Future<NotificationPermissionStatus> requestNotificationPermission() async {
    _requireAndroid();
    return _decode('requestNotificationPermission', (Map<Object?, Object?> map) {
      return NotificationPermissionStatus.fromWire(map.stringOrNull('status'));
    });
  }

  Future<void> openNotificationSettings() async {
    _requireAndroid();
    await _invokeRaw('openNotificationSettings');
  }

  // ------------------------------------------------------------------ infraestrutura

  void dispose() {
    _events = null;
  }

  void _requireAndroid() {
    if (_supported) return;
    throw const BackgroundBridgeException(
      'UNSUPPORTED',
      'Relay em segundo plano ainda não é suportado nesta plataforma.',
    );
  }

  /// Invoca, exige `Map` e converte. Qualquer desvio vira [BackgroundBridgeException]:
  /// resposta vazia é `SERVICE_UNAVAILABLE`, tipo errado ou campo faltando é
  /// `CONTRACT_VIOLATION` — nunca um `FormatException` cru vazando para a UI nem um
  /// `Map` vazio que passaria por "sem dados".
  Future<T> _decode<T>(
    String method,
    T Function(Map<Object?, Object?>) parse,
  ) async {
    final Object? raw = await _invokeRaw(method);
    if (raw == null) {
      throw BackgroundBridgeException('SERVICE_UNAVAILABLE', 'resposta vazia de $method');
    }
    if (raw is! Map<Object?, Object?>) {
      throw BackgroundBridgeException(
        'CONTRACT_VIOLATION',
        '$method devolveu ${raw.runtimeType} em vez de Map',
      );
    }
    try {
      return parse(raw);
    } on FormatException catch (error) {
      throw BackgroundBridgeException('CONTRACT_VIOLATION', '$method: ${error.message}');
    }
  }

  /// Um evento malformado **não** derruba o stream: viraria perda de wake-up.
  static BackgroundEvent _decodeEvent(Object? raw) {
    if (raw is! Map<Object?, Object?>) {
      return UnknownBackgroundEvent(<Object?, Object?>{'raw': raw});
    }
    return BackgroundEvent.fromMap(raw);
  }

  Future<Object?> _invokeRaw(String method) async {
    try {
      return await _methodChannel.invokeMethod<Object?>(method);
    } on MissingPluginException {
      throw const BackgroundBridgeException(
        'UNSUPPORTED',
        'Nenhum handler nativo registrado para o canal.',
      );
    } on PlatformException catch (error) {
      throw BackgroundBridgeException(error.code, error.message ?? 'erro nativo');
    }
  }
}
