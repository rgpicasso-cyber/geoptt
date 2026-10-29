import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geoptt/core/storage/secure_storage.dart';
import 'package:geoptt/features/auth/data/auth_repository.dart';
import 'package:geoptt/core/network/dio_client.dart';

/// Authentication status enum
enum AuthStatus {
  unknown,
  unauthenticated,
  authenticating,
  authenticated,
}

/// State held by the auth notifier
class AuthState {
  const AuthState({
    this.status = AuthStatus.unknown,
    this.userUuid,
    this.displayName,
    this.email,
    this.avatarUrl,
  });

  final AuthStatus status;
  final String? userUuid;
  final String? displayName;
  final String? email;
  final String? avatarUrl;

  bool get isAuthenticated => status == AuthStatus.authenticated;
  bool get isLoading => status == AuthStatus.authenticating;

  AuthState copyWith({
    AuthStatus? status,
    String? userUuid,
    String? displayName,
    String? email,
    String? avatarUrl,
  }) {
    return AuthState(
      status: status ?? this.status,
      userUuid: userUuid ?? this.userUuid,
      displayName: displayName ?? this.displayName,
      email: email ?? this.email,
      avatarUrl: avatarUrl ?? this.avatarUrl,
    );
  }
}

/// Notifier managing authentication lifecycle
class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier({
    required AuthRepository authRepository,
    required SecureStorage secureStorage,
  })  : _authRepo = authRepository,
        _storage = secureStorage,
        super(const AuthState(status: AuthStatus.unknown)) {
    _init();
  }

  final AuthRepository _authRepo;
  final SecureStorage _storage;

  Future<void> _init() async {
    // Try to restore session from secure storage
    final access = await _storage.readAccessToken();
    final uuid = await _storage.readUserUuid();
    if (access != null && uuid != null) {
      // We have a token; try to fetch profile to validate
      state = state.copyWith(status: AuthStatus.authenticating);
      try {
        final profile = await _authRepo.fetchProfile();
        state = state.copyWith(
          status: AuthStatus.authenticated,
          userUuid: profile.uuid,
          displayName: profile.displayName,
          email: profile.email,
          avatarUrl: profile.avatarUrl,
        );
      } catch (_) {
        // Token invalid/expired -> try refresh
        final refreshed = await _authRepo.refreshAccessToken();
        if (refreshed) {
          try {
            final profile = await _authRepo.fetchProfile();
            state = state.copyWith(
              status: AuthStatus.authenticated,
              userUuid: profile.uuid,
              displayName: profile.displayName,
              email: profile.email,
              avatarUrl: profile.avatarUrl,
            );
            return;
          } catch (_) {}
        }
        // Refresh failed -> unauthenticated
        await _storage.clearAllAuth();
        state = state.copyWith(status: AuthStatus.unauthenticated);
      }
    } else {
      state = state.copyWith(status: AuthStatus.unauthenticated);
    }
  }

  Future<void> login({required String email, required String password}) async {
    state = state.copyWith(status: AuthStatus.authenticating);
    try {
      await _authRepo.login(email: email, password: password);
      final profile = await _authRepo.fetchProfile();
      state = state.copyWith(
        status: AuthStatus.authenticated,
        userUuid: profile.uuid,
        displayName: profile.displayName,
        email: profile.email,
        avatarUrl: profile.avatarUrl,
      );
    } catch (e) {
      state = state.copyWith(status: AuthStatus.unauthenticated);
      rethrow;
    }
  }

  Future<void> register({
    required String email,
    required String password,
    required String displayName,
  }) async {
    state = state.copyWith(status: AuthStatus.authenticating);
    try {
      await _authRepo.register(email: email, password: password, displayName: displayName);
      final profile = await _authRepo.fetchProfile();
      state = state.copyWith(
        status: AuthStatus.authenticated,
        userUuid: profile.uuid,
        displayName: profile.displayName,
        email: profile.email,
        avatarUrl: profile.avatarUrl,
      );
    } catch (e) {
      state = state.copyWith(status: AuthStatus.unauthenticated);
      rethrow;
    }
  }

  Future<void> logout() async {
    await _authRepo.logout();
    state = const AuthState(status: AuthStatus.unauthenticated);
  }
}

/// Provider for SecureStorage (singleton)
final Provider<SecureStorage> secureStorageProvider = Provider<SecureStorage>((ref) => SecureStorage());

/// Provider for DioClient (singleton)
final Provider<DioClient> dioClientProvider = Provider<DioClient>((ref) {
  final storage = ref.watch(secureStorageProvider);
  return DioClient(
    baseUrl: 'https://api.geoptt.local/api/v1', // TODO: move to config/env
    secureStorage: storage,
  );
});

/// Provider for AuthRepository
final Provider<AuthRepository> authRepositoryProvider = Provider<AuthRepository>((ref) {
  final dio = ref.watch(dioClientProvider);
  final storage = ref.watch(secureStorageProvider);
  return AuthRepository(dioClient: dio, secureStorage: storage);
});

/// Provider for AuthNotifier (state)
final StateNotifierProvider<AuthNotifier, AuthState> authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  final repo = ref.watch(authRepositoryProvider);
  final storage = ref.watch(secureStorageProvider);
  return AuthNotifier(authRepository: repo, secureStorage: storage);
});