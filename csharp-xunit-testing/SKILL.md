---
name: csharp-xunit-testing
description: |
  Generates comprehensive xUnit unit tests for C# code following Arrange-Act-Assert
  and Conga Revenue codebase conventions. Mocks all external dependencies via Moq,
  correlates tests to source structure, and covers success paths, failure paths,
  batch processing, and async patterns — all without touching production code.
---

# C# xUnit Unit Testing Skill

## The Core Idea

Standard test generation produces isolated, boilerplate tests with no context. This skill is different:

1. **Codebase-aware** — test names, namespace mirroring, and mock patterns follow conventions observed across Conga Revenue repositories (Renewal Worker, Asset API, Billing).
2. **Dependency-complete** — every external dependency (`ILogger`, `ITelemetryTracer`, `IConfiguration`) is mocked correctly in the constructor; no real services are used.
3. **Pattern-matched** — processor tests, data-access tests, and service-layer tests each have their own proven template drawn from the actual codebase.

> The LLM writes the tests; the developer reviews and adjusts only edge-case logic.

---

## Stack

| Concern | Library | Version |
|---------|---------|---------|
| **Test runner** | xUnit | v2.4.0+ |
| **Mocking** | Moq | v4.18.0+ |
| **Target framework** | .NET | 8.0 |
| **C# version** | — | 12.0 |

---

## ? Quick Start

```csharp
// Minimal template — copy, rename, fill in mocks
namespace [Namespace].Tests.[SubFolder]
{
    public class [ClassUnderTest]Tests
    {
        private readonly Mock<IDependency1> mockDependency1;
        private readonly Mock<IDependency2> mockDependency2;
        private readonly [ClassUnderTest] sut; // System Under Test

        public [ClassUnderTest]Tests()
        {
            mockDependency1 = new Mock<IDependency1>();
            mockDependency2 = new Mock<IDependency2>();
            sut = new [ClassUnderTest](mockDependency1.Object, mockDependency2.Object);
        }

        [Fact]
        public async Task MethodName_Scenario_ExpectedBehavior()
        {
            // Arrange
            mockDependency1.Setup(x => x.MethodCall(...)).ReturnsAsync(...);

            // Act
            var result = await sut.MethodUnderTest(...);

            // Assert
            Assert.Equal(expectedResult, result);
            mockDependency1.Verify(x => x.MethodCall(...), Times.Once);
        }
    }
}
```

---

## Naming Conventions

| Element | Pattern | Example |
|---------|---------|---------|
| Test method | `MethodName_Scenario_ExpectedBehavior` | `CreateRenewGroupsAsync_NoProductsFound_ReturnsZero` |
| Test class | `[ClassUnderTest]Tests` | `RenewGroupCreationServiceTests` |
| System under test variable | `sut` | `private readonly QuoteCreationProcessor sut` |

---

## Operations

### Generate — Common Patterns

**Theory (parameterized)** — use when the same logic applies across multiple inputs:

```csharp
[Theory]
[InlineData(0)]
[InlineData(1)]
[InlineData(5)]
public async Task MethodName_WithVariousInputs_HandlesCorrectly(int count)
{
    var items = CreateTestData(count);
    var result = await sut.Method(items);
    Assert.Equal(expectedValue, result);
}
```

**Exception** — verify the exact exception type thrown:

```csharp
[Fact]
public async Task MethodName_InvalidInput_ThrowsException()
{
    await Assert.ThrowsAsync<ArgumentNullException>(() => sut.Method(null));
}
```

**Async** — always `async Task`, always `await`:

```csharp
[Fact]
public async Task MethodName_Scenario_ExpectedBehavior()
{
    mockService.Setup(x => x.GetDataAsync()).ReturnsAsync(data);
    var result = await sut.ProcessDataAsync();
    Assert.NotNull(result);
}
```

---

### Generate — Processor (Renewal Worker Pattern)

When the target class is a processor (e.g. `QuoteCreationProcessor`, `AssetRenewalProcessor`):

1. Declare mocks for `IConfiguration`, `ILogger<T>`, `ITelemetryTracer`, and all domain services.
2. Call `SetupConfiguration()` in the constructor — processors read settings from `IConfigurationSection`.
3. Cover: valid input ? success, no assets ? early return, exception ? propagation.
4. Verify mock calls with `Times.Once` / `Times.Exactly(n)` after each Act.

```csharp
public class QuoteCreationProcessorTests
{
    private readonly Mock<IConfiguration>                   mockConfiguration;
    private readonly Mock<ILogger<QuoteCreationProcessor>>  mockLogger;
    private readonly Mock<ITelemetryTracer>                 mockTracer;
    private readonly Mock<IQuoteService>                    mockQuoteService;
    private readonly Mock<ICartService>                     mockCartService;
    private readonly Mock<IAssetService>                    mockAssetService;
    private readonly Mock<IRenewGroupDataAccess>            mockRenewGroupDataAccess;
    private readonly QuoteCreationProcessor sut;

    public QuoteCreationProcessorTests()
    {
        mockConfiguration        = new Mock<IConfiguration>();
        mockLogger               = new Mock<ILogger<QuoteCreationProcessor>>();
        mockTracer               = new Mock<ITelemetryTracer>();
        mockQuoteService         = new Mock<IQuoteService>();
        mockCartService          = new Mock<ICartService>();
        mockAssetService         = new Mock<IAssetService>();
        mockRenewGroupDataAccess = new Mock<IRenewGroupDataAccess>();
        SetupConfiguration();
        sut = new QuoteCreationProcessor(
            mockConfiguration.Object, mockLogger.Object, mockTracer.Object,
            mockQuoteService.Object /*, ... */);
    }

    private void SetupConfiguration()
    {
        var renewalConfig = new Dictionary<string, object>
        {
            { "MaxWaitTimeForPricing", "300000" },
            { "MaxNumberOfAssetsPerBatchForAssetRenewal", "500" }
        };
        var mockSection = new Mock<IConfigurationSection>();
        mockSection.Setup(x => x.Get<Dictionary<string, object>>()).Returns(renewalConfig);
        mockConfiguration.Setup(x => x.GetSection("RenewalConfig")).Returns(mockSection.Object);
    }

    [Fact]
    public async Task ProcessRenewalGroup_ValidInput_CreatesQuoteSuccessfully()
    {
        // Arrange
        var renewGroupAndItems = CreateTestRenewGroup();
        mockQuoteService.Setup(x => x.CreateQuotesAsync(It.IsAny<List<Proposal>>()))
            .ReturnsAsync(new List<Proposal> { new Proposal { Id = "quote-1" } });
        mockCartService.Setup(x => x.ActivateCartForQuoteAsync(It.IsAny<string>()))
            .ReturnsAsync(new ProductConfiguration { Id = "cart-1" });

        // Act
        var result = await sut.ProcessRenewalGroup(renewGroupAndItems, 1);

        // Assert
        Assert.True(result);
        mockQuoteService.Verify(x => x.CreateQuotesAsync(It.IsAny<List<Proposal>>()), Times.Once);
    }
}
```

---

### Generate — Data Access Layer

When the target class is a repository or data-access class:

1. Mock `IObjectDbRepository`, `ILogger<T>`, `ITelemetryTracer`, `IConfiguration`.
2. Test: valid ID ? entity returned, missing ID ? null/empty, repo throws ? exception propagated.
3. Verify the exact repository method and parameter signature.

```csharp
public class DataAccessTests
{
    private readonly Mock<IObjectDbRepository> mockRepository;
    private readonly Mock<ILogger<DataAccess>>  mockLogger;
    private readonly Mock<ITelemetryTracer>     mockTracer;
    private readonly Mock<IConfiguration>       mockConfiguration;
    private readonly DataAccess sut;

    public DataAccessTests()
    {
        mockRepository    = new Mock<IObjectDbRepository>();
        mockLogger        = new Mock<ILogger<DataAccess>>();
        mockTracer        = new Mock<ITelemetryTracer>();
        mockConfiguration = new Mock<IConfiguration>();
        sut = new DataAccess(mockTracer.Object, mockLogger.Object,
                             mockRepository.Object, mockConfiguration.Object);
    }

    [Fact]
    public async Task FindByIdAsync_ValidId_ReturnsEntity()
    {
        // Arrange
        var entityId       = "test-id";
        var expectedEntity = new Entity { Id = entityId };
        mockRepository
            .Setup(x => x.FindObjects<Entity>(
                It.IsAny<string>(), It.IsAny<string>(), It.IsAny<List<string>>()))
            .ReturnsAsync(new List<Entity> { expectedEntity });

        // Act
        var result = await sut.FindByIdAsync(entityId);

        // Assert
        Assert.NotNull(result);
        Assert.Equal(entityId, result.Id);
        mockRepository.Verify(x => x.FindObjects<Entity>(
            It.IsAny<string>(), It.IsAny<string>(), It.IsAny<List<string>>()), Times.Once);
    }
}
```

---

### Generate — Service Layer

When the target class orchestrates between data-access and domain logic:

1. Mock `IDataAccess`, `ILogger<T>`, `ITelemetryTracer`.
2. Test: success flow ? all dependencies called in order, partial failure ? correct short-circuit.
3. Verify all `Save` / `Update` calls were made (not just the return value).

```csharp
public class ServiceTests
{
    private readonly Mock<IDataAccess>      mockDataAccess;
    private readonly Mock<ILogger<Service>> mockLogger;
    private readonly Mock<ITelemetryTracer> mockTracer;
    private readonly Service sut;

    public ServiceTests()
    {
        mockDataAccess = new Mock<IDataAccess>();
        mockLogger     = new Mock<ILogger<Service>>();
        mockTracer     = new Mock<ITelemetryTracer>();
        sut = new Service(mockTracer.Object, mockLogger.Object, mockDataAccess.Object);
    }

    [Fact]
    public async Task ProcessAsync_ValidInput_ReturnsSuccess()
    {
        // Arrange
        var input    = new ProcessRequest { Id = "test-id" };
        var entities = new List<Entity> { new Entity { Id = "entity-1" } };
        mockDataAccess.Setup(x => x.FindEntitiesAsync(It.IsAny<List<string>>()))
            .ReturnsAsync(entities);
        mockDataAccess.Setup(x => x.SaveAsync(It.IsAny<List<Entity>>()))
            .Returns(Task.CompletedTask);

        // Act
        var result = await sut.ProcessAsync(input);

        // Assert
        Assert.True(result.Success);
        mockDataAccess.Verify(x => x.FindEntitiesAsync(It.IsAny<List<string>>()), Times.Once);
        mockDataAccess.Verify(x => x.SaveAsync(It.IsAny<List<Entity>>()), Times.Once);
    }
}
```

---

### Generate — Complex Scenarios

**Batch processing** — verify call count equals `ceil(total / batchSize)`:

```csharp
[Fact]
public async Task RenewAssetsAndTriggerPricing_LargeAssetList_ProcessesInBatches()
{
    var assetIds = Enumerable.Range(1, 1500).Select(i => $"asset-{i}").ToList();
    mockAssetService.Setup(x => x.RenewAssetsAsync(
        It.IsAny<string>(), It.IsAny<RenewAssetsRequest>()))
        .ReturnsAsync(new List<LineItem> { new LineItem { Id = "line-1" } });

    var result = await sut.RenewAssetsAndTriggerPricing("cart-1", CreateTestRenewGroup(assetIds), 500, 1000);

    Assert.NotNull(result);
    mockAssetService.Verify(x => x.RenewAssetsAsync(
        It.IsAny<string>(), It.IsAny<RenewAssetsRequest>()), Times.Exactly(3)); // 1500 / 500
}
```

**Dictionary returns** — verify key presence and count:

```csharp
[Fact]
public async Task Method_ReturnsCorrectDictionary()
{
    var expectedDict = new Dictionary<string, List<Item>>
    {
        { "key1", new List<Item> { new Item { Id = "1" } } },
        { "key2", new List<Item> { new Item { Id = "2" } } }
    };
    mockService.Setup(x => x.GetDictionaryAsync()).ReturnsAsync(expectedDict);

    var result = await sut.ProcessDictionaryAsync();

    Assert.Equal(2, result.Count);
    Assert.Contains("key1", result.Keys);
}
```

**Parallel processing** — verify all groups were processed:

```csharp
[Fact]
public async Task ProcessRenewalGroups_MultipleGroups_ProcessesAll()
{
    var groups = CreateTestGroups(5);
    mockProcessor.Setup(x => x.ProcessGroup(It.IsAny<RenewGroup>()))
        .Returns(Task.FromResult(true));

    await sut.ProcessRenewalGroups("job-1", groups);

    mockProcessor.Verify(x => x.ProcessGroup(It.IsAny<RenewGroup>()), Times.Exactly(5));
}
```

**Configuration-driven logic** — inject config value, assert it was applied:

```csharp
[Fact]
public async Task Method_UsesConfigurationValue()
{
    var renewalConfig = new Dictionary<string, object> { { "MaxBatchSize", "500" } };
    var mockSection   = new Mock<IConfigurationSection>();
    mockSection.Setup(x => x.Get<Dictionary<string, object>>()).Returns(renewalConfig);
    mockConfiguration.Setup(x => x.GetSection("RenewalConfig")).Returns(mockSection.Object);

    var result = await sut.ProcessBatchAsync();

    Assert.Equal(500, result.BatchSize);
}
```

**Notification scenarios** — verify action type on the notification request:

```csharp
[Fact]
public async Task ProcessGroup_Success_SendsNotification()
{
    var settings = CreateTestSettings();
    settings.SendRenewalQuoteCreateNotification = true;
    mockNotificationService.Setup(x => x.SendNotificationAsync(It.IsAny<NotificationRequest>()))
        .ReturnsAsync(new NotificationResponse { StatusCode = System.Net.HttpStatusCode.OK });

    await sut.ProcessRenewalGroup(renewGroup, 1);

    mockNotificationService.Verify(x => x.SendNotificationAsync(
        It.Is<NotificationRequest>(r => r.Action == NotificationAction.QuoteCreationSuccess)),
        Times.Once);
}
```

**Renewal processor with job status** — verify job status updated to Completed:

```csharp
[Fact]
public async Task Processor_ValidRequest_UpdatesJobStatus()
{
    var jobId   = "job-123";
    var request = CreateTestRequest();
    mockRenewalJobManager.Setup(x => x.GetJobStatusAsync(jobId))
        .ReturnsAsync(new CPQJobStatus { Id = jobId });
    mockRenewalJobManager.Setup(x => x.UpdateJobDetailsAsync(
        It.IsAny<CPQJobStatus>(), It.IsAny<List<string>>()))
        .ReturnsAsync(true);

    var result = await sut.ProcessAsync(jobId, request);

    Assert.True(result);
    mockRenewalJobManager.Verify(
        x => x.UpdateJobDetailsAsync(
            It.Is<CPQJobStatus>(s => s.Status == "Completed"),
            It.IsAny<List<string>>()),
        Times.Once);
}
```

---

## Test Generation Constraints

### Must Do
- ? Use `MethodName_Scenario_ExpectedBehavior` naming for every test
- ? Arrange-Act-Assert structure — one comment block per phase
- ? `async Task` return type for all tests calling async methods
- ? Mock every external dependency — no real services, no real I/O
- ? Verify mock calls with `Times` constraints after the result assertion
- ? One logical outcome per test — group related assertions, not unrelated scenarios
- ? Use `[Theory]` + `[InlineData]` when the same logic applies to multiple inputs
- ? Assert on the result first, then verify mocks
- ? Place helper/builder methods at the bottom of the test class
- ? Mirror source structure: `Processors/QuoteCreation.cs` ? `Processors/QuoteCreationTests.cs`

### Must Not Do
- ? Do not test implementation details — test observable behavior, not internal state
- ? Do not over-mock — only mock external dependencies, not value objects or DTOs
- ? Do not use real HTTP clients, databases, or file system access
- ? Do not ignore `await` — every async call must be awaited in tests
- ? Do not use magic numbers — use named variables or constants
- ? Do not test multiple unrelated scenarios in one test
- ? Do not leave `IDisposable` resources without cleanup

---

## Test Data Builders

Place all builder methods at the bottom of the test class:

```csharp
private AssetRenewalGroupAndItems CreateTestRenewGroup(List<string> assetIds = null)
{
    assetIds ??= new List<string> { "asset-1", "asset-2" };
    return new AssetRenewalGroupAndItems
    {
        AssetRenewGroup = new AssetRenewGroup
        {
            Id = "group-1", GroupName = "Test Group",
            Account = new LookupObject("acc-1", "Account 1"), IsAutoRenew = false
        },
        AssetRenewGroupItems = assetIds.Select((id, i) => new AssetRenewGroupItem
        {
            Id = $"item-{i}",
            AssetLineItem = new AssetLineItem { Id = id, Name = $"Asset {id}" }
        }).ToList()
    };
}

private List<AssetLineItem> CreateTestAssets(int count) =>
    Enumerable.Range(0, count)
        .Select(i => new AssetLineItem
        {
            Id      = $"asset-{i}",
            Name    = $"Asset {i}",
            Account = new LookupObject($"acc-{i}", $"Account {i}")
        }).ToList();

private Assets CreateTestSettings(int? maxItems = null, int? leadTime = null) =>
    new Assets
    {
        MaxRenewalLineItemPerCart           = maxItems ?? 500,
        RenewalLeadTime                    = leadTime ?? 30,
        RenewalGroupFields                 = "Account,PriceList",
        RenewalGroupAttributes             = "",
        SendRenewalQuoteCreateNotification = true
    };
```

---

## Mock Patterns Reference

| Scenario | Pattern |
|----------|---------|
| Simple sync return | `mock.Setup(x => x.Method(It.IsAny<T>())).Returns(value)` |
| Async return | `mock.Setup(x => x.MethodAsync(It.IsAny<T>())).ReturnsAsync(value)` |
| Multiple setups | Chain `.Setup(...)` calls — last matching setup wins |
| Conditional input | `It.Is<T>(x => x.StartsWith("test"))` |
| Capture argument | `.Callback<T>(arg => captured = arg).ReturnsAsync(true)` |
| Void async | `.Returns(Task.CompletedTask)` |
| Throw exception | `.ThrowsAsync<InvalidOperationException>()` |
| Verify once | `mock.Verify(x => x.Method(...), Times.Once)` |
| Verify never | `mock.Verify(x => x.Method(...), Times.Never)` |
| Verify exact count | `mock.Verify(x => x.Method(...), Times.Exactly(3))` |
| Verify exact param | `mock.Verify(x => x.Method("exact"), Times.Once)` |

---

## Common Mock Setups

### ILogger — verify error logging

```csharp
mockLogger.Verify(
    x => x.Log(
        LogLevel.Error,
        It.IsAny<EventId>(),
        It.Is<It.IsAnyType>((v, t) => true),
        It.IsAny<Exception>(),
        It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
    Times.Once);
```

### ITelemetryTracer — return a mock span

```csharp
var mockSpan = new Mock<ISpan>();
mockTracer
    .Setup(x => x.StartActiveSpan(
        It.IsAny<string>(), It.IsAny<SpanKind>(), It.IsAny<TagsCollection>()))
    .Returns(mockSpan.Object);
```

### IConfiguration — section with dictionary values

```csharp
private void SetupConfiguration(Dictionary<string, object> config)
{
    var mockSection = new Mock<IConfigurationSection>();
    mockSection.Setup(x => x.Get<Dictionary<string, object>>()).Returns(config);
    mockConfiguration.Setup(x => x.GetSection("RenewalConfig")).Returns(mockSection.Object);
}
```

### Complex return type

```csharp
mockService
    .Setup(x => x.GetComplexObjectAsync())
    .ReturnsAsync(new ComplexObject
    {
        Property1    = "value1",
        NestedObject = new NestedObject { Id = "nested-id" },
        Collection   = new List<Item> { new Item { Id = "item-1" } }
    });
```

---

## Assertion Reference

| Need | Assertion |
|------|-----------|
| Equal value | `Assert.Equal(expected, actual)` |
| Not equal | `Assert.NotEqual(expected, actual)` |
| Null | `Assert.Null(result)` |
| Not null | `Assert.NotNull(result)` |
| True / False | `Assert.True(cond)` / `Assert.False(cond)` |
| Collection count | `Assert.Equal(n, result.Count)` |
| Contains item | `Assert.Contains(result, x => x.Id == id)` |
| Empty | `Assert.Empty(result)` |
| Not empty | `Assert.NotEmpty(result)` |
| All match predicate | `Assert.All(result, x => Assert.NotNull(x.Name))` |
| Throws async | `await Assert.ThrowsAsync<Ex>(() => sut.Method())` |

---

## Design Philosophy

> "One test, one reason to fail. Mock what you don't own. Assert what you care about."

| Layer | What to test | What NOT to test |
|-------|-------------|------------------|
| **Processor** | Orchestration order, early-exit logic, job-status updates | Internal loops, private methods |
| **Service** | Domain rules, dependency call sequencing, error propagation | Framework internals, EF query shape |
| **Data Access** | Query construction, result mapping, null/empty handling | ORM internals, DB schema |
| **Naming** | `MethodName_Scenario_ExpectedBehavior` for every test | Free-form names, `Test1`, `ShouldWork` |
| **Structure** | AAA with explicit comments, mocks verified after result | Mixed Act+Assert, no phases |

---

## Quick Reference

### xUnit Attributes

| Attribute | Purpose |
|-----------|---------|
| `[Fact]` | Single test case |
| `[Theory]` | Parameterized test — requires data source |
| `[InlineData(...)]` | Inline data row for `[Theory]` |
| `[Skip("reason")]` | Skip temporarily with explanation |
| `[Trait("Category", "Integration")]` | Categorise for filtered runs |

### Moq `Times`

| Value | Meaning |
|-------|---------|
| `Times.Never` | Must not be called |
| `Times.Once` | Exactly once |
| `Times.Exactly(n)` | Exactly n times |
| `Times.AtLeast(n)` | n or more |
| `Times.AtMost(n)` | n or fewer |
| `Times.Between(min, max, Range.Inclusive)` | Between min and max |

### `It` Matchers

| Matcher | Matches |
|---------|---------|
| `It.IsAny<T>()` | Any value of type T |
| `It.Is<T>(x => cond)` | Values satisfying predicate |
| `It.IsIn(collection)` | Values present in collection |
| `It.IsRegex(pattern)` | Strings matching regex |
| `It.IsNotNull<T>()` | Non-null value of type T |
