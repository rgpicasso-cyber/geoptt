import 'dart:async';

import 'package:flutter/material.dart';

import 'features/background/background.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  // Registrar o handler de background ANTES de `runApp`: uma data message pode chegar
  // enquanto a UI ainda está inicializando (app aberto por toque na notificação) e o
  // isolate de background precisa existir antes disso. Também é obrigatório em
  // `main()` — registrar depois do primeiro frame é tarde para o caso de app morto.
  PushMessaging.registerBackgroundHandler();

  runApp(const GeoPttApp());
}

class GeoPttApp extends StatelessWidget {
  const GeoPttApp({
    super.key,
    this.bridge,
    this.push,
  });

  /// Injeção para testes de widget.
  final BackgroundBridge? bridge;
  final PushMessaging? push;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'GeoPTT',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorSchemeSeed: const Color(0xFF1565C0),
      ),
      home: RelayDiagnosticsPage(bridge: bridge, push: push),
    );
  }
}

/// Painel temporário de diagnóstico da Fase 3.
///
/// Existe para validar em aparelho real o que o teste automatizado não alcança:
/// swipe-away mantendo o serviço, reboot religando o relay e isenção de bateria.
/// A UI de produto (mapa + PTT) entra nas Fases 4 e 5 — esta tela será descartada.
class RelayDiagnosticsPage extends StatefulWidget {
  const RelayDiagnosticsPage({super.key, this.bridge, this.push});

  /// Injeção para testes de widget.
  final BackgroundBridge? bridge;
  final PushMessaging? push;

  @override
  State<RelayDiagnosticsPage> createState() => _RelayDiagnosticsPageState();
}

class _RelayDiagnosticsPageState extends State<RelayDiagnosticsPage> {
  late final BackgroundBridge _bridge;
  late final PushMessaging _push;

  StreamSubscription<BackgroundEvent>? _subscription;
  RelayStatus? _status;
  PushMessagingState? _pushState;
  String? _lastEvent;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _bridge = widget.bridge ?? BackgroundBridge();
    _push = widget.push ?? PushMessaging();

    _subscription = _bridge.events.listen(
      _onEvent,
      onError: (Object error) {
        if (!mounted) return;
        setState(() => _lastEvent = 'stream nativo falhou: $error');
      },
    );

    unawaited(_refreshStatus());
    unawaited(_initPush());
  }

  @override
  void dispose() {
    unawaited(_subscription?.cancel());
    _bridge.dispose();
    super.dispose();
  }

  // ------------------------------------------------------------------ eventos

  void _onEvent(BackgroundEvent event) {
    if (!mounted) return;
    setState(() => _lastEvent = _describe(event));

    if (event is RelayStartedEvent ||
        event is RelayStoppedEvent ||
        event is RelayStartDeniedEvent) {
      unawaited(_refreshStatus());
    }
  }

  String _describe(BackgroundEvent event) => switch (event) {
    PttWakeupEvent(:final String channelId) =>
      'wake-up recebido (canal ${_shortId(channelId)}…)',
    RelayStartedEvent(:final List<String> foregroundTypes) =>
      'relay ativo · tipos: ${foregroundTypes.join(', ')}',
    RelayStoppedEvent(:final String source) => 'relay parado ($source)',
    RelayStartDeniedEvent(:final RelayStartSource source) =>
      'Android recusou o relay (origem: ${source.name})',
    BatteryExemptionChangedEvent(:final bool ignoring) =>
      ignoring ? 'isenção de bateria concedida' : 'isenção de bateria removida',
    NotificationPermissionEvent(:final bool granted) =>
      granted ? 'notificações permitidas' : 'notificações negadas',
    UnknownBackgroundEvent(:final Map<Object?, Object?> raw) =>
      'evento desconhecido: ${raw['event']}',
  };

  /// IDs vêm do servidor (UUID), mas um payload truncado não pode derrubar a tela de
  /// diagnóstico com `RangeError` — `substring(0, 8)` estoura em string curta.
  static String _shortId(String value) =>
      value.length <= 8 ? value : value.substring(0, 8);

  // ------------------------------------------------------------------ ações

  Future<void> _refreshStatus() async {
    try {
      final RelayStatus status = await _bridge.getStatus();
      if (!mounted) return;
      setState(() => _status = status);
    } on BackgroundBridgeException catch (error) {
      if (!mounted) return;
      setState(() => _lastEvent = 'status indisponível: ${error.code}');
    }
  }

  Future<void> _initPush() async {
    try {
      final PushMessagingState state = await _push.initialize();
      if (!mounted) return;
      setState(() => _pushState = state);
    } on Object catch (error) {
      // Falha de plugin/Firebase não pode virar exceção não tratada no `initState`.
      if (!mounted) return;
      setState(() => _lastEvent = 'push indisponível: $error');
    }
  }

  Future<void> _startRelay() async {
    setState(() => _busy = true);
    try {
      final bool exempt = await _bridge.isIgnoringBatteryOptimizations();
      if (!exempt) {
        if (!mounted) return;
        final BatteryPromptDecision decision = await showBatteryOptimizationPrompt(context);
        if (decision == BatteryPromptDecision.allow) {
          await _bridge.requestIgnoreBatteryOptimizations();
        }
      }

      final RelayStartResult result = await _bridge.startRelay();
      if (!mounted) return;
      setState(
        () => _lastEvent =
            'relay solicitado · tipos: ${result.foregroundTypes.join(', ')}',
      );
      await _refreshStatus();
    } on BackgroundBridgeException catch (error) {
      if (!mounted) return;
      setState(() => _lastEvent = 'falha ao iniciar: ${error.code}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _stopRelay() async {
    setState(() => _busy = true);
    try {
      final bool accepted = await _bridge.stopRelay();
      if (!mounted) return;
      setState(
        () => _lastEvent = accepted
            ? 'relay desligado'
            : 'o Android não aceitou a parada; o serviço pode continuar ativo',
      );
      await _refreshStatus();
    } on BackgroundBridgeException catch (error) {
      if (!mounted) return;
      setState(() => _lastEvent = 'falha ao parar: ${error.code}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _consumeWakeup() async {
    try {
      final PttWakeupEvent? wakeup = await _bridge.consumePendingWakeup();
      if (!mounted) return;
      setState(
        () => _lastEvent = wakeup == null
            ? 'nenhum wake-up pendente'
            : 'wake-up pendente drenado (canal ${_shortId(wakeup.channelId)}…)',
      );
    } on BackgroundBridgeException catch (error) {
      if (!mounted) return;
      setState(() => _lastEvent = 'wake-up indisponível: ${error.code}');
    }
  }

  Future<void> _openBatterySettings() async {
    try {
      final BatteryExemptionRequest request =
          await _bridge.requestIgnoreBatteryOptimizations();
      if (!mounted) return;
      setState(
        () => _lastEvent = request.alreadyGranted
            ? 'app já está isento de otimização'
            : 'tela de isenção aberta',
      );
    } on BackgroundBridgeException catch (error) {
      if (!mounted) return;
      setState(() => _lastEvent = 'isenção indisponível: ${error.code}');
    }
  }

  // ------------------------------------------------------------------ UI

  @override
  Widget build(BuildContext context) {
    final RelayStatus? status = _status;

    return Scaffold(
      appBar: AppBar(
        title: const Text('GeoPTT · diagnóstico'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Atualizar status',
            onPressed: _busy ? null : () => unawaited(_refreshStatus()),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: <Widget>[
          _StatusCard(status: status),
          const SizedBox(height: 12),
          _PushCard(state: _pushState),
          const SizedBox(height: 12),
          _EventCard(message: _lastEvent),
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: _busy ? null : () => unawaited(_startRelay()),
            icon: const Icon(Icons.play_arrow),
            label: const Text('Ativar canal PTT'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _busy ? null : () => unawaited(_stopRelay()),
            icon: const Icon(Icons.stop),
            label: const Text('Desligar canal PTT'),
          ),
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: _busy ? null : () => unawaited(_consumeWakeup()),
            icon: const Icon(Icons.mark_email_unread_outlined),
            label: const Text('Drenar wake-up pendente'),
          ),
          TextButton.icon(
            onPressed: _busy ? null : () => unawaited(_openBatterySettings()),
            icon: const Icon(Icons.battery_saver_outlined),
            label: const Text('Abrir isenção de bateria'),
          ),
        ],
      ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.status});

  final RelayStatus? status;

  @override
  Widget build(BuildContext context) {
    final RelayStatus? current = status;
    if (current == null) {
      return const Card(
        child: ListTile(
          leading: Icon(Icons.hourglass_empty),
          title: Text('Lendo estado do relay…'),
        ),
      );
    }

    return Card(
      child: Column(
        children: <Widget>[
          ListTile(
            leading: Icon(
              current.running ? Icons.radio_button_checked : Icons.radio_button_off,
              color: current.running ? Colors.green : null,
            ),
            title: Text(current.running ? 'Relay ativo' : 'Relay parado'),
            subtitle: Text(
              current.foregroundTypes.isEmpty
                  ? 'sem foregroundServiceType declarado'
                  : 'tipos: ${current.foregroundTypes.join(', ')}',
            ),
          ),
          _InfoRow(
            label: 'Ativado pelo usuário',
            value: current.enabled ? 'sim' : 'não',
          ),
          _InfoRow(
            label: 'Isenção de bateria',
            value: current.ignoringBatteryOptimizations ? 'concedida' : 'pendente',
          ),
          _InfoRow(
            label: 'Notificações',
            value: current.notificationPermission.name,
          ),
          _InfoRow(
            label: 'Pode falar em background',
            value: current.canSpeakInBackground ? 'sim' : 'não (só ouve)',
          ),
          _InfoRow(
            label: 'Aparelho',
            value: '${current.manufacturer} · API ${current.sdkInt}',
          ),
        ],
      ),
    );
  }
}

class _PushCard extends StatelessWidget {
  const _PushCard({required this.state});

  final PushMessagingState? state;

  @override
  Widget build(BuildContext context) {
    final PushMessagingState? current = state;
    if (current == null) {
      return const Card(
        child: ListTile(
          leading: Icon(Icons.cloud_queue),
          title: Text('Inicializando Firebase…'),
        ),
      );
    }

    return Card(
      child: Column(
        children: <Widget>[
          ListTile(
            leading: Icon(
              current.available ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
            ),
            title: Text(current.available ? 'FCM disponível' : 'FCM indisponível'),
            subtitle: Text(
              current.available
                  ? 'permissão: ${current.permission.name}'
                  : 'motivo: ${current.failureCode ?? 'desconhecido'}',
            ),
          ),
          if (current.token != null)
            _InfoRow(label: 'Token (mascarado)', value: _mask(current.token)),        ],
      ),
    );
  }

  /// Nunca exibir o token completo: ele permite enviar push para o aparelho.
  static String _mask(String? token) {
    if (token == null || token.length < 12) return '—';
    return '${token.substring(0, 8)}…${token.length}b';
  }
}

class _EventCard extends StatelessWidget {
  const _EventCard({required this.message});

  final String? message;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: const Icon(Icons.bolt_outlined),
        title: const Text('Último evento'),
        subtitle: Text(message ?? 'nenhum evento desde o start'),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      child: Row(
        children: <Widget>[
          Expanded(child: Text(label)),
          Text(
            value,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
