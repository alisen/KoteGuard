# SwiftUI Patterns

Best-practice SwiftUI patterns for Copilot agents working on iOS projects.

---

## State Management

### Prefer `@Observable` (iOS 17+) over `ObservableObject`

```swift
// Modern (iOS 17+)
@Observable
class CounterViewModel {
    var count = 0
    func increment() { count += 1 }
}

// Consume in a View — no property wrapper needed
struct CounterView: View {
    var model: CounterViewModel
    var body: some View {
        Button("\(model.count)") { model.increment() }
    }
}
```

For iOS 16 and below, use `ObservableObject` + `@Published` + `@StateObject` / `@ObservedObject`.

### Use `@State` for local, ephemeral view state only

```swift
struct ToggleView: View {
    @State private var isOn = false
    var body: some View {
        Toggle("Feature", isOn: $isOn)
    }
}
```

Never lift `@State` up to a parent or share it across views — use a shared `@Observable` model instead.

---

## Navigation

### Use `NavigationStack` (not `NavigationView`) for iOS 16+

```swift
NavigationStack(path: $path) {
    ContentView()
        .navigationDestination(for: Route.self) { route in
            route.view
        }
}
```

### Type-safe routing with enums

```swift
enum Route: Hashable {
    case detail(Item)
    case settings
}
```

---

## Scene Lifecycle

### Handle scene phase changes with `@Environment(\.scenePhase)`

```swift
@main
struct MyApp: App {
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup { ContentView() }
            .onChange(of: scenePhase) { _, newPhase in
                if newPhase == .background { saveState() }
            }
    }
}
```

---

## Performance Rules

- Use `LazyVStack` / `LazyHStack` for lists longer than ~20 items
- Avoid recomputing heavy values in `body` — move them to the view model
- Use `task(id:)` for async work that should restart when an `id` changes
- Prefer `Equatable` conformance on models to prevent unnecessary redraws

---

## Do NOT

- Do not use `UIKit` view controllers directly unless bridging with `UIViewControllerRepresentable`
- Do not store `@Binding` in view models — pass values as closures instead
- Do not perform network calls inside `body` — use `.task { }` or `.onAppear { }`
