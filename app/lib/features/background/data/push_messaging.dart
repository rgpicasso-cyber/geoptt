import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

/// Handler de background do FCM.
///
/// **Precisa** ficar fora de qualquer classe e anotado com `@pragma('vm:entry-point')`:
/// o tree-shaker remove símbolos não referenciados e o isolate de background não
/// encontraria a função (regra da skill `mobile-background-resilience`).
///
/// Aqui não há trabalho pesado de propósito: o despertar real (WakeLock + Foreground
/// Service) acontece antes, no Kotlin (`GeoPttMessagingService`). Este isolate serve
/// para manter o contrato do plugin e reagir a mensagens com o app fechado.
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  try {
    if (Firebase.apps.isEmpty) {
      await Firebase.initializeApp();
    }
  } on FirebaseException catch (error) {
    // Sem google-services.json o build local não tem Firebase: degradar é esperado.
    debugPrint('[GeoPTT] FCM background indisponível (${error.code})');
    return;
  }

  final Object? rawType = message.data['type'];
  final String type = rawType is String ? rawType : 'desconhecido';
  debugPrint('[GeoPTT] data message em background: $type');
}

/// Estado da inicialização do push.
@immutable
class PushMessagingState {
  const PushMessagingState({
    required this.available,
    required this.permission,
    this.token,
    this.failureCode,
  });

  final bool available;
  final AuthorizationStatus permission;

  /// Token de **registro** do FCM — não confundir com o FID.
  ///
  /// É o valor que o backend persiste em `users.fcm_token` e usa em
  /// `messaging.Message(token=...)`. A migração para FID está registrada como
  /// ADR-007 (pendente) em `docs/ARCHITECTURE.md` §11.
  final String? token;

  /// Motivo da indisponibilidade (`firebase_unavailable`, `no-app`, ...).
  final String? failureCode;
}

/// Fachada fina sobre `firebase_messaging`.
///
/// Responsabilidade desta classe: expor permissão e token, e pedir permissão **sob
/// demanda**. O registro do handler de background fica em [registerBackgroundHandler] e
/// é chamado no `main()`, antes do `runApp` — registrar aqui seria tarde para o caso de o
/// app estar morto quando a mensagem chega.
///
/// O envio do token ao backend (`POST /users/me/fcm-token`) é da feature `auth`
/// (Fase 4) — aqui não há sessão para autenticar.
class PushMessaging {
  PushMessaging({FirebaseMessaging? messaging})
    : _messaging = messaging ?? FirebaseMessaging.instance;

  final FirebaseMessaging _messaging;

  /// Idempotente: o plugin ignora registros repetidos.
  static void registerBackgroundHandler() {
    FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
  }

  /// Inicializa o Firebase e **lê** o estado — não pede permissão.
  ///
  /// Pedir `POST_NOTIFICATIONS` no boot é hostil (diálogo sem contexto, e uma negativa
  /// no primeiro contato é difícil de reverter). Quem decide o momento é a UI, via
  /// [requestPermission].
  Future<PushMessagingState> initialize() async {
    try {
      if (Firebase.apps.isEmpty) {
        await Firebase.initializeApp();
      }
    } on FirebaseException catch (error) {
      return PushMessagingState(
        available: false,
        permission: AuthorizationStatus.denied,
        failureCode: error.code,
      );
    }

    registerBackgroundHandler();

    final NotificationSettings settings = await _messaging.getNotificationSettings();

    return PushMessagingState(
      available: true,
      permission: settings.authorizationStatus,
      token: await _registrationToken(),
    );
  }

  /// Pede a permissão de notificação (Android 13+/iOS). Retorna o status resultante.
  Future<AuthorizationStatus> requestPermission() async {
    final NotificationSettings settings = await _messaging.requestPermission();
    return settings.authorizationStatus;
  }

  /// Renovação do token de registro — quem persiste no backend é a feature `auth`.
  Stream<String> get tokenRefreshes => _tokenRefreshes();

  /// Por que a API depreciada continua aqui (e não `register()`/`onRegistered`):
  ///
  /// `firebase_messaging` 17 introduziu as APIs de **FID** e depreciou
  /// `getToken()`/`onTokenRefresh`. Mas o backend da Fase 2 envia com
  /// `messaging.Message(token=...)` (token de registro) e persiste o valor em
  /// `users.fcm_token`. Trocar só o cliente faria o servidor mandar para um
  /// identificador que ele não conhece — o PTT simplesmente não acordaria.
  ///
  /// A migração cliente+servidor é a **ADR-007** (`docs/ARCHITECTURE.md` §11) e entra
  /// junto com o deploy. Até lá, usar a API antiga é a escolha correta e consciente;
  /// o `ignore` fica isolado nestes dois pontos para não mascarar outras depreciações.
  Future<String?> _registrationToken() async {
    // ignore: deprecated_member_use
    return _messaging.getToken();
  }

  Stream<String> _tokenRefreshes() {
    // ignore: deprecated_member_use
    return _messaging.onTokenRefresh;
  }
}
