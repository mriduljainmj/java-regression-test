using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using BP.Models;
using Microsoft.AspNetCore.Http;
using Newtonsoft.Json.Linq;
using TechTalk.SpecFlow;

namespace BP.Tests.StepDefinitions
{
    [Binding]
    public class ProductManagementStepDefinitions
    {
        private readonly HttpClient _httpClient;
        private readonly ScenarioContext _scenarioContext;

        public ProductManagementStepDefinitions(HttpClient httpClient, ScenarioContext scenarioContext)
        {
            _httpClient = httpClient;
            _scenarioContext = scenarioContext;
        }

        [Given(@"^a product exists with id (\d+)$")]
        public async Task GivenAProductExistsWithId(int id)
        {
            // Assuming a product with the given id already exists in the test data store.
            // If not, create it here.
            var response = await _httpClient.GetAsync($"/api/products/{id}");
            if (response.StatusCode == HttpStatusCode.NotFound)
            {
                var product = new { Name = $"Product{id}", Price = 10.0, InStock = true };
                var createResponse = await _httpClient.PostAsync("/api/products",
                    new StringContent(JsonSerializer.Serialize(product), Encoding.UTF8, "application/json"));
                createResponse.EnsureSuccessStatusCode();
            }
        }

        [Given(@"^a product exists with payload:$")]
        public async Task GivenAProductExistsWithPayload(string payload)
        {
            var content = new StringContent(payload, Encoding.UTF8, "application/json");
            var response = await _httpClient.PostAsync("/api/products", content);
            response.EnsureSuccessStatusCode();
        }

        [When(@"^a client POSTs /api/products with body$")]
        public async Task WhenAClientPOSTsApiProductsWithBody(string body)
        {
            var content = new StringContent(body, Encoding.UTF8, "application/json");
            var response = await _httpClient.PostAsync("/api/products", content);
            _scenarioContext["response"] = response;
        }

        [When(@"^a client requests GET /api/products$")]
        public async Task WhenAClientRequestsGetApiProducts()
        {
            var response = await _httpClient.GetAsync("/api/products");
            _scenarioContext["response"] = response;
        }

        [When(@"^a client requests GET /api/products/(\d+)$")]
        public async Task WhenAClientRequestsGetApiProductsById(int id)
        {
            var response = await _httpClient.GetAsync($"/api/products/{id}");
            _scenarioContext["response"] = response;
        }

        [When(@"^a client requests GET /api/products/inventory-count$")]
        public async Task WhenAClientRequestsGetApiProductsInventoryCount()
        {
            var response = await _httpClient.GetAsync("/api/products/inventory-count");
            _scenarioContext["response"] = response;
        }

        [When(@"^a client requests GET /api/products/in-stock-count$")]
        public async Task WhenAClientRequestsGetApiProductsInStockCount()
        {
            var response = await _httpClient.GetAsync("/api/products/in-stock-count");
            _scenarioContext["response"] = response;
        }

        [When(@"^a client PUTs /api/products/(\d+) with body$")]
        public async Task WhenAClientPutsApiProductsWithBody(int id, string body)
        {
            var content = new StringContent(body, Encoding.UTF8, "application/json");
            var response = await _httpClient.PutAsync($"/api/products/{id}", content);
            _scenarioContext["response"] = response;
        }

        [When(@"^a client DELETEs /api/products/(\d+)$")]
        public async Task WhenAClientDeletesApiProducts(int id)
        {
            var response = await _httpClient.DeleteAsync($"/api/products/{id}");
            _scenarioContext["response"] = response;
        }

        [When(@"^a client PATCHes /api/products/(\d+)/stock with body$")]
        public async Task WhenAClientPATCHesApiProductsStockWithBody(int id, string body)
        {
            var request = new HttpRequestMessage(new HttpMethod("PATCH"), $"/api/products/{id}/stock")
            {
                Content = new StringContent(body, Encoding.UTF8, "application/json")
            };
            var response = await _httpClient.SendAsync(request);
            _scenarioContext["response"] = response;
        }

        [Then(@"^the response status should be (\d+)$")]
        public void ThenTheResponseStatusShouldBe(int expectedStatus)
        {
            var response = (HttpResponseMessage)_scenarioContext["response"];
            if ((int)response.StatusCode != expectedStatus)
            {
                throw new Exception($"Expected status {expectedStatus} but got {(int)response.StatusCode}");
            }
        }

        [Then(@"^the response JSON should contain ""([^""]*)"": (.*)$")]
        public async Task ThenTheResponseJSONShouldContain(string key, string expectedValue)
        {
            var response = (HttpResponseMessage)_scenarioContext["response"];
            var json = await response.Content.ReadAsStringAsync();
            var jObj = JObject.Parse(json);
            var actual = jObj.SelectToken(key)?.ToString();
            if (actual == null)
                throw new Exception($"Key '{key}' not found in response.");
            if (expectedValue.StartsWith("\"") && expectedValue.EndsWith("\""))
            {
                var trimmed = expectedValue.Trim('\"');
                if (actual != trimmed)
                    throw new Exception($"Expected '{key}' to be '{trimmed}' but was '{actual}'.");
            }
            else
            {
                if (actual != expectedValue)
                    throw new Exception($"Expected '{key}' to be '{expectedValue}' but was '{actual}'.");
            }
        }

        [Then(@"^the response JSON should contain message ""([^""]*)""$")]
        public async Task ThenTheResponseJSONShouldContainMessage(string expectedMessage)
        {
            var response = (HttpResponseMessage)_scenarioContext["response"];
            var json = await response.Content.ReadAsStringAsync();
            var jObj = JObject.Parse(json);
            var actual = jObj["message"]?.ToString();
            if (actual != expectedMessage)
                throw new Exception($"Expected message '{expectedMessage}' but got '{actual}'.");
        }
    }
}
