import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:geoptt/features/background/background.dart';

/// Contrato Dart ↔ Kotlin do relay (`docs/ARCHITECTURE.md` §4.1).
///
/// Se um nome de método ou de chave mudar no Kotlin sem mudar aqui, estes testes
/// continuam passando (eles mockam o canal) — o que eles protegem é o **parsing**:
/// payload inesperado deve virar erro tipado, nunca `dynamic` silencioso.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const MethodChannel channel = MethodChannel(BackgroundBridge.methodChannelName);
  final List<MethodCall> calls = <MethodCall>[];

  BackgroundBridge buildBridge() => BackgroundBridge(supported: true);

  void mockHandler(Future<Object?> Function(MethodCall call) handler) {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (MethodCall call) {
          calls.add(call);
          return handler(call);
        });
  }

  setUp(calls.clear);

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  group('startRelay', () {
    test('envia o método e converte o resultado', () async {
      mockHandler((MethodCall call) async => <Object?, Object?>{
        'started': true,
        'foregroundTypes': <Object?>['mediaPlayback', 'location'],
        'notificationPermission': 'granted',
      });

      final RelayStartResult result = await buildBridge().startRelay();

      expect(calls.single.method, 'startRelay');
      expect(result.started, isTrue);
      expect(result.foregroundTypes, <String>['mediaPlayback', 'location']);
      expect(result.notificationPermission, NotificationPermissionStatus.granted);
    });

    test('traduz PlatformException em erro tipado', () async {
      mockHandler((MethodCall call) async {
        throw PlatformException(
          code: 'RELAY_START_DENIED',
          message: 'recusado pelo SO',
        );
      });

      expect(
        buildBridge().startRelay,
        throwsA(
          isA<BackgroundBridgeException>().having(
            (BackgroundBridgeException e) => e.code,
            'code',
            'RELAY_START_DENIED',
          ),
        ),
      );
    });
  });

  group('getStatus', () {
    test('converte todos os campos', () async {
      mockHandler((MethodCall call) async => <Object?, Object?>{
        'running': true,
        'enabled': true,
        'ignoringBatteryOptimizations': false,
        'foregroundTypes': <Object?>['mediaPlayback', 'location'],
        'notificationPermission': 'denied',
        'sdkInt': 34,
        'manufacturer': 'Xiaomi',
      });

      final RelayStatus status = await buildBridge().getStatus();

      expect(calls.single.method, 'getStatus');
      expect(status.running, isTrue);
      expect(status.enabled, isTrue);
      expect(status.ignoringBatteryOptimizations, isFalse);
      expect(status.canSpeakInBackground, isFalse);
      expect(status.notificationPermission, NotificationPermissionStatus.denied);
      expect(status.sdkInt, 34);
      expect(status.manufacturer, 'Xiaomi');
    });

    test('rejeita payload sem campos obrigatórios', () async {
      mockHandler((MethodCall call) async => <Object?, Object?>{'running': true});

      expect(
        buildBridge().getStatus,
        throwsA(
          isA<BackgroundBridgeException>().having(
            (BackgroundBridgeException e) => e.code,
            'code',
            'CONTRACT_VIOLATION',
          ),
        ),
      );
    });

    test('resposta vazia vira SERVICE_UNAVAILABLE', () async {
      mockHandler((MethodCall call) async => null);

      expect(
        buildBridge().getStatus,
        throwsA(
          isA<BackgroundBridgeException>().having(
            (BackgroundBridgeException e) => e.code,
            'code',
            'SERVICE_UNAVAILABLE',
          ),
        ),
      );
    });

    test('resposta que não é Map vira CONTRACT_VIOLATION', () async {
      mockHandler((MethodCall call) async => 'texto inesperado');

      expect(
        buildBridge().getStatus,
        throwsA(
          isA<BackgroundBridgeException>().having(
            (BackgroundBridgeException e) => e.code,
            'code',
            'CONTRACT_VIOLATION',
          ),
        ),
      );
    });

    test('aceita microfone concedido', () async {
      mockHandler((MethodCall call) async => <Object?, Object?>{
        'running': true,
        'enabled': true,
        'ignoringBatteryOptimizations': true,
        'foregroundTypes': <Object?>['microphone', 'location', 'mediaPlayback'],
        'notificationPermission': 'granted',
        'sdkInt': 33,
        'manufacturer': 'samsung',
      });

      final RelayStatus status = await buildBridge().getStatus();

      expect(status.canSpeakInBackground, isTrue);
    });
  });

  group('stopRelay', () {
    test('envia o método e devolve a aceitação do SO', () async {
      mockHandler((MethodCall call) async => <Object?, Object?>{'stopped': true});

      expect(await buildBridge().stopRelay(), isTrue);
      expect(calls.single.method, 'stopRelay');
    });

    test('parada recusada pelo SO vira false', () async {
      mockHandler((MethodCall call) async => <Object?, Object?>{'stopped': false});

      expect(await buildBridge().stopRelay(), isFalse);
    });
  });

  group('consumePendingWakeup', () {
    test('retorna null quando não há wake-up', () async {
      mockHandler((MethodCall call) async => null);

      expect(await buildBridge().consumePendingWakeup(), isNull);
    });

    test('converte o mapa em evento tipado', () async {
      mockHandler(
        (MethodCall call) async => <Object?, Object?>{
          'channelId': '8b6f1a2c-3d4e-4f50-9a6b-7c8d9e0f1a2b',
          'senderId': '11111111-2222-4333-8444-555555555555',
          'callId': null,
          'timestampSeconds': 1730000000,
          'protocolVersion': 1,
          'source': 'fcm',
        },
      );

      final PttWakeupEvent? wakeup = await buildBridge().consumePendingWakeup();

      expect(wakeup, isNotNull);
      expect(wakeup!.source, RelayStartSource.fcm);
      expect(wakeup.timestampSeconds, 1730000000);
      expect(wakeup.callId, isNull);
    });
  });

  group('bateria e notificação', () {
    test('isIgnoringBatteryOptimizations devolve bool do canal', () async {
      mockHandler((MethodCall call) async => true);

      expect(await buildBridge().isIgnoringBatteryOptimizations(), isTrue);
    });

    test('requestIgnoreBatteryOptimizations converte o resultado', () async {
      mockHandler(
        (MethodCall call) async => <Object?, Object?>{
          'requested': true,
          'alreadyGranted': false,
        },
      );

      final BatteryExemptionRequest request =
          await buildBridge().requestIgnoreBatteryOptimizations();

      expect(request.requested, isTrue);
      expect(request.alreadyGranted, isFalse);
    });

    test('requestNotificationPermission converte o status', () async {
      mockHandler(
        (MethodCall call) async => <Object?, Object?>{'status': 'requested'},
      );

      expect(
        await buildBridge().requestNotificationPermission(),
        NotificationPermissionStatus.requested,
      );
    });
  });

  group('plataforma sem suporte', () {
    test('métodos lançam UNSUPPORTED fora do Android', () async {
      final BackgroundBridge bridge = BackgroundBridge(supported: false);

      expect(bridge.isSupported, isFalse);
      expect(
        bridge.startRelay,
        throwsA(
          isA<BackgroundBridgeException>().having(
            (BackgroundBridgeException e) => e.code,
            'code',
            'UNSUPPORTED',
          ),
        ),
      );
    });

    test('canal sem handler nativo lança UNSUPPORTED', () async {
      // Sem mock registrado o messenger devolve `null` e o `MethodChannel` lança
      // `MissingPluginException` — o cenário real de um build sem o Kotlin do relay.
      expect(
        buildBridge().getStatus,
        throwsA(
          isA<BackgroundBridgeException>().having(
            (BackgroundBridgeException e) => e.code,
            'code',
            'UNSUPPORTED',
          ),
        ),
      );
    });
  });
}
