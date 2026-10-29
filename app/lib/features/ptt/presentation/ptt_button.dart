import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geoptt/features/ptt/audio/audio_service.dart';
import 'package:geoptt/features/background/background.dart';
import 'package:geoptt/features/ptt/network/ptt_ws_client.dart';
import 'package:geoptt/features/ptt/network/ptt_providers.dart';

/// Botão Hold‑to‑Talk que inicia/para captura e envia chunks via WebSocket real.
class PttButton extends ConsumerStatefulWidget {
  const PttButton({super.key});

  @override
  ConsumerState<PttButton> createState() => _PttButtonState();
}

class _PttButtonState extends ConsumerState<PttButton> {
  bool _pressed = false;
  PttWsClient? _wsClient;

  @override
  void initState() {
    super.initState();
    AudioService.instance.init();
  }

  void _onPressDown() async {
    setState(() => _pressed = true);
    // Inicia captura local
    await AudioService.instance.startCapture();
    // Sobe relay (Android) / canal PTT (iOS)
    final bridge = ref.read(backgroundBridgeProvider);
    await bridge.startRelay();

    // Conecta WebSocket e envia PTT_DOWN
    _wsClient = ref.read(pttWsClientProvider);
    _wsClient!.onSpeakingChanged = (speaking) {
      // Atualiza UI se necessário
    };
    _wsClient!.onError = (msg) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
      }
    };
    await _wsClient!.pressDown();
  }

  void _onPressUp() async {
    setState(() => _pressed = false);
    await AudioService.instance.stopCapture();
    final bridge = ref.read(backgroundBridgeProvider);
    await bridge.stopRelay();
    await _wsClient?.pressUp();
    _wsClient = null;
  }

  @override
  void dispose() {
    _wsClient?.dispose();
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
      );
    }
  }
}