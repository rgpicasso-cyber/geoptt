import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:web_socket_channel/status.dart' as ws_status;
import 'package:geoptt/features/ptt/audio/audio_service.dart';

/// Cliente WebSocket dedicado ao PTT (binário + controle).
class PttWsClient {
  PttWsClient({
    required this.baseUrl,
    required this.token,
    required this.channelId,
  });

  final String baseUrl;
  final String token;
  final String channelId;

  WebSocketChannel? _channel;
  Timer? _reconnectTimer;
  int _reconnectAttempt = 0;
  static const _maxReconnectAttempts = 10;
  static const _baseReconnectDelay = Duration(seconds: 1);
  static const _maxReconnectDelay = Duration(seconds: 30);

  final _audio = AudioService.instance;

  // Callbacks for UI
  void Function(bool speaking)? onSpeakingChanged;
  void Function(String error)? onError;

  /// Inicia conexão e handshake PTT_DOWN.
  Future<void> connect() async {
    final uri = Uri.parse('$baseUrl/ws?token=$token');
    _channel = WebSocketChannel.connect(uri);
    _channel!.stream.listen(_onMessage, onDone: _onClose, onError: _onError);
    await _sendPttDown();
  }

  Future<void> _sendPttDown() async {
    final msg = jsonEncode({
      'v': 1,
      'type': 'PTT_DOWN',
      'data': {'channel_id': channelId},
    });
    _channel?.sink.add(msg);
  }

  Future<void> _sendPttUp() async {
    final msg = jsonEncode({
      'v': 1,
      'type': 'PTT_UP',
      'data': {'channel_id': channelId},
    });
    _channel?.sink.add(msg);
  }

  void _onMessage(dynamic data) {
    if (data is String) {
      final Map<String, dynamic> json = jsonDecode(data) as Map<String, dynamic>;
      final type = json['type'] as String?;
      final payload = json['data'] as Map<String, dynamic>?;

      switch (type) {
        case 'PTT_BUSY':
          _audio.stopCapture();
          onError?.call('Canal ocupado: ${payload?['speaker_id']}');
          break;
        case 'PTT_SPEAKER_START':
        case 'PTT_SPEAKER_STOP':
          onSpeakingChanged?.call(type == 'PTT_SPEAKER_START');
          break;
        case 'ERROR':
          onError?.call(payload?['message'] ?? 'Erro desconhecido');
          break;
        default:
          break;
      }
    } else if (data is List<int>) {
      _audio.enqueueReceivedChunk(Uint8List.fromList(data));
    }
  }

  void _onClose() {
    _scheduleReconnect();
  }

  void _onError(dynamic error) {
    onError?.call('WebSocket error: $error');
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    if (_reconnectAttempt >= _maxReconnectAttempts) {
      onError?.call('Máximo de tentativas de reconexão atingido');
      return;
    }
    final delayMs = min(
      _baseReconnectDelay.inMilliseconds * pow(2, _reconnectAttempt),
      _maxReconnectDelay.inMilliseconds,
    );
    _reconnectAttempt++;
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(Duration(milliseconds: delayMs.toInt()), () {
      connect();
    });
  }

  /// Envia chunk de áudio binário.
  void sendAudioChunk(List<int> chunk) {
    _channel?.sink.add(chunk);
  }

  /// Envia PTT_DOWN (pressionou botão)
  Future<void> pressDown() async {
    _reconnectAttempt = 0;
    _reconnectTimer?.cancel();
    await connect();
    await _audio.startCapture();
  }

  /// Envia PTT_UP (soltou botão)
  Future<void> pressUp() async {
    await _audio.stopCapture();
    await _sendPttUp();
    _channel?.sink.close(ws_status.normalClosure);
    _reconnectTimer?.cancel();
  }

  void dispose() {
    _reconnectTimer?.cancel();
    _channel?.sink.close(ws_status.goingAway);
  }
}