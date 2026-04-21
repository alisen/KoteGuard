# Navigation 3

Best practices for the Jetpack Navigation 3 library in Android Compose applications.

## Overview

Navigation 3 is the latest iteration of Jetpack Navigation, designed from the ground up for Compose. It uses a type-safe API and eliminates XML nav graphs entirely.

## Key APIs

```kotlin
// Define type-safe destinations
@Serializable
object HomeRoute

@Serializable
data class DetailRoute(val id: String)

// Create a NavController
val navController = rememberNavController()

// NavHost with type-safe routes
NavHost(navController = navController, startDestination = HomeRoute) {
    composable<HomeRoute> { HomeScreen(navController) }
    composable<DetailRoute> { backStackEntry ->
        val route: DetailRoute = backStackEntry.toRoute()
        DetailScreen(id = route.id)
    }
}
```

## Best Practices

1. **Always use type-safe routes** – `@Serializable` data classes or objects, never strings
2. **Define routes in a sealed interface** for discoverability:
   ```kotlin
   sealed interface AppRoute {
       @Serializable data object Home : AppRoute
       @Serializable data class Detail(val id: String) : AppRoute
   }
   ```
3. **Pass data as route args** – only primitive/serializable types
4. **Use `popBackStack()` with typed route** to pop to a specific destination
5. **Avoid global NavController references** – pass down via function parameters or CompositionLocal
6. **Test navigation** with `TestNavController` – do not test composables with navigation directly

## Forbidden Patterns

- Do NOT use string-based route definitions (deprecated)
- Do NOT navigate from ViewModel directly – use callbacks/events
- Do NOT store NavController in a ViewModel

## Dependency

```kotlin
// build.gradle.kts (app)
dependencies {
    implementation("androidx.navigation:navigation-compose:2.8.+")
}
```
