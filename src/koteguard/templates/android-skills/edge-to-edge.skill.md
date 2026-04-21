# Edge-to-Edge Display

Best practices for implementing edge-to-edge display on Android (API 29+, enforced API 35+).

## Overview

Edge-to-edge allows your app content to draw behind system bars (status bar, navigation bar), creating an immersive experience. As of Android 15 (API 35), edge-to-edge is enforced for apps targeting API 35+.

## Enabling Edge-to-Edge

```kotlin
// In your Activity.onCreate() – call BEFORE setContent
override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    enableEdgeToEdge()  // androidx.activity:activity-ktx
    setContent {
        MyAppTheme {
            // ...
        }
    }
}
```

## Handling Insets in Compose

```kotlin
// Apply window insets to your root scaffold
Scaffold(
    modifier = Modifier.fillMaxSize(),
) { innerPadding ->
    // innerPadding already includes insets when using Scaffold
    Content(modifier = Modifier.padding(innerPadding))
}

// For custom layouts, use windowInsetsPadding:
Box(
    modifier = Modifier
        .fillMaxSize()
        .windowInsetsPadding(WindowInsets.systemBars)
) {
    // content
}

// Status bar only:
Box(modifier = Modifier.statusBarsPadding()) { ... }

// Navigation bar only:
Box(modifier = Modifier.navigationBarsPadding()) { ... }

// IME (keyboard) insets:
Box(modifier = Modifier.imePadding()) { ... }
```

## Best Practices

1. **Use `enableEdgeToEdge()`** from `androidx.activity:activity-ktx` – do NOT use `WindowCompat.setDecorFitsSystemWindows(window, false)` directly
2. **Apply insets at the leaf level** – push inset padding down to the content that needs it
3. **Use `Scaffold`** – it handles insets automatically for top/bottom bars
4. **Test on API 29, 33, and 35** – behavior differs across versions
5. **Do not hardcode status bar height** – always use inset APIs
6. **Dark/light status bar icons** – use `enableEdgeToEdge(statusBarStyle = SystemBarStyle.auto(...))` to control icon color

## Dependency

```kotlin
// build.gradle.kts (app)
dependencies {
    implementation("androidx.activity:activity-ktx:1.9.+")
    implementation("androidx.core:core-ktx:1.13.+")
}
```

## Migration from WindowCompat

Replace:
```kotlin
WindowCompat.setDecorFitsSystemWindows(window, false)
```
With:
```kotlin
enableEdgeToEdge()
```
