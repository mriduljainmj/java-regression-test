using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using TechTalk.SpecFlow;

namespace BP.Tests.StepDefinitions
{
    [Binding]
    public class ProductManagementStepDefinitions
    {
        private readonly HttpClient _httpClient;
        private readonly ScenarioContext _scenarioContext;

        private string AliasKey(int requestedId) => $"product_id_alias_{requestedId}";

        private int ResolveProductId(int requestedId)
        {
            var key = AliasKey(requestedId);
            if (_scenarioContext.TryGetValue(key, out int mappedId))
            {
                return mappedId;
            }
            return requestedId;
        }

        private static int? TryExtractProductId(string body)
        {
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.ValueKind != JsonValueKind.Object)
            {
                return null;
            }

            if (doc.RootElement.TryGetProperty("ProductId", out var pid))
            {
                return pid.GetInt32();
            }
            if (doc.RootElement.TryGetProperty("productId", out var pidCamel))
            {
                return pidCamel.GetInt32();
            }
            if (doc.RootElement.TryGetProperty("id", out var id))
            {
                return id.GetInt32();
            }
            return null;
        }

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
            if (response.StatusCode != HttpStatusCode.NotFound)
            {
                _scenarioContext[AliasKey(id)] = id;
                return;
            }

            var product = new { Name = $"Product{id}", Price = 10.0, InStock = true };
            var createResponse = await _httpClient.PostAsync(
                "/api/products",
                new StringContent(JsonSerializer.Serialize(product), Encoding.UTF8, "application/json")
            );
            createResponse.EnsureSuccessStatusCode();

            var body = await createResponse.Content.ReadAsStringAsync();
            int createdId = TryExtractProductId(body) ?? id;
            _scenarioContext[AliasKey(id)] = createdId;
        }

        [Given(@"^a product exists with payload:$")]
        public async Task GivenAProductExistsWithPayload(string payload)
        {
            var content = new StringContent(payload, Encoding.UTF8, "application/json");
            var response = await _httpClient.PostAsync("/api/products", content);
            response.EnsureSuccessStatusCode();
        }

        [Given(@"^the product catalog is empty$")]
        public async Task GivenTheProductCatalogIsEmpty()
        {
            var response = await _httpClient.GetAsync("/api/products");
            if (!response.IsSuccessStatusCode)
            {
                return;
            }

            var body = await response.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
            {
                return;
            }

            foreach (var product in doc.RootElement.EnumerateArray())
            {
                if (!product.TryGetProperty("ProductId", out var idElement))
                {
                    continue;
                }

                int id = idElement.GetInt32();
                await _httpClient.DeleteAsync($"/api/products/{id}");
            }
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
            int resolvedId = ResolveProductId(id);
            var response = await _httpClient.GetAsync($"/api/products/{resolvedId}");
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
            int resolvedId = ResolveProductId(id);
            var content = new StringContent(body, Encoding.UTF8, "application/json");
            var response = await _httpClient.PutAsync($"/api/products/{resolvedId}", content);
            _scenarioContext["response"] = response;
        }

        [When(@"^a client DELETEs /api/products/(\d+)$")]
        public async Task WhenAClientDeletesApiProducts(int id)
        {
            int resolvedId = ResolveProductId(id);
            var response = await _httpClient.DeleteAsync($"/api/products/{resolvedId}");
            _scenarioContext["response"] = response;
        }

        [When(@"^a client PATCHes /api/products/(\d+)/stock with body$")]
        public async Task WhenAClientPATCHesApiProductsStockWithBody(int id, string body)
        {
            int resolvedId = ResolveProductId(id);
            var request = new HttpRequestMessage(new HttpMethod("PATCH"), $"/api/products/{resolvedId}/stock")
            {
                Content = new StringContent(body, Encoding.UTF8, "application/json")
            };
            var response = await _httpClient.SendAsync(request);
            _scenarioContext["response"] = response;
        }

    }
}
