---
name: flutter-reactive-state
description: Diretrizes arquiteturais para gerência de estado no Frontend (Flutter) separando UI de regras de negócio.
---

# Flutter Reactive State Skill

## Quando usar esta Skill
Sempre que for criar telas, widgets, controladores ou gerenciar a atualização do mapa e do botão PTT na interface do usuário.

## Regras de Ouro
1. **Padrão de Estado:** Utilize uma gerência de estado reativa clara (como `Provider`, `Riverpod` ou `BLoC/Cubit` - prefira a que for definida no `rules.md`). Nunca coloque lógica de WebSocket ou GPS diretamente dentro dos arquivos de interface (`.dart` com Widgets).
2. **Isolamento de Streams:** O estado do botão PTT (pressionado, solto, conectando, falando) e o Stream de localização dos amigos no mapa devem rodar de forma independente. Atualizar a posição de um amigo no mapa NÃO PODE fazer o botão do PTT piscar ou a tela inteira dar *rebuild*.
3. **Padrão Repositório:** O código da UI só se comunica com "Controllers" ou "Repositories". Quem acessa o SQLite local ou a API REST/WebSocket é o Repositório, nunca a View.
