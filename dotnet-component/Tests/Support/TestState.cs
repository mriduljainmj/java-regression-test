using Microsoft.AspNetCore.Mvc.Testing;

namespace Tests.Support;

/// <summary>
/// Scenario-scoped shared state — the .NET equivalent of the Java TestContext
/// bean. Reqnroll's context injection creates ONE instance per scenario and
/// passes it to every [Binding] class via constructor injection, so step
/// definitions across multiple classes share the same HttpClient and ids.
///
/// A fresh WebApplicationFactory per scenario means a fresh in-memory store,
/// so scenarios are isolated without an explicit reset step.
///
/// Step-definition classes must take this via their constructor — never use
/// static fields, which are invisible across binding classes.
/// </summary>
public sealed class TestState : IDisposable
{
    private readonly WebApplicationFactory<Program> _factory = new();

    public HttpClient Client { get; }
    public HttpResponseMessage? LastResponse { get; set; }
    public long LastCreatedProductId { get; set; }

    public TestState() => Client = _factory.CreateClient();

    public void Dispose()
    {
        Client.Dispose();
        _factory.Dispose();
    }
}
