# C# xUnit Unit Testing Skill

This skill helps generate comprehensive xUnit unit tests for C# code following industry best practices and patterns observed in the Conga Revenue codebase.

## Framework & Libraries

- **Testing Framework:** xUnit (v2.4.0+)
- **Mocking Framework:** Moq (v4.18.0+)
- **Target Framework:** .NET 8.0
- **C# Version:** 12.0

## Test Class Structure

### Basic Template

```csharp
namespace [Namespace].Tests.[SubFolder]
{
    public class [ClassUnderTest]Tests
    {
        private readonly Mock<IDependency1> mockDependency1;
        private readonly Mock<IDependency2> mockDependency2;
        private readonly [ClassUnderTest] sut; // System Under Test

        public [ClassUnderTest]Tests()
        {
            // Arrange - Setup mocks
            mockDependency1 = new Mock<IDependency1>();
            mockDependency2 = new Mock<IDependency2>();
            
            // Create system under test
            sut = new [ClassUnderTest](mockDependency1.Object, mockDependency2.Object);
        }

        [Fact]
        public async Task MethodName_Scenario_ExpectedBehavior()
        {
            // Arrange
            var expectedResult = ...;
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

## Naming Conventions

### Test Method Names
Use the pattern: `MethodName_Scenario_ExpectedBehavior`

**Examples:**
- `CreateRenewGroupsAsync_NoProductsFound_ReturnsZero`
- `FindAssetLineItemsForProductAsync_ValidInput_ReturnsAssetLineItems`
- `ProcessAccountAssetsAsync_NullFilteredAssets_ReturnsZero`
- `UpdateRenewGroupsAsync_ExceptionThrown_PropagatesException`

### Test Class Names
- Test class name = `[ClassUnderTest]Tests`
- Example: `RenewGroupCreationServiceTests`, `AssetLineItemsDataAccessTests`

## Common Test Patterns

### 1. Theory Tests (Parameterized Tests)

Use `[Theory]` with `[InlineData]` for testing multiple scenarios:

```csharp
[Theory]
[InlineData(0)]
[InlineData(1)]
[InlineData(5)]
public async Task MethodName_WithVariousInputs_HandlesCorrectly(int count)
{
    // Arrange
    var items = CreateTestData(count);
    
    // Act
    var result = await sut.Method(items);
    
    // Assert
    Assert.Equal(expectedValue, result);
}
```

### 2. Exception Testing

```csharp
[Fact]
public async Task MethodName_InvalidInput_ThrowsException()
{
    // Arrange
    var invalidInput = null;
    
    // Act & Assert
    await Assert.ThrowsAsync<ArgumentNullException>(() => 
        sut.Method(invalidInput));
}
```

### 3. Async Method Testing

Always use `async Task` return type and `await` for async methods:

```csharp
[Fact]
public async Task MethodName_Scenario_ExpectedBehavior()
{
    // Arrange
    mockService.Setup(x => x.GetDataAsync()).ReturnsAsync(data);
    
    // Act
    var result = await sut.ProcessDataAsync();
    
    // Assert
    Assert.NotNull(result);
}
```

### 4. Mock Setup Patterns

#### Simple Return
```csharp
mockRepository.Setup(x => x.FindById(It.IsAny<string>())).Returns(entity);
```

#### Async Return
```csharp
mockRepository.Setup(x => x.FindByIdAsync(It.IsAny<string>())).ReturnsAsync(entity);
```

#### Multiple Setups
```csharp
mockService.Setup(x => x.Method1()).ReturnsAsync(result1);
mockService.Setup(x => x.Method2()).ReturnsAsync(result2);
mockService.Setup(x => x.Method3()).Returns(Task.CompletedTask);
```

#### Conditional Setup
```csharp
mockService.Setup(x => x.GetData(It.Is<string>(s => s.StartsWith("test"))))
    .ReturnsAsync(testData);
```

#### Callback Setup
```csharp
mockService.Setup(x => x.ProcessData(It.IsAny<Data>()))
    .Callback<Data>(data => capturedData = data)
    .ReturnsAsync(true);
```

### 5. Verification Patterns

#### Verify Method Called
```csharp
mockService.Verify(x => x.Method(It.IsAny<string>()), Times.Once);
```

#### Verify Method Never Called
```csharp
mockService.Verify(x => x.Method(It.IsAny<string>()), Times.Never);
```

#### Verify with Exact Parameters
```csharp
mockService.Verify(x => x.Method("exactValue"), Times.Once);
```

#### Verify Multiple Calls
```csharp
mockService.Verify(x => x.Method1(), Times.Once);
mockService.Verify(x => x.Method2(), Times.Exactly(2));
```

### 6. Collection Assertions

```csharp
// Count
Assert.Equal(expectedCount, result.Count);

// Contains
Assert.Contains(result, item => item.Id == expectedId);

// Empty/NotEmpty
Assert.Empty(result);
Assert.NotEmpty(result);

// All items match condition
Assert.All(result, item => Assert.NotNull(item.Name));
```

### 7. Null Checks

```csharp
Assert.Null(result);
Assert.NotNull(result);
```

### 8. Boolean Assertions

```csharp
Assert.True(condition);
Assert.False(condition);
```

## Testing Services with Dependencies

### Processor Testing (Renewal Worker Pattern)

```csharp
public class QuoteCreationProcessorTests
{
    private readonly Mock<IConfiguration> mockConfiguration;
    private readonly Mock<ILogger<QuoteCreationProcessor>> mockLogger;
    private readonly Mock<ITelemetryTracer> mockTracer;
    private readonly Mock<IQuoteService> mockQuoteService;
    private readonly Mock<ICartService> mockCartService;
    private readonly Mock<IAssetService> mockAssetService;
    private readonly Mock<IRenewGroupDataAccess> mockRenewGroupDataAccess;
    private readonly QuoteCreationProcessor sut;

    public QuoteCreationProcessorTests()
    {
        mockConfiguration = new Mock<IConfiguration>();
        mockLogger = new Mock<ILogger<QuoteCreationProcessor>>();
        mockTracer = new Mock<ITelemetryTracer>();
        mockQuoteService = new Mock<IQuoteService>();
        mockCartService = new Mock<ICartService>();
        mockAssetService = new Mock<IAssetService>();
        mockRenewGroupDataAccess = new Mock<IRenewGroupDataAccess>();
        
        // Setup configuration
        SetupConfiguration();
        
        sut = new QuoteCreationProcessor(
            mockConfiguration.Object,
            mockLogger.Object,
            mockTracer.Object,
            mockQuoteService.Object,
            // ... other dependencies
        );
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

### Data Access Layer Testing

```csharp
public class DataAccessTests
{
    private readonly Mock<IObjectDbRepository> mockRepository;
    private readonly Mock<ILogger<DataAccess>> mockLogger;
    private readonly Mock<ITelemetryTracer> mockTracer;
    private readonly Mock<IConfiguration> mockConfiguration;
    private readonly DataAccess sut;

    public DataAccessTests()
    {
        mockRepository = new Mock<IObjectDbRepository>();
        mockLogger = new Mock<ILogger<DataAccess>>();
        mockTracer = new Mock<ITelemetryTracer>();
        mockConfiguration = new Mock<IConfiguration>();
        
        sut = new DataAccess(
            mockTracer.Object,
            mockLogger.Object,
            mockRepository.Object,
            mockConfiguration.Object);
    }

    [Fact]
    public async Task FindByIdAsync_ValidId_ReturnsEntity()
    {
        // Arrange
        var entityId = "test-id";
        var expectedEntity = new Entity { Id = entityId };
        mockRepository
            .Setup(x => x.FindObjects<Entity>(
                It.IsAny<string>(), 
                It.IsAny<string>(), 
                It.IsAny<List<string>>()))
            .ReturnsAsync(new List<Entity> { expectedEntity });

        // Act
        var result = await sut.FindByIdAsync(entityId);

        // Assert
        Assert.NotNull(result);
        Assert.Equal(entityId, result.Id);
        mockRepository.Verify(x => x.FindObjects<Entity>(
            It.IsAny<string>(), 
            It.IsAny<string>(), 
            It.IsAny<List<string>>()), Times.Once);
    }
}
```

### Service Layer Testing

```csharp
public class ServiceTests
{
    private readonly Mock<IDataAccess> mockDataAccess;
    private readonly Mock<ILogger<Service>> mockLogger;
    private readonly Mock<ITelemetryTracer> mockTracer;
    private readonly Service sut;

    public ServiceTests()
    {
        mockDataAccess = new Mock<IDataAccess>();
        mockLogger = new Mock<ILogger<Service>>();
        mockTracer = new Mock<ITelemetryTracer>();
        
        sut = new Service(mockTracer.Object, mockLogger.Object, mockDataAccess.Object);
    }

    [Fact]
    public async Task ProcessAsync_ValidInput_ReturnsSuccess()
    {
        // Arrange
        var input = new ProcessRequest { Id = "test-id" };
        var entities = new List<Entity> { new Entity { Id = "entity-1" } };
        
        mockDataAccess
            .Setup(x => x.FindEntitiesAsync(It.IsAny<List<string>>()))
            .ReturnsAsync(entities);
        
        mockDataAccess
            .Setup(x => x.SaveAsync(It.IsAny<List<Entity>>()))
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

## Testing Complex Scenarios

### 1. Testing Batch Processing

```csharp
[Fact]
public async Task RenewAssetsAndTriggerPricing_LargeAssetList_ProcessesInBatches()
{
    // Arrange
    var assetIds = Enumerable.Range(1, 1500).Select(i => $"asset-{i}").ToList();
    var renewGroup = CreateTestRenewGroup(assetIds);
    
    mockAssetService.Setup(x => x.RenewAssetsAsync(It.IsAny<string>(), It.IsAny<RenewAssetsRequest>()))
        .ReturnsAsync(new List<LineItem> { new LineItem { Id = "line-1" } });
    
    // Act
    var result = await sut.RenewAssetsAndTriggerPricing("cart-1", renewGroup, 500, 1000);
    
    // Assert
    Assert.NotNull(result);
    // Should call RenewAssetsAsync 3 times (1500/500)
    mockAssetService.Verify(
        x => x.RenewAssetsAsync(It.IsAny<string>(), It.IsAny<RenewAssetsRequest>()), 
        Times.Exactly(3));
}
```

### 2. Testing with Dictionary Returns

```csharp
[Fact]
public async Task Method_ReturnsCorrectDictionary()
{
    // Arrange
    var expectedDict = new Dictionary<string, List<Item>>
    {
        { "key1", new List<Item> { new Item { Id = "1" } } },
        { "key2", new List<Item> { new Item { Id = "2" } } }
    };
    
    mockService.Setup(x => x.GetDictionaryAsync()).ReturnsAsync(expectedDict);

    // Act
    var result = await sut.ProcessDictionaryAsync();

    // Assert
    Assert.Equal(2, result.Count);
    Assert.Contains("key1", result.Keys);
}
```

### 3. Testing Parallel Processing

```csharp
[Fact]
public async Task ProcessRenewalGroups_MultipleGroups_ProcessesInParallel()
{
    // Arrange
    var groups = CreateTestGroups(5);
    var processingOrder = new List<int>();
    
    mockProcessor.Setup(x => x.ProcessGroup(It.IsAny<RenewGroup>()))
        .Returns((RenewGroup g) => 
        {
            processingOrder.Add(int.Parse(g.Id));
            return Task.FromResult(true);
        });
    
    // Act
    await sut.ProcessRenewalGroups("job-1", groups);
    
    // Assert
    Assert.Equal(5, processingOrder.Count);
}
```

### 4. Testing with Configuration

```csharp
[Fact]
public async Task Method_UsesConfigurationValue()
{
    // Arrange
    var renewalConfig = new Dictionary<string, object>
    {
        { "MaxBatchSize", "500" }
    };
    
    var mockSection = new Mock<IConfigurationSection>();
    mockSection.Setup(x => x.Get<Dictionary<string, object>>()).Returns(renewalConfig);
    mockConfiguration.Setup(x => x.GetSection("RenewalConfig")).Returns(mockSection.Object);

    // Act
    var result = await sut.ProcessBatchAsync();

    // Assert
    Assert.Equal(500, result.BatchSize);
}
```

## Test Data Builders

Use helper methods to create test data:

```csharp
private AssetRenewalGroupAndItems CreateTestRenewGroup(List<string> assetIds = null)
{
    assetIds ??= new List<string> { "asset-1", "asset-2" };
    
    return new AssetRenewalGroupAndItems
    {
        AssetRenewGroup = new AssetRenewGroup
        {
            Id = "group-1",
            GroupName = "Test Group",
            Account = new LookupObject("acc-1", "Account 1"),
            IsAutoRenew = false
        },
        AssetRenewGroupItems = assetIds.Select((id, index) => new AssetRenewGroupItem
        {
            Id = $"item-{index}",
            AssetLineItem = new AssetLineItem
            {
                Id = id,
                Name = $"Asset {id}"
            }
        }).ToList()
    };
}

private List<AssetLineItem> CreateTestAssets(int count)
{
    var assets = new List<AssetLineItem>();
    for (int i = 0; i < count; i++)
    {
        assets.Add(new AssetLineItem
        {
            Id = $"asset-{i}",
            Name = $"Asset {i}",
            Account = new LookupObject($"acc-{i}", $"Account {i}")
        });
    }
    return assets;
}

private Assets CreateTestSettings(int? maxItems = null, int? leadTime = null)
{
    return new Assets
    {
        MaxRenewalLineItemPerCart = maxItems ?? 500,
        RenewalLeadTime = leadTime ?? 30,
        RenewalGroupFields = "Account,PriceList",
        RenewalGroupAttributes = "",
        SendRenewalQuoteCreateNotification = true
    };
}
```

## Assertion Best Practices

### 1. Use Specific Assertions
```csharp
// Good
Assert.Equal(expectedValue, result);
Assert.Contains(expectedItem, collection);

// Avoid
Assert.True(result == expectedValue);
Assert.True(collection.Contains(expectedItem));
```

### 2. One Logical Assert Per Test
```csharp
[Fact]
public async Task Method_Scenario_ExpectedBehavior()
{
    // Arrange & Act
    var result = await sut.Method();

    // Assert - All related to the same logical outcome
    Assert.NotNull(result);
    Assert.Equal(expectedCount, result.Count);
    Assert.All(result, item => Assert.NotNull(item.Id));
}
```

### 3. Assert on Mocks Last
```csharp
// Arrange & Act
var result = await sut.Method();

// Assert
Assert.Equal(expected, result); // Assert on result first
mockService.Verify(x => x.Called(), Times.Once); // Then verify mocks
```

## Common Mock Scenarios

### 1. Mocking ILogger
```csharp
private readonly Mock<ILogger<ClassUnderTest>> mockLogger;

// Usually no setup needed - just verify if logging is critical
mockLogger.Verify(
    x => x.Log(
        LogLevel.Error,
        It.IsAny<EventId>(),
        It.Is<It.IsAnyType>((v, t) => true),
        It.IsAny<Exception>(),
        It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
    Times.Once);
```

### 2. Mocking ITelemetryTracer
```csharp
private readonly Mock<ITelemetryTracer> mockTracer;
private readonly Mock<ISpan> mockSpan;

public TestClass()
{
    mockTracer = new Mock<ITelemetryTracer>();
    mockSpan = new Mock<ISpan>();
    
    mockTracer
        .Setup(x => x.StartActiveSpan(
            It.IsAny<string>(), 
            It.IsAny<SpanKind>(), 
            It.IsAny<TagsCollection>()))
        .Returns(mockSpan.Object);
}
```

### 3. Mocking IConfiguration
```csharp
private void SetupConfiguration(Dictionary<string, object> config)
{
    var mockSection = new Mock<IConfigurationSection>();
    mockSection.Setup(x => x.Get<Dictionary<string, object>>()).Returns(config);
    mockConfiguration.Setup(x => x.GetSection("RenewalConfig")).Returns(mockSection.Object);
}
```

### 4. Mocking Complex Return Types
```csharp
mockService
    .Setup(x => x.GetComplexObjectAsync())
    .ReturnsAsync(new ComplexObject
    {
        Property1 = "value1",
        NestedObject = new NestedObject
        {
            Id = "nested-id"
        },
        Collection = new List<Item>
        {
            new Item { Id = "item-1" }
        }
    });
```

## Test Organization

### 1. Group Related Tests
```csharp
public class ServiceTests
{
    // Constructor and shared setup
    
    #region ProcessRenewalGroup Tests
    
    [Fact]
    public async Task ProcessRenewalGroup_ValidInput_CreatesQuote() { }
    
    [Fact]
    public async Task ProcessRenewalGroup_NoAssets_ReturnsTrue() { }
    
    #endregion
    
    #region RenewAssetsAndTriggerPricing Tests
    
    [Fact]
    public async Task RenewAssetsAndTriggerPricing_LargeList_ProcessesInBatches() { }
    
    #endregion
    
    // Helper methods at the bottom
    private TestData CreateTestData() { }
}
```

### 2. Test File Location
- Mirror the source code structure in the test project
- Example:
  - Source: `Conga.Revenue.Renewal.Worker\Processors\QuoteCreationProcessor.cs`
  - Test: `Conga.Revenue.Renewal.Worker.Tests\Processors\QuoteCreationProcessorTests.cs`

## Common Pitfalls to Avoid

1. ? **Don't test implementation details** - Test behavior, not internal state
2. ? **Don't over-mock** - Only mock external dependencies
3. ? **Don't use real dependencies** - Always use mocks for external services
4. ? **Don't ignore async/await** - Always await async methods in tests
5. ? **Don't forget to verify** - Always verify that mocks were called as expected
6. ? **Don't use magic numbers** - Use constants or variables with clear names
7. ? **Don't test multiple scenarios in one test** - Keep tests focused
8. ? **Don't forget cleanup** - Dispose of resources properly

## Quick Reference

### xUnit Attributes
- `[Fact]` - Single test case
- `[Theory]` - Parameterized test
- `[InlineData(...)]` - Provides data for theory
- `[Skip("reason")]` - Skip a test temporarily
- `[Trait("Category", "Integration")]` - Categorize tests

### Moq Times
- `Times.Never` - Method should not be called
- `Times.Once` - Method should be called exactly once
- `Times.Exactly(n)` - Method should be called exactly n times
- `Times.AtLeast(n)` - Method should be called at least n times
- `Times.AtMost(n)` - Method should be called at most n times
- `Times.Between(min, max, Range.Inclusive)` - Between min and max times

### Common It.Is Patterns
- `It.IsAny<T>()` - Any value of type T
- `It.Is<T>(x => condition)` - Value matching condition
- `It.IsIn(collection)` - Value in collection
- `It.IsRegex(pattern)` - String matching regex
- `It.IsNotNull<T>()` - Non-null value of type T

## Conga-Specific Patterns

### Testing Renewal Processors
```csharp
[Fact]
public async Task Processor_ValidRequest_UpdatesJobStatus()
{
    // Arrange
    var jobId = "job-123";
    var request = CreateTestRequest();
    
    mockRenewalJobManager.Setup(x => x.GetJobStatusAsync(jobId))
        .ReturnsAsync(new CPQJobStatus { Id = jobId });
    
    mockRenewalJobManager.Setup(x => x.UpdateJobDetailsAsync(
        It.IsAny<CPQJobStatus>(), 
        It.IsAny<List<string>>()))
        .ReturnsAsync(true);
    
    // Act
    var result = await sut.ProcessAsync(jobId, request);
    
    // Assert
    Assert.True(result);
    mockRenewalJobManager.Verify(
        x => x.UpdateJobDetailsAsync(
            It.Is<CPQJobStatus>(s => s.Status == "Completed"), 
            It.IsAny<List<string>>()), 
        Times.Once);
}
```

### Testing with Notifications
```csharp
[Fact]
public async Task ProcessGroup_Success_SendsNotification()
{
    // Arrange
    var settings = CreateTestSettings();
    settings.SendRenewalQuoteCreateNotification = true;
    
    mockNotificationService.Setup(x => x.SendNotificationAsync(It.IsAny<NotificationRequest>()))
        .ReturnsAsync(new NotificationResponse { StatusCode = System.Net.HttpStatusCode.OK });
    
    // Act
    await sut.ProcessRenewalGroup(renewGroup, 1);
    
    // Assert
    mockNotificationService.Verify(
        x => x.SendNotificationAsync(
            It.Is<NotificationRequest>(r => r.Action == NotificationAction.QuoteCreationSuccess)), 
        Times.Once);
}
```

## Summary

When writing xUnit tests with Copilot for Conga projects:
1. ? Use descriptive test method names following the pattern `MethodName_Scenario_ExpectedBehavior`
2. ? Arrange-Act-Assert structure
3. ? Mock all external dependencies (services, repositories, loggers, etc.)
4. ? Use `async Task` for async methods
5. ? Verify mock calls with appropriate `Times` constraints
6. ? Use `[Theory]` for parameterized tests
7. ? One logical assertion per test
8. ? Test both success and failure paths
9. ? Use helper methods for test data creation
10. ? Keep tests focused and maintainable
11. ? Test batch processing and parallel execution scenarios
12. ? Mock configuration properly for processor tests
13. ? Test notification scenarios when applicable
14. ? Verify telemetry and logging calls for critical paths
