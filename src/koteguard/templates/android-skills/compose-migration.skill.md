# Jetpack Compose Migration

Best practices for migrating from View-based UI to Jetpack Compose.

## Overview

Compose is Android's modern declarative UI toolkit. Migration is incremental – you can mix Compose and Views using `ComposeView` and `AndroidView` interop.

## Migration Strategy

### Phase 1: Leaf Screens First

Migrate simple, self-contained screens first (settings, detail views, dialogs) before complex screens (home, main).

```kotlin
// In your existing XML layout, add ComposeView:
// res/layout/fragment_settings.xml
<androidx.compose.ui.platform.ComposeView
    android:id="@+id/compose_view"
    android:layout_width="match_parent"
    android:layout_height="match_parent" />

// In your Fragment:
override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
    view.findViewById<ComposeView>(R.id.compose_view).setContent {
        MaterialTheme {
            SettingsScreen()
        }
    }
}
```

### Phase 2: Fragment → Composable

Once all screens are Compose, replace Fragment navigation with Navigation Compose.

### Phase 3: Remove View System

Remove XML layouts, Fragments (if all replaced), and View-system theme attributes.

## Key Patterns

### ViewModel Integration

```kotlin
@Composable
fun ProfileScreen(viewModel: ProfileViewModel = viewModel()) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    ProfileContent(uiState = uiState)
}
```

### Material 3 Theme

```kotlin
@Composable
fun MyAppTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = dynamicColorScheme(), // or lightColorScheme/darkColorScheme
        typography = AppTypography,
        content = content,
    )
}
```

### Lists (LazyColumn)

```kotlin
LazyColumn {
    items(items = list, key = { it.id }) { item ->
        ItemRow(item = item)
    }
}
```

### State Hoisting

```kotlin
// WRONG: state inside composable (not testable/reusable)
@Composable
fun Counter() {
    var count by remember { mutableIntStateOf(0) }
    Button(onClick = { count++ }) { Text("$count") }
}

// CORRECT: hoist state up
@Composable
fun Counter(count: Int, onIncrement: () -> Unit) {
    Button(onClick = onIncrement) { Text("$count") }
}
```

## Best Practices

1. **Hoist state** – keep composables stateless where possible
2. **Use `collectAsStateWithLifecycle`** – NOT `collectAsState` (lifecycle-aware)
3. **One `MaterialTheme` per app** – wrap at the root Activity/NavHost level
4. **Use `key` in `LazyColumn.items`** – prevents recomposition issues with moving items
5. **Avoid side effects in composables** – use `LaunchedEffect`, `SideEffect`, `DisposableEffect`
6. **Preview with `@Preview`** – create light/dark and multiple size previews

## Performance

- Use `remember` and `derivedStateOf` to minimize recomposition
- Use `Stable` / `Immutable` annotations on data classes passed to composables
- Profile with Compose Compiler metrics: `./gradlew assembleRelease -PcomposeCompilerReports=true`

## Forbidden Patterns

- Do NOT call `invalidate()` or `requestLayout()` from Compose
- Do NOT use `View.VISIBLE/GONE` inside composables – use `if` conditions
- Do NOT create `Composable` functions that return a value

## Dependencies

```kotlin
// build.gradle.kts (app)
dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.+")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
```
