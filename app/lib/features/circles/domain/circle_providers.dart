import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geoptt/features/circles/data/circle_repository.dart';
import 'package:geoptt/core/network/dio_client.dart';

final Provider<CircleRepository> circleRepositoryProvider = Provider<CircleRepository>((ref) {
  final dio = ref.watch(dioClientProvider);
  return CircleRepository(dioClient: dio);
});