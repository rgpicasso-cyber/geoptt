import 'dart:io';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;

part 'app_database.g.dart';

/// -----------------------------------------------------------------------------
/// Tabelas
/// -----------------------------------------------------------------------------

class Users extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get uuid => text().withLength(min: 36, max: 36)(); // UUID string
  TextColumn get email => text()();
  TextColumn get displayName => text().nullable()();
  TextColumn get avatarUrl => text().nullable()();
  TextColumn get accessToken => text().nullable()();
  TextColumn get refreshToken => text().nullable()();
  DateTimeColumn get tokenExpiry => dateTime().nullable()();
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();
  DateTimeColumn get updatedAt => dateTime().withDefault(currentDateAndTime)();
}

class Circles extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get uuid => text().withLength(min: 36, max: 36)();
  TextColumn get name => text()();
  TextColumn get ownerUuid => text().withLength(min: 36, max: 36)(); // FK to Users.uuid
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();
  DateTimeColumn get updatedAt => dateTime().withDefault(currentDateAndTime)();
}

class CircleMembers extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get circleUuid => text().withLength(min: 36, max: 36)();
  TextColumn get userUuid => text().withLength(min: 36, max: 36)();
  BoolColumn get canSpeak => boolean().withDefault(const Constant(true))();
  DateTimeColumn get joinedAt => dateTime().withDefault(currentDateAndTime)();
}

class LocationQueue extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get userUuid => text().withLength(min: 36, max: 36)();
  RealColumn get latitude => real()();
  RealColumn get longitude => real()();
  RealColumn get accuracy => real().nullable()();
  RealColumn get altitude => real().nullable()();
  RealColumn get speed => real().nullable()();
  RealColumn get heading => real().nullable()();
  DateTimeColumn get recordedAt => dateTime()();
  BoolColumn get synced => boolean().withDefault(const Constant(false))();
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();
}

/// -----------------------------------------------------------------------------
/// Database
/// -----------------------------------------------------------------------------

@DriftDatabase(tables: [Users, Circles, CircleMembers, LocationQueue])
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(_openConnection());

  @override
  int get schemaVersion => 1;

  // ---------------------------------------------------------------------------
  // Users DAO helpers
  // ---------------------------------------------------------------------------
  Future<void> upsertUser({
    required String uuid,
    required String email,
    String? displayName,
    String? avatarUrl,
    String? accessToken,
    String? refreshToken,
    DateTime? tokenExpiry,
  }) async {
    await into(users).insertOnConflictUpdate(
      UsersCompanion.insert(
        uuid: uuid,
        email: email,
        displayName: Value(displayName),
        avatarUrl: Value(avatarUrl),
        accessToken: Value(accessToken),
        refreshToken: Value(refreshToken),
        tokenExpiry: Value(tokenExpiry),
        updatedAt: Value(DateTime.now()),
      ),
    );
  }

  Future<UserData?> getUserByUuid(String uuid) async {
    final query = select(users)..where((u) => u.uuid.equals(uuid));
    return await query.getSingleOrNull();
  }

  Future<void> clearAuthTokens(String uuid) async {
    await (update(users)..where((u) => u.uuid.equals(uuid))).write(
      UsersCompanion(
        accessToken: const Value.absent(),
        refreshToken: const Value.absent(),
        tokenExpiry: const Value.absent(),
        updatedAt: Value(DateTime.now()),
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Circles DAO helpers
  // ---------------------------------------------------------------------------
  Future<int> insertCircle({
    required String uuid,
    required String name,
    required String ownerUuid,
  }) async {
    return await into(circles).insert(
      CirclesCompanion.insert(
        uuid: uuid,
        name: name,
        ownerUuid: ownerUuid,
      ),
    );
  }

  Future<List<CircleData>> getAllCircles() async {
    return await select(circles).get();
  }

  Future<CircleData?> getCircleByUuid(String uuid) async {
    final q = select(circles)..where((c) => c.uuid.equals(uuid));
    return await q.getSingleOrNull();
  }

  // ---------------------------------------------------------------------------
  // CircleMembers
  // ---------------------------------------------------------------------------
  Future<void> addMember({
    required String circleUuid,
    required String userUuid,
    bool canSpeak = true,
  }) async {
    await into(circleMembers).insertOnConflictUpdate(
      CircleMembersCompanion.insert(
        circleUuid: circleUuid,
        userUuid: userUuid,
        canSpeak: Value(canSpeak),
      ),
    );
  }

  Future<List<CircleMemberData>> getMembersForCircle(String circleUuid) async {
    final q = select(circleMembers)..where((cm) => cm.circleUuid.equals(circleUuid));
    return await q.get();
  }

  // ---------------------------------------------------------------------------
  // LocationQueue
  // ---------------------------------------------------------------------------
  Future<int> enqueueLocation({
    required String userUuid,
    required double latitude,
    required double longitude,
    double? accuracy,
    double? altitude,
    double? speed,
    double? heading,
    required DateTime recordedAt,
  }) async {
    return await into(locationQueue).insert(
      LocationQueueCompanion.insert(
        userUuid: userUuid,
        latitude: latitude,
        longitude: longitude,
        accuracy: Value(accuracy),
        altitude: Value(altitude),
        speed: Value(speed),
        heading: Value(heading),
        recordedAt: recordedAt,
      ),
    );
  }

  Future<List<LocationQueueData>> getUnsyncedLocations({int limit = 100}) async {
    final q = select(locationQueue)
      ..where((lq) => lq.synced.equals(false))
      ..orderBy([(lq) => OrderingTerm.asc(lq.recordedAt)])
      ..limit(limit);
    return await q.get();
  }

  Future<void> markLocationsSynced(List<int> ids) async {
    if (ids.isEmpty) return;
    await (update(locationQueue)..where((lq) => lq.id.isIn(ids))).write(
      LocationQueueCompanion(synced: const Value(true)),
    );
  }
}

/// -----------------------------------------------------------------------------
/// Connection helper
/// -----------------------------------------------------------------------------

LazyDatabase _openConnection() {
  return LazyDatabase(() async {
    final dir = await getApplicationDocumentsDirectory();
    final file = File(p.join(dir.path, 'geoptt.db'));
    return NativeDatabase.createInBackground(file);
  });
}

/// Riverpod provider for the database instance
import 'package:flutter_riverpod/flutter_riverpod.dart';

final appDatabaseProvider = Provider<AppDatabase>((ref) {
  return AppDatabase();
});