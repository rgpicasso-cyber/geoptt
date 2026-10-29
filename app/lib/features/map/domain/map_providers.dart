import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Simple data class for UI (kept for future use)
class LocationData {
  final double latitude;
  final double longitude;
  final int? batteryLevel;
  final DateTime timestamp;

  LocationData({
    required this.latitude,
    required this.longitude,
    this.batteryLevel,
    required this.timestamp,
  });
}