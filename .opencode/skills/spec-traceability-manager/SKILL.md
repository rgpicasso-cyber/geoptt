---
name: spec-traceability-manager
description: Skill comportamental obrigatória para manter a documentação arquitetural e o histórico do projeto sempre atualizados.
---

# Specification & Traceability Manager Skill

## Quando usar esta Skill
DEVE ser acionada ANTES de escrever qualquer código para entender a fase atual, e APÓS concluir uma tarefa para registrar o progresso.

## Regras de Ouro
1. **O Triângulo da Verdade:** A verdade absoluta do projeto reside nestes 3 arquivos na pasta `/docs`: `ARCHITECTURE.md`, `DATA_MODEL.md` e `TASKS.md`.
2. **Registro de Estado (`STATE_TRACEABILITY.md`):** Após qualquer implementação bem-sucedida ou alteração arquitetural, o agente DEVE fazer um "append" neste arquivo com a data, a ação realizada, bibliotecas novas adicionadas e próximos passos.
3. **Sincronia de Data Model:** Se for necessário adicionar um novo campo no banco de dados (ex: `fcm_token` na tabela `User`), essa alteração deve ser PRIMEIRO documentada no `DATA_MODEL.md` e só depois programada em código (Python/Dart).
4. **Respeito às Fases:** Só avance para a "Fase X+1" do `TASKS.md` se o usuário disser que a "Fase X" foi testada e aprovada.
