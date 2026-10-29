import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geoptt/features/map/presentation/map_page.dart';

void main() {
  testWidgets('MapPage renders without error', (WidgetTester tester) async {
    await tester.pumpWidget(
      const ProviderScope(
        child: MaterialApp(home: MapPage()),
      ),
    );

    // Should render without crash
    expect(find.byType(MapPage), findsOneWidget);
    expect(find.byType(FlutterMap), findsOneWidget);
  });
}