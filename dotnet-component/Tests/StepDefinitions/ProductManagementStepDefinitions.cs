using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using TechTalk.SpecFlow;
using Xunit;

namespace BP.Tests.StepDefinitions
{
    [Binding]
    public class ProductManagementStepDefinitions
    {
        private readonly ScenarioContext _scenarioContext;
        private readonly HttpClient _httpClient;

        public ProductManagementStepDefinitions(ScenarioContext scenarioContext, HttpClient httpClient)
        {
            _scenarioContext = scenarioContext;
            _httpClient = httpClient;
        }

        [Given(@"^a product exists with id (\d+)$")]
        public async Task GivenAProductExistsWithId(int id)
        {
            var response = await _httpClient.GetAsync($"/api/products/{id}");
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        }

        [When(@"^a client POSTs /api/products with body$")]
        public async Task WhenAClientPostsApiProductsWithBody(string body)
        {
            var content = new StringContent(body, Encoding.UTF8, "application/json");
            var response = await _httpClient.PostAsync("/api/products", content);
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
        public async Task WhenAClientPatchesApiProductsStockWithBody(int id, string body)
        {
            var content = new StringContent(body.Trim(), Encoding.UTF8, "application/json");
            var response = await _httpClient.PatchAsync($"/api/products/{id}/stock", content);
            _scenarioContext["response"] = response;
        }
    }
}
