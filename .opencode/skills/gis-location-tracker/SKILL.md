---
name: gis-location-tracker
description: Diretrizes para rastreamento de localização em segundo plano (estilo Life360), integração OpenStreetMap e economia de bateria.
---

# GIS & Location Tracker Skill

## Quando usar esta Skill
Na construção do módulo de mapas no Flutter, serviços de captura de GPS em background e endpoints geográficos no FastAPI.

## Regras de Ouro
1. **Frontend Map Engine:** O mapa deve ser renderizado utilizando o pacote `flutter_map` consumindo tilesheet do **OpenStreetMap (OSM)**. Não utilize Google Maps SDK para evitar custos de API.
2. **Economia de Bateria (Smart Ping):** A localização em segundo plano não deve fazer "ping" no servidor a cada 1 segundo. Implemente uma lógica de gatilho baseada em distância (ex: só atualize se mover mais de 10 metros) e tempo limite (heartbeat a cada 2 minutos se parado).
3. **Payload Enriquecido:** Todo pacote de localização (`LocationDTO`) enviado ao servidor DEVE conter: `user_id`, `lat`, `lng`, `speed`, `heading` (direção) e `battery_level` (para que outros usuários vejam a bateria, padrão Life360).
4. **Backend (Geo-Queries):** Se usar SQLite no backend, utilize as funções matemáticas de Haversine para calcular distâncias. Se escalar para PostgreSQL, utilize obrigatoriamente a extensão **PostGIS**.
