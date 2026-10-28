/// Leitura estrita de mapas vindos de `MethodChannel`/`EventChannel`.
///
/// O canal entrega `Map<Object?, Object?>`: sem conversão explícita, qualquer campo
/// inesperado viraria `dynamic` e escaparia da tipagem estrita (`strict-casts`).
/// Aqui a falha é alta e localizada — `FormatException` com o nome da chave.
library;

extension PlatformMapX on Map<Object?, Object?> {
  String? stringOrNull(String key) {
    final Object? value = this[key];
    if (value == null) return null;
    if (value is String) return value;
    throw FormatException('campo "$key" deveria ser String', value);
  }

  String requireString(String key) {
    final String? value = stringOrNull(key);
    if (value == null || value.isEmpty) {
      throw FormatException('campo obrigatório "$key" ausente');
    }
    return value;
  }

  bool requireBool(String key) {
    final Object? value = this[key];
    if (value is bool) return value;
    throw FormatException('campo "$key" deveria ser bool', value);
  }

  bool boolOr(String key, {required bool fallback}) {
    final Object? value = this[key];
    if (value == null) return fallback;
    if (value is bool) return value;
    throw FormatException('campo "$key" deveria ser bool', value);
  }

  int intOr(String key, {required int fallback}) {
    final Object? value = this[key];
    if (value == null) return fallback;
    if (value is int) return value;
    throw FormatException('campo "$key" deveria ser int', value);
  }

  List<String> stringList(String key) {
    final Object? value = this[key];
    if (value == null) return const <String>[];
    if (value is List<Object?>) {
      return List<String>.unmodifiable(
        value.map((Object? item) {
          if (item is String) return item;
          throw FormatException('campo "$key" contém item não textual', item);
        }),
      );
    }
    throw FormatException('campo "$key" deveria ser List', value);
  }
}
