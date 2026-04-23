# XCTest & iOS Testing

Best-practice XCTest, async testing, and snapshot testing patterns for iOS agents.

---

## Unit Testing with XCTest

### Basic test structure

```swift
import XCTest
@testable import MyApp

final class UserViewModelTests: XCTestCase {
    var sut: UserViewModel!

    override func setUp() {
        super.setUp()
        sut = UserViewModel(repository: MockUserRepository())
    }

    override func tearDown() {
        sut = nil
        super.tearDown()
    }

    func test_loadUser_setsName() async throws {
        // Arrange — already done in setUp

        // Act
        try await sut.load(userId: "u1")

        // Assert
        XCTAssertEqual(sut.user?.name, "Alice")
    }
}
```

---

## Async Testing

### Use `async throws` test functions (Xcode 13.2+)

```swift
func test_fetchItems_returnsNonEmpty() async throws {
    let items = try await sut.fetchItems()
    XCTAssertFalse(items.isEmpty)
}
```

### Test Actor-isolated code with `@MainActor`

```swift
@MainActor
func test_publishedProperty_updatesOnLoad() async throws {
    await sut.load()
    XCTAssertFalse(sut.items.isEmpty)
}
```

### Use `XCTestExpectation` only when bridging callback APIs

```swift
func test_legacyCallback() {
    let exp = expectation(description: "callback fired")
    sut.legacyLoad { result in
        XCTAssertNotNil(result)
        exp.fulfill()
    }
    waitForExpectations(timeout: 2)
}
```

---

## Mocking Dependencies

Prefer protocol-based mocking over subclassing:

```swift
protocol UserRepository {
    func fetch(id: String) async throws -> User
}

final class MockUserRepository: UserRepository {
    var stubbedUser: User?
    func fetch(id: String) async throws -> User {
        guard let user = stubbedUser else { throw TestError.noStub }
        return user
    }
}
```

---

## Snapshot Testing (SnapshotTesting library)

```swift
import SnapshotTesting

final class ProfileViewSnapshotTests: XCTestCase {
    func test_profileView_renders() {
        let view = ProfileView(user: .fixture)
        assertSnapshot(of: view, as: .image(layout: .device(config: .iPhone13)))
    }
}
```

- Store snapshots in `__Snapshots__/` next to the test file
- Run with `record: true` to generate new snapshots, then commit them
- Always re-record when intentional UI changes are made

---

## Performance Testing

```swift
func test_sortPerformance() {
    let items = (0..<1000).map { Item(id: $0) }
    measure {
        _ = items.sorted { $0.id < $1.id }
    }
}
```

---

## Do NOT

- Do not share mutable state between tests — use `setUp` / `tearDown`
- Do not use `sleep()` — use `XCTestExpectation` or async/await instead
- Do not hardcode file paths in tests — use `Bundle.module` for test resources
- Do not leave `record: true` in snapshot tests before committing — snapshots will always pass
