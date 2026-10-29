import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geoptt/features/background/data/background_bridge.dart';

final backgroundBridgeProvider = Provider<BackgroundBridge>((ref) {
  return BackgroundBridge();
});