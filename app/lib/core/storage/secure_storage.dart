import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Wrapper around [FlutterSecureStorage] with typed keys used by the app.
class SecureStorage {
  SecureStorage._internal(this._storage);
  static final SecureStorage _instance = SecureStorage._internal(
    const FlutterSecureStorage(
      aOptions: AndroidOptions(encryptedSharedPreferences: true),
      iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
    ),
  );

  factory SecureStorage() => _instance;

  final FlutterSecureStorage _storage;

  // Keys
  static const _kAccessToken = 'auth_access_token';
  static const _kRefreshToken = 'auth_refresh_token';
  static const _kTokenExpiry = 'auth_token_expiry'; // ISO8601 string
  static const _kUserUuid = 'auth_user_uuid';

  // ------------------- Access Token -------------------
  Future<void> saveAccessToken(String token) async {
    await _storage.write(key: _kAccessToken, value: token);
  }

  Future<String?> readAccessToken() async {
    return await _storage.read(key: _kAccessToken);
  }

  Future<void> deleteAccessToken() async {
    await _storage.delete(key: _kAccessToken);
  }

  // ------------------- Refresh Token -------------------
  Future<void> saveRefreshToken(String token) async {
    await _storage.write(key: _kRefreshToken, value: token);
  }

  Future<String?> readRefreshToken() async {
    return await _storage.read(key: _kRefreshToken);
  }

  Future<void> deleteRefreshToken() async {
    await _storage.delete(key: _kRefreshToken);
  }

  // ------------------- Token Expiry -------------------
  Future<void> saveTokenExpiry(DateTime expiry) async {
    await _storage.write(key: _kTokenExpiry, value: expiry.toIso8601String());
  }

  Future<DateTime?> readTokenExpiry() async {
    final s = await _storage.read(key: _kTokenExpiry);
    if (s == null) return null;
    return DateTime.tryParse(s);
  }

  Future<void> deleteTokenExpiry() async {
    await _storage.delete(key: _kTokenExpiry);
  }

  // ------------------- User UUID -------------------
  Future<void> saveUserUuid(String uuid) async {
    await _storage.write(key: _kUserUuid, value: uuid);
  }

  Future<String?> readUserUuid() async {
    return await _storage.read(key: _kUserUuid);
  }

  Future<void> deleteUserUuid() async {
    await _storage.delete(key: _kUserUuid);
  }

  // ------------------- Clear All Auth -------------------
  Future<void> clearAllAuth() async {
    await Future.wait([
      deleteAccessToken(),
      deleteRefreshToken(),
      deleteTokenExpiry(),
      deleteUserUuid(),
    ]);
  }
}