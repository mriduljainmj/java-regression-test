using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Reqnroll;
using Tests.Support;
using Xunit;

namespace Tests.StepDefinitions;

[Binding]
public class ProductStepDefinitions
{
    private readonly TestState _state;

    public ProductStepDefinitions(TestState state) => _state = state;

    [When(@"a client creates a product with name '(.*)' and price (.*)")]
    public async Task WhenCreate(string name, double price)
    {
        _state.LastResponse = await _state.Client.PostAsJsonAsync(
            "/api/v1/products", new { name, price });
        if (_state.LastResponse.StatusCode == HttpStatusCode.Created)
        {
            var body = await _state.LastResponse.Content.ReadFromJsonAsync<JsonElement>();
            _state.LastCreatedProductId = body.GetProperty("id").GetInt64();
        }
    }

    [When(@"a client requests the product with id (\d+)")]
    public async Task WhenGetById(long id)
    {
        _state.LastResponse = await _state.Client.GetAsync($"/api/v1/products/{id}");
    }

    [When(@"a client requests the last created product")]
    public async Task WhenGetLast()
    {
        _state.LastResponse = await _state.Client.GetAsync(
            $"/api/v1/products/{_state.LastCreatedProductId}");
    }

    [Then(@"the response status should be (\d+)")]
    public void ThenStatus(int code)
    {
        Assert.Equal(code, (int)_state.LastResponse!.StatusCode);
    }

    [Then(@"the response should contain a product id")]
    public async Task ThenHasId()
    {
        var body = await _state.LastResponse!.Content.ReadFromJsonAsync<JsonElement>();
        Assert.True(body.TryGetProperty("id", out _));
    }

    [Then(@"the response should contain a product with name '(.*)'")]
    public async Task ThenName(string name)
    {
        var body = await _state.LastResponse!.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal(name, body.GetProperty("name").GetString());
    }

    [Then(@"the error message should contain '(.*)'")]
    public async Task ThenError(string fragment)
    {
        var text = await _state.LastResponse!.Content.ReadAsStringAsync();
        Assert.Contains(fragment, text);
    }
}
