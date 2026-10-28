plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.geoptt"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.geoptt"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")

            // R8 fica desligado nesta fase: ativar minificação sem um build de release
            // testado em aparelho (Fase 6) trocaria tamanho por crashes silenciosos.
            // As regras já estão ligadas abaixo para que a virada seja só a flag.
            isMinifyEnabled = false
            isShrinkResources = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }
}

/**
 * Versão do BOM do Firebase usada pelo FlutterFire.
 *
 * O plugin `firebase_core` publica `FirebaseSDKVersion` no seu `gradle.properties` e o
 * consome internamente. Lemos a mesma propriedade para não divergir do plugin — se um
 * upgrade do FlutterFire subir a versão, este módulo acompanha sozinho. O fallback só
 * existe para o caso de o projeto `:firebase_core` não estar disponível.
 */
val firebaseBomVersion: String = (findProperty("FirebaseSDKVersion") as String?)
    ?: runCatching {
        project(":firebase_core").property("FirebaseSDKVersion") as String
    }.getOrElse { "35.1.0" }

dependencies {
    // NotificationCompat / ServiceCompat / ContextCompat usados pelo relay.
    // O embedding do Flutter já traz androidx.core transitivamente; declarar aqui
    // evita depender de resolução implícita.
    implementation("androidx.core:core-ktx:1.17.0")

    // Obrigatório para `GeoPttMessagingService`: as dependências `implementation` de um
    // subprojeto de plugin NÃO vazam para o classpath de compilação do `:app`, então
    // `FirebaseMessagingService`/`RemoteMessage` não estariam visíveis sem esta linha.
    // Sem versão explícita de artefato: o BOM abaixo é a única fonte de verdade.
    implementation(platform("com.google.firebase:firebase-bom:$firebaseBomVersion"))
    implementation("com.google.firebase:firebase-messaging")

    testImplementation("junit:junit:4.13.2")
}

// O google-services.json é gitignored (IDs do projeto Firebase). Sem ele, o plugin do
// Google falha o build inteiro — então só aplicamos quando o arquivo existe.
// Consequência: builds locais sem Firebase compilam, mas o FCM fica inativo.
if (file("google-services.json").exists()) {
    apply(plugin = "com.google.gms.google-services")
} else {
    logger.lifecycle(
        "google-services.json ausente: build sem Firebase (FCM inativo). " +
            "Ver docs/ARCHITECTURE.md §4.1.",
    )
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
