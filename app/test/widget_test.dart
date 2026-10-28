// This is a basic Flutter widget test for GeoPTT.
// Tests the diagnostic screen that exercises the native background bridge.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:geoptt/features/background/background.dart';
import 'package:geoptt/main.dart';

/// Mock PushMessaging para testes - evita inicialização do Firebase.
class MockPushMessaging extends PushMessaging {
  MockPushMessaging() : super(messaging: null);
}

void main() {
  testWidgets('GeoPTT diagnostic screen loads', (WidgetTester tester) async {
    // Build our app with mock dependencies to avoid Firebase initialization
    final mockBridge = BackgroundBridge(supported: false);
    final mockPush = MockPushMessaging();

    await tester.pumpWidget(
      GeoPttApp(bridge: mockBridge, push: mockPush),
    );

    // Verify the diagnostic screen loads
    expect(find.text('GeoPTT · diagnóstico'), findsOneWidget);
    expect(find.text('Ativar canal PTT'), findsOneWidget);
    expect(find.text('Desligar canal PTT'), findsOneWidget);
  });
}