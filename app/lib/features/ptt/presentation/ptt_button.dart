import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geoptt/features/ptt/audio/audio_service.dart';
import 'package:geoptt/features/background/background.dart';

/// Botão Hold‑to‑Talk que inicia/para captura e envia chunks via WebSocket.
class PttButton extends ConsumerStatefulWidget {
  const PttButton({super.key});

  @override
  ConsumerState<PttButton> createState() => _PttButtonState();
}

class _PttButtonState extends ConsumerState<PttButton> {
  bool _pressed = false;
  StreamSubscription<Uint8List>? _sendSub;

  @override
  void initState() {
    super.initState();
    // Inicializa audio session
    AudioService.instance.init();
  }

  void _onPressDown() async {
    setState(() => _pressed = true);
    // Inicia captura local
    await AudioService.instance.startCapture();
    // Sobe relay (Android) / canal PTT (iOS)
    final bridge = ref.read(backgroundBridgeProvider);
    await bridge.startRelay();
    // Escuta chunks capturados e envia via WebSocket (via pttProvider)
    _listenAndSend();
  }

  void _onPressUp() async {
    setState(() => _pressed = false);
    await AudioService.instance.stopCapture();
    final bridge = ref.read(backgroundBridgeProvider);
    await bridge.stopRelay();
    _cancelSend();
  }

  void _listenAndSend() {
    final audio = AudioService.instance;
    _sendSub = audio.capturedChunks.listen((chunk) {
      // Envia chunk binário via WebSocket (implementado no pttProvider)
      ref.read(pttSenderProvider).sendAudioChunk(chunk);
    });
  }

  void _cancelSend() {
    _sendSub?.cancel();
    _sendSub = null;
  }

  @override
  void dispose() {
    _cancelSend();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onLongPressStart: (_) => _onPressDown(),
      onLongPressEnd: (_) => _onPressUp(),
      onTapDown: (_) => _onPressDown(),
      onTapUp: (_) => _onPressUp(),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        width: 120,
        height: 120,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: _pressed ? Colors.red : Colors.blue,
          boxShadow: [
            if (_pressed)
              BoxShadow(
                color: Colors.red.withOpacity(0.6),
                blurRadius: 20,
                spreadRadius: 5,
              ),
          ],
        ),
        child: Center(
          child: Icon(
            _pressed ? Icons.mic : Icons.mic_none,
            size: 48,
            color: Colors.white,
          ),
        ),
      ),
    );
  }
}

// Provider dummy para envio; implementação real no pttProvider (WS)
final pttSenderProvider = Provider<PttSender>((ref) => _DummyPttSender());

class PttSender {
  void sendAudioChunk(Uint8List chunk) {}
}

class _DummyPttSender implements PttSender {
  @override
  void sendAudioChunk(Uint8List chunk) {
    // TODO: integrar com ConnectionManager do backend via WebSocket
  }
}