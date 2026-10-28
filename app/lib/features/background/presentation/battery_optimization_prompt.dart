import 'package:flutter/material.dart';

/// Decisão do usuário no pedido de isenção de bateria.
enum BatteryPromptDecision { allow, later }

/// Pede a isenção de otimização de bateria de forma **graciosa**.
///
/// Regra da skill `mobile-background-resilience`: nunca disparar o intent direto.
/// Sem a isenção o Android atrasa Data Messages em Doze Mode e o PTT chega minutos
/// depois — mas o app continua funcionando, então recusar é uma opção legítima.
Future<BatteryPromptDecision> showBatteryOptimizationPrompt(BuildContext context) async {
  final BatteryPromptDecision? decision = await showDialog<BatteryPromptDecision>(
    context: context,
    barrierDismissible: false,
    builder: (BuildContext dialogContext) => const _BatteryOptimizationDialog(),
  );
  return decision ?? BatteryPromptDecision.later;
}

class _BatteryOptimizationDialog extends StatelessWidget {
  const _BatteryOptimizationDialog();

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);

    return AlertDialog(
      icon: const Icon(Icons.battery_alert_outlined),
      title: const Text('Manter o canal PTT ativo'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const Text(
            'Para receber voz e compartilhar sua localização com o app fechado, o '
            'Android precisa de uma exceção na otimização de bateria.',
          ),
          const SizedBox(height: 12),
          Text(
            'Sem essa exceção o sistema pode atrasar o aviso de chamada em até '
            'vários minutos. Você pode mudar isso depois nas configurações do aparelho.',
            style: theme.textTheme.bodySmall,
          ),
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(BatteryPromptDecision.later),
          child: const Text('Agora não'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(BatteryPromptDecision.allow),
          child: const Text('Permitir'),
        ),
      ],
    );
  }
}
