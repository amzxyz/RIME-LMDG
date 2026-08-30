plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.wanxiangupdater"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.wanxiangupdater"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "2.2"

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    signingConfigs {
        create("release") {
            val keystoreFile = System.getenv("KEYSTORE_FILE")
            if (keystoreFile != null) {
                storeFile = file(keystoreFile)
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KEY_ALIAS")
                keyPassword = System.getenv("KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (System.getenv("KEYSTORE_FILE") != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    buildFeatures {
        compose = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.8"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}


// 仓库结构：
// <repo>/pinyin_bridge.py
// <repo>/pypinyin/
// <repo>/wanxiang-updater/app/...
//
// 不直接把仓库根目录交给 Chaquopy，而是在构建前仅同步 Android 需要的两项。
val wanxiangRepoRoot = rootProject.projectDir.parentFile
val generatedPythonDir = layout.buildDirectory.dir("generated/wanxiangPython")

val syncWanxiangPython by tasks.registering(Sync::class) {
    from(wanxiangRepoRoot) {
        include("pinyin_bridge.py")
        include("pypinyin/**")
    }
    into(generatedPythonDir)
}

chaquopy {
    defaultConfig {
        version = "3.10"
    }

    sourceSets {
        getByName("main") {
            setSrcDirs(listOf(generatedPythonDir.get().asFile))
        }
    }
}

// 确保 Chaquopy 的任何 Python 构建任务开始前，根目录源码已同步。
tasks.configureEach {
    if (name != syncWanxiangPython.name && name.contains("Python")) {
        dependsOn(syncWanxiangPython)
    }
}
tasks.named("preBuild").configure {
    dependsOn(syncWanxiangPython)
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation(platform("androidx.compose:compose-bom:2023.10.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    implementation("androidx.documentfile:documentfile:1.0.1")
}
