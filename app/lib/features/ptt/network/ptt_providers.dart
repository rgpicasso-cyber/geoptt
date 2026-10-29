import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geoptt/features/ptt/network/ptt_ws_client.dart';
import 'package:geoptt/core/storage/secure_storage.dart';

final pttWsClientProvider = Provider.autoDispose<PttWsClient>((ref) {
  final storage = ref.watch(secureStorageProvider);
  final token = storage.readAccessToken() ?? '';
  // baseUrl deve vir de config/env
  const baseUrl = 'wss://api.geoptt.local';
  // channelId fixo por enquanto; depois virá do círculo selecionado
  const channelId = '00000000-0000-0000-0000-000000000001';
  return PttWsClient(baseUrl: baseUrl, token: token, channelId: channelId);
});