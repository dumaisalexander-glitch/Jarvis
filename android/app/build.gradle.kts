plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.loryzon.jarvis"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.loryzon.jarvis"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }

    signingConfigs {
        // Clé privée optionnelle fournie par GitHub Actions (secrets, voir le guide).
        val ks = System.getenv("JARVIS_KEYSTORE")
        if (ks != null && file(ks).exists()) {
            create("release") {
                storeFile = file(ks)
                storePassword = System.getenv("JARVIS_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("JARVIS_KEY_ALIAS") ?: "jarvis"
                keyPassword = System.getenv("JARVIS_KEYSTORE_PASSWORD")
            }
        }
        // Clé fixe incluse dans le projet : chaque nouvelle version s'installe par-dessus l'ancienne.
        create("stable") {
            storeFile = file("jarvis-debug.keystore")
            storePassword = "android"
            keyAlias = "jarvis"
            keyPassword = "android"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("stable")
        }
        debug {
            signingConfig = signingConfigs.getByName("stable")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    androidResources {
        noCompress += "onnx"
    }
}

dependencies {
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.20.0")
}
