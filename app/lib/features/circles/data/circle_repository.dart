import 'package:dio/dio.dart';
import 'package:geoptt/core/network/dio_client.dart';

/// Simple data classes for circles
class Circle {
  final String uuid;
  final String name;
  final String ownerUuid;
  final DateTime createdAt;

  Circle({
    required this.uuid,
    required this.name,
    required this.ownerUuid,
    required this.createdAt,
  });

  factory Circle.fromJson(Map<String, dynamic> json) {
    return Circle(
      uuid: json['uuid'] as String,
      name: json['name'] as String,
      ownerUuid: json['owner_uuid'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}

class CircleMember {
  final String userUuid;
  final String displayName;
  final bool canSpeak;

  CircleMember({
    required this.userUuid,
    required this.displayName,
    required this.canSpeak,
  });

  factory CircleMember.fromJson(Map<String, dynamic> json) {
    return CircleMember(
      userUuid: json['user_uuid'] as String,
      displayName: json['display_name'] as String,
      canSpeak: json['can_speak'] as bool? ?? true,
    );
  }
}

/// Repository for circles API
class CircleRepository {
  CircleRepository({required DioClient dioClient}) : _dio = dioClient.dio;

  final Dio _dio;

  Future<List<Circle>> listMyCircles() async {
    final resp = await _dio.get<List<dynamic>>('/circles');
    return (resp.data ?? []).map((e) => Circle.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Circle> createCircle({required String name}) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/circles',
      data: {'name': name},
    );
    return Circle.fromJson(resp.data!);
  }

  Future<Circle> getCircle(String uuid) async {
    final resp = await _dio.get<Map<String, dynamic>>('/circles/$uuid');
    return Circle.fromJson(resp.data!);
  }

  Future<void> inviteMember({required String circleUuid, required String email}) async {
    await _dio.post('/circles/$circleUuid/invite', data: {'email': email});
  }

  Future<List<CircleMember>> listMembers(String circleUuid) async {
    final resp = await _dio.get<List<dynamic>>('/circles/$circleUuid/members');
    return (resp.data ?? []).map((e) => CircleMember.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<void> updateMemberPermission({required String circleUuid, required String userUuid, required bool canSpeak}) async {
    await _dio.patch('/circles/$circleUuid/members/$userUuid', data: {'can_speak': canSpeak});
  }

  Future<void> removeMember({required String circleUuid, required String userUuid}) async {
    await _dio.delete('/circles/$circleUuid/members/$userUuid');
  }
}