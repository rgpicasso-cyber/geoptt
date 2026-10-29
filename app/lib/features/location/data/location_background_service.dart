import 'dart:async';
import 'package:geolocator/geolocator.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:geoptt/core/database/app_database.dart';
import 'package:geoptt/core/network/dio_client.dart';
import 'package:geoptt/features/auth/domain/auth_state.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class LocationBackgroundService {
  LocationBackgroundService(this._db, this._dio, this._authRepo);

  final AppDatabase _db;
  final DioClient _dio;
  final AuthRepository _authRepo;

  StreamSubscription<Position>? _positionStream;
  Position? _lastSentPosition;
  DateTime? _lastSentTime;

  static const double _distanceThresholdMeters = 10.0;
  static const Duration _timeThreshold = Duration(minutes: 2);

  Future<void> start() async {
    // Request permissions
    final status = await Permission.locationAlways.request();
    if (!status.isGranted) {
      // fallback to when in use
      await Permission.locationWhenInUse.request();
    }

    // Configure location settings
    const locationSettings = LocationSettings(
      accuracy: LocationAccuracy.high,
      distanceFilter: 5, // get updates every 5 meters
    );

    _positionStream = Geolocator.getPositionStream(locationSettings: locationSettings).listen(_onPosition);
  }

  void _onPosition(Position position) {
    final now = DateTime.now();
    bool shouldSend = false;

    if (_lastSentPosition == null) {
      shouldSend = true;
    } else {
      final distance = Geolocator.distanceBetween(
        _lastSentPosition!.latitude,
        _lastSentPosition!.longitude,
        position.latitude,
        position.longitude,
      );
      final timeDiff = now.difference(_lastSentTime!);
      if (distance >= _distanceThresholdMeters || timeDiff >= _timeThreshold) {
        shouldSend = true;
      }
    }

    if (shouldSend) {
      _enqueueAndSend(position);
      _lastSentPosition = position;
      _lastSentTime = now;
    }
  }

  Future<void> _enqueueAndSend(Position position) async {
    // Get current user uuid from auth repo (simplified)
    final userUuid = await _authRepo.getCurrentUserUuid();
    if (userUuid == null) return;

    await _db.enqueueLocation(
      userUuid: userUuid,
      latitude: position.latitude,
      longitude: position.longitude,
      accuracy: position.accuracy,
      altitude: position.altitude,
      speed: position.speed,
      heading: position.heading,
      recordedAt: DateTime.fromMillisecondsSinceEpoch(position.timestamp.toInt()),
    );

    // Try to flush immediately if online
    await _flushQueue();
  }

  Future<void> _flushQueue() async {
    final unsynced = await _db.getUnsyncedLocations(limit: 100);
    if (unsynced.isEmpty) return;

    // Build payload for backend /location/batch
    final payload = {
      'points': unsynced.map((l) => {
        'lat': l.latitude,
        'lng': l.longitude,
        'accuracy': l.accuracy,
        'altitude': l.altitude,
        'speed': l.speed,
        'heading': l.heading,
        'recorded_at': l.recordedAt.toIso8601String(),
      }).toList(),
    };

    try {
      await _dio.post('/location/batch', data: payload);
      // mark synced
      await _db.markLocationsSynced(unsynced.map((e) => e.id).toList());
    } catch (_) {
      // keep in queue for later retry
    }
  }

  Future<void> stop() async {
    await _positionStream?.cancel();
  }
}

/// Riverpod provider for the background service
final locationBackgroundServiceProvider = Provider<LocationBackgroundService>((ref) {
  final db = ref.watch(appDatabaseProvider);
  final dio = ref.watch(dioClientProvider);
  final auth = ref.watch(authRepositoryProvider);
  return LocationBackgroundService(db, dio, auth);
});