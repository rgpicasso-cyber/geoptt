import 'dart:async';
import 'dart:typed_data';
import 'package:audio_session/audio_session.dart';
import 'package:just_audio/just_audio.dart';
import 'package:flutter/foundation.dart';

/// Encapsula captura (mic) e reprodução de áudio Opus via WebSocket.
class AudioService {
  AudioService._internal();
  static final AudioService instance = AudioService._internal();

  final AudioPlayer _player = AudioPlayer();
  StreamSubscription<Uint8List>? _playbackSubscription;
  final _chunkController = StreamController<Uint8List>.broadcast();

  /// Stream de chunks Opus prontos para envio (captura).
  Stream<Uint8List> get capturedChunks => _chunkController.stream;

  /// Inicializa sessão de áudio (voice communication) e prepara player.
  Future<void> init() async {
    final session = await AudioSession.instance;
    await session.configure(AudioSessionConfiguration(
      avAudioSessionCategory: AVAudioSessionCategory.playAndRecord,
      avAudioSessionCategoryOptions: AVAudioSessionCategoryOptions.allowBluetooth |
          AVAudioSessionCategoryOptions.defaultToSpeaker,
      avAudioSessionMode: AVAudioSessionMode.voiceChat,
      androidAudioAttributes: AndroidAudioAttributes(
        usage: AndroidAudioUsage.voiceCommunication,
        contentType: AndroidAudioContentType.speech,
        flags: AndroidAudioFlags.none,
      ),
      androidAudioFocusGainType: AndroidAudioFocusGainType.gainTransientMayDuck,
      androidWillPauseWhenDucked: true,
    ));
    // Configura player para stream de bytes (Opus)
    await _player.setAudioSource(_OpusStreamAudioSource(_chunkController.stream));
  }

  /// Inicia captura simulada (placeholder) emitindo chunks dummy a cada 200 ms.
  Future<void> startCapture() async {
    // Em produção, usar `record` para capturar mic real.
    // Aqui emitimos pacotes dummy de 20 ms (Opus 64 kbps ≈ 160 bytes).
    Timer.periodic(const Duration(milliseconds: 200), (timer) {
      if (!_chunkController.isClosed) {
        _chunkController.add(Uint8List(160));
      } else {
        timer.cancel();
      }
    });
  }

  /// Para captura.
  Future<void> stopCapture() async {
    // timer will be cancelled when controller closed
  }

  /// Reproduz chunks recebidos do WebSocket.
  void enqueueReceivedChunk(Uint8List opusChunk) {
    _chunkController.add(opusChunk);
  }

  /// Libera recursos.
  Future<void> dispose() async {
    await _player.dispose();
    await _chunkController.close();
  }
}

/// Fonte de áudio customizada que consome chunks Opus de um Stream.
class _OpusStreamAudioSource extends StreamAudioSource {
  final Stream<Uint8List> _chunkStream;
  _OpusStreamAudioSource(this._chunkStream);

  @override
  Future<StreamAudioResponse> request([int? start, int? end]) async {
    return StreamAudioResponse(
      sourceLength: -1,
      contentLength: -1,
      offset: start ?? 0,
      stream: _chunkStream,
      contentType: 'audio/opus',
    );
  }
}