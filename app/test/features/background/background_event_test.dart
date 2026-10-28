import 'package:flutter_test/flutter_test.dart';
import 'package:geoptt/features/background/background.dart';

/// Parsing dos eventos do `EventChannel`.
///
/// Regra: payload inesperado nunca derruba o stream — vira [UnknownBackgroundEvent].
/// Um wake-up perdido por `FormatException` seria uma chamada de voz perdida.
void main() {
  group('BackgroundEvent.fromMap', () {
    test('converte wakeup completo', () {
      final BackgroundEvent event = BackgroundEvent.fromMap(<Object?, Object?>{
        'event': 'wakeup',
        'channelId': '8b6f1a2c-3d4e-4f50-9a6b-7c8d9e0f1a2b',
        'senderId': '11111111-2222-4333-8444-555555555555',
        'callId': '99999999-8888-4777-8666-555555555555',
        'timestampSeconds': 1730000000,
        'protocolVersion': 1,
        'source': 'fcm',
      });

      expect(event, isA<PttWakeupEvent>());
      final PttWakeupEvent wakeup = event as PttWakeupEvent;
      expect(wakeup.channelId, '8b6f1a2c-3d4e-4f50-9a6b-7c8d9e0f1a2b');
      expect(wakeup.source, RelayStartSource.fcm);
      expect(wakeup.protocolVersion, 1);
    });

    test('wakeup sem channelId vira evento desconhecido', () {
      final BackgroundEvent event = BackgroundEvent.fromMap(<Object?, Object?>{
        'event': 'wakeup',
        'timestampSeconds': 1730000000,
      });

      expect(event, isA<UnknownBackgroundEvent>());
    });

    test('converte relayStarted com os tipos concedidos', () {
      final BackgroundEvent event = BackgroundEvent.fromMap(<Object?, Object?>{
        'event': 'relayStarted',
        'foregroundTypes': <Object?>['mediaPlayback', 'location'],
        'source': 'ui',
      });

      expect(event, isA<RelayStartedEvent>());
      final RelayStartedEvent started = event as RelayStartedEvent;
      expect(started.foregroundTypes, <String>['mediaPlayback', 'location']);
      expect(started.source, RelayStartSource.ui);
    });

    test('converte relayStartDenied', () {
      final BackgroundEvent event = BackgroundEvent.fromMap(<Object?, Object?>{
        'event': 'relayStartDenied',
        'source': 'boot',
      });

      expect(event, isA<RelayStartDeniedEvent>());
      expect((event as RelayStartDeniedEvent).source, RelayStartSource.boot);
    });

    test('converte batteryExemptionChanged', () {
      final BackgroundEvent event = BackgroundEvent.fromMap(<Object?, Object?>{
        'event': 'batteryExemptionChanged',
        'ignoringBatteryOptimizations': true,
      });

      expect(event, isA<BatteryExemptionChangedEvent>());
      expect((event as BatteryExemptionChangedEvent).ignoring, isTrue);
    });

    test('converte notificationPermission', () {
      final BackgroundEvent event = BackgroundEvent.fromMap(<Object?, Object?>{
        'event': 'notificationPermission',
        'granted': false,
      });

      expect(event, isA<NotificationPermissionEvent>());
      expect((event as NotificationPermissionEvent).granted, isFalse);
    });

    test('evento novo do nativo não derruba o stream', () {
      final BackgroundEvent event = BackgroundEvent.fromMap(<Object?, Object?>{
        'event': 'algoNovo',
        'payload': 42,
      });

      expect(event, isA<UnknownBackgroundEvent>());
      expect((event as UnknownBackgroundEvent).raw['event'], 'algoNovo');
    });

    test('mapa sem a chave event vira desconhecido', () {
      expect(
        BackgroundEvent.fromMap(const <Object?, Object?>{}),
        isA<UnknownBackgroundEvent>(),
      );
    });

    test('evento com campo de tipo errado vira desconhecido', () {
      final BackgroundEvent event = BackgroundEvent.fromMap(<Object?, Object?>{
        'event': 'notificationPermission',
        'granted': 'sim',
      });

      expect(event, isA<UnknownBackgroundEvent>());
    });
  });
}
