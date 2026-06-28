# .NET sample component

The .NET counterpart of `java-component/` — a small ASP.NET Core Web API with a
Reqnroll (SpecFlow-compatible) BDD test suite. It exists so the agent's
**language detection** has a real target: a change here is detected as `dotnet`
and the agent generates **C# step definitions** instead of Java glue.

```
dotnet-component/
  Api/                         ASP.NET Core Web API (the component under test)
    Controllers/ProductsController.cs   /api/v1/products CRUD
    Domain.cs                  Product, ProductRequest (validation), ProductService
    Program.cs                 host + 404 exception mapping
  Tests/                       Reqnroll + xUnit test project
    Features/*.feature         Gherkin scenarios (identical format to Cucumber)
    StepDefinitions/*.cs       C# glue: [Given]/[When]/[Then] regex attributes
    Support/TestState.cs       scenario-scoped shared state (the C# "TestContext")
```

## Run the tests

```bash
dotnet test dotnet-component
```

Requires the .NET 8 SDK. The test project boots the API in-process via
`WebApplicationFactory<Program>`, so no server needs to be started separately.

> ⚠️ **Verification status:** this sample was authored in an environment without
> the .NET SDK, so it has **not** yet been compiled/run here. Run `dotnet test`
> once on a machine (or in CI) with the SDK to confirm package versions resolve
> and the two scenarios pass, then commit any fixups. The agent pipeline itself
> (detection, C# glue parsing, the `dotnet test` runner + console-failure parser)
> is unit-tested and verified independently of the SDK.

## How the agent treats this component

| Aspect | Java component | This .NET component |
|---|---|---|
| Detected language | `java` | `dotnet` |
| Glue language | Java `@Given("…")` cucumber expressions | C# `[Given(@"…")]` regex attributes |
| Shared state | `TestContext` Spring bean | `TestState` (Reqnroll context injection) |
| Test command | `mvn test` | `dotnet test` |
| Failure source | `cucumber-report.json` | `dotnet test` console output |

The `.feature` files are the same Gherkin in both — only the glue differs.
