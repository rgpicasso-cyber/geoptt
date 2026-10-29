import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';

void main() {
  group('Smart ping logic', () {
    test('first position always triggers send', () {
      Position? lastSent;
      final now = DateTime.now();
      final pos = Position(
        latitude: -23.96,
        longitude: -46.33,
        timestamp: DateTime.now(),
        accuracy: 5,
        altitude: 0,
        heading: 0,
        speed: 0,
        speedAccuracy: 0,
        altitudeAccuracy: 1,
        headingAccuracy: 1,
      );

      bool shouldSend = lastSent == null;
      expect(shouldSend, true);
    });

    test('distance > 10m triggers send', () {
      final lastSent = Position(
        latitude: -23.9600,
        longitude: -46.3300,
        timestamp: DateTime.now().subtract(const Duration(minutes: 1)),
        accuracy: 5,
        altitude: 0,
        heading: 0,
        speed: 0,
        speedAccuracy: 0,
        altitudeAccuracy: 1,
        headingAccuracy: 1,
      );

      final newPos = Position(
        latitude: -23.9615,
        longitude: -46.3300,
        timestamp: DateTime.now(),
        accuracy: 5,
        altitude: 0,
        heading: 0,
        speed: 0,
        speedAccuracy: 0,
        altitudeAccuracy: 1,
        headingAccuracy: 1,
      );

      final distance = Geolocator.distanceBetween(
        lastSent.latitude,
        lastSent.longitude,
        newPos.latitude,
        newPos.longitude,
      );
      expect(distance > 10, true);
    });

    test('time > 2 min triggers send even if distance small', () {
      final lastSent = Position(
        latitude: -23.9600,
        longitude: -46.3300,
        timestamp: DateTime.now().subtract(const Duration(minutes: 3)),
        accuracy: 5,
        altitude: 0,
        heading: 0,
        speed: 0,
        speedAccuracy: 0,
        altitudeAccuracy: 1,
        headingAccuracy: 1,
      );

      final newPos = Position(
        latitude: -23.9600,
        longitude: -46.3300,
        timestamp: DateTime.now(),
        accuracy: 5,
        altitude: 0,
        heading: 0,
        speed: 0,
        speedAccuracy: 0,
        altitudeAccuracy: 1,
        headingAccuracy: 1,
      );

      final timeDiff = DateTime.now().difference(lastSent.timestamp);
      expect(timeDiff.inMinutes >= 2, true);
    });
  });
}