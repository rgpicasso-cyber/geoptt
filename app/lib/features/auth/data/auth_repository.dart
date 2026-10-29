import 'package:dio/dio.dart';
import 'package:geoptt/core/network/dio_client.dart';
import 'package:geoptt/core/storage/secure_storage.dart';

/// Data models for auth responses
class AuthTokens {
  final String accessToken;
  final String refreshToken;
  final DateTime expiry;

  AuthTokens({
    required this.accessToken,
    required this.refreshToken,
    required this.expiry,
  });

  factory AuthTokens.fromJson(Map<String, dynamic> json) {
    return AuthTokens(
      accessToken: json['access_token'] as String,
      refreshToken: json['refresh_token'] as String,
      expiry: DateTime.parse(json['expires_at'] as String),
    );
  }
}

class UserProfile {
  final String uuid;
  final String email;
  final String displayName;
  final String? avatarUrl;

  UserProfile({
    required this.uuid,
    required this.email,
    required this.displayName,
    this.avatarUrl,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    return UserProfile(
      uuid: json['uuid'] as String,
      email: json['email'] as String,
      displayName: json['display_name'] as String,
      avatarUrl: json['avatar_url'] as String?,
    );
  }
}

/// Repository handling all auth-related HTTP calls.
class AuthRepository {
  AuthRepository({
    required DioClient dioClient,
    required SecureStorage secureStorage,
  })  : _dio = dioClient.dio,
        _storage = secureStorage;

  final Dio _dio;
  final SecureStorage _storage;

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /// Register a new user.
  Future<AuthTokens> register({
    required String email,
    required String password,
    required String displayName,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/auth/register',
      data: {
        'email': email,
        'password': password,
        'display_name': displayName,
      },
    );
    final tokens = AuthTokens.fromJson(resp.data!);
    await _persistTokens(tokens);
    return tokens;
  }

  /// Login with email/password (OAuth2 password flow).
  Future<AuthTokens> login({
    required String email,
    required String password,
  }) async {
    // FastAPI OAuth2PasswordRequestForm expects form data with fields
    // username (email) and password.
    final formData = FormData.fromMap({
      'username': email,
      'password': password,
    });
    final resp = await _dio.post<Map<String, dynamic>>(
      '/auth/login',
      data: formData,
      options: Options(
        headers: {'Content-Type': 'multipart/form-data'},
      ),
    );
    final tokens = AuthTokens.fromJson(resp.data!);
    await _persistTokens(tokens);
    return tokens;
  }

  /// Refresh access token using stored refresh token.
  Future<bool> refreshAccessToken() async {
    final refresh = await _storage.readRefreshToken();
    if (refresh == null) return false;

    try {
      final resp = await _dio.post<Map<String, dynamic>>(
        '/auth/refresh',
        data: {'refresh_token': refresh},
      );
      final tokens = AuthTokens.fromJson(resp.data!);
      await _persistTokens(tokens);
      return true;
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) {
        await _storage.clearAllAuth();
      }
      return false;
    }
  }

  /// Logout - revoke refresh token on server and clear local storage.
  Future<void> logout() async {
    final refresh = await _storage.readRefreshToken();
    if (refresh != null) {
      try {
        await _dio.post('/auth/logout', data: {'refresh_token': refresh});
      } catch (_) {
        // ignore server errors; we clear locally anyway
      }
    }
    await _storage.clearAllAuth();
  }

  /// Return stored user UUID if any.
  Future<String?> getCurrentUserUuid() async {
    return await _storage.readUserUuid();
  }

  /// Fetch current user profile.
  Future<UserProfile> fetchProfile() async {
    final resp = await _dio.get<Map<String, dynamic>>('/users/me');
    return UserProfile.fromJson(resp.data!);
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  Future<void> _persistTokens(AuthTokens tokens) async {
    await Future.wait([
      _storage.saveAccessToken(tokens.accessToken),
      _storage.saveRefreshToken(tokens.refreshToken),
      _storage.saveTokenExpiry(tokens.expiry),
    ]);
  }
}