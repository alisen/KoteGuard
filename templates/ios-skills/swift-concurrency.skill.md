# Swift Concurrency

Best-practice async/await and structured concurrency patterns for iOS agents.

---

## Core Rules

### Always prefer `async/await` over callbacks and `DispatchQueue`

```swift
// Good
func fetchUser(id: String) async throws -> User {
    let (data, _) = try await URLSession.shared.data(from: url)
    return try JSONDecoder().decode(User.self, from: data)
}

// Bad — do not use
URLSession.shared.dataTask(with: url) { data, _, error in ... }.resume()
```

### Call async functions from Tasks or within other async contexts

```swift
// In a SwiftUI view
.task {
    do {
        user = try await fetchUser(id: userId)
    } catch {
        errorMessage = error.localizedDescription
    }
}
```

---

## Actors for Shared Mutable State

Use `actor` to protect shared mutable state across concurrent tasks:

```swift
actor DataCache {
    private var store: [String: Data] = [:]

    func set(_ data: Data, for key: String) {
        store[key] = data
    }

    func get(for key: String) -> Data? {
        store[key]
    }
}
```

Use `@MainActor` to guarantee UI updates happen on the main thread:

```swift
@MainActor
class ViewModel: ObservableObject {
    @Published var items: [Item] = []

    func load() async {
        items = await repository.fetchAll()
    }
}
```

---

## Structured Concurrency

### Use `async let` for parallel independent work

```swift
async let profile = fetchProfile(userId)
async let posts = fetchPosts(userId)
let (p, ps) = try await (profile, posts)
```

### Use `withTaskGroup` for dynamic parallelism

```swift
let results = try await withThrowingTaskGroup(of: Item.self) { group in
    for id in ids {
        group.addTask { try await fetchItem(id) }
    }
    return try await group.reduce(into: []) { $0.append($1) }
}
```

---

## Cancellation

Always check `Task.isCancelled` in long-running loops and respect cancellation:

```swift
func processItems(_ items: [Item]) async throws {
    for item in items {
        try Task.checkCancellation()
        await process(item)
    }
}
```

---

## AsyncStream for Live Data

```swift
func temperatureStream() -> AsyncStream<Double> {
    AsyncStream { continuation in
        let timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { _ in
            continuation.yield(readTemperature())
        }
        continuation.onTermination = { _ in timer.invalidate() }
    }
}
```

---

## Do NOT

- Do not use `DispatchQueue.main.async` to update UI — use `@MainActor` instead
- Do not create unstructured `Task { }` inside `@Observable` models without storing the handle (causes leaks)
- Do not mix `async/await` with Combine Publishers unless bridging via `AsyncPublisher`
- Do not catch all errors with `catch {}` — handle or rethrow specifically
