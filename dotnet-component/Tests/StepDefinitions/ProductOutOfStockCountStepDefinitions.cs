using System.Net.Http;
using System.Threading.Tasks;
using TechTalk.SpecFlow;

namespace BP.Tests.StepDefinitions
{
    [Binding]
    public class ProductOutOfStockCountStepDefinitions
    {
        private readonly HttpClient _httpClient;
        private readonly ScenarioContext _scenarioContext;

        public ProductOutOfStockCountStepDefinitions(HttpClient httpClient, ScenarioContext scenarioContext)
        {
            _httpClient = httpClient;
            _scenarioContext = scenarioContext;
        }

        [When(@"^a client requests GET /api/products/out-of-stock-count$")]
        public async Task WhenAClientRequestsGetApiProductsOutOfStockCount()
        {
            var response = await _httpClient.GetAsync("/api/products/out-of-stock-count");
            _scenarioContext["response"] = response;
        }
    }
}
