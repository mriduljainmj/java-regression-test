using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using TechTalk.SpecFlow;
using Xunit;

namespace BP.Tests.StepDefinitions
{
    [Binding]
    public class PricingOrchestrationStepDefinitions
    {
        private readonly HttpClient _httpClient;
        private readonly ScenarioContext _scenarioContext;

        public PricingOrchestrationStepDefinitions(HttpClient httpClient, ScenarioContext scenarioContext)
        {
            _httpClient = httpClient;
            _scenarioContext = scenarioContext;
        }

        [When(@"^a client requests GET /api/discount-policy with quantity (\d+) and loyalty (true|false)$")]
        public async Task WhenAClientRequestsDiscountPolicy(int quantity, string loyalty)
        {
            var response = await _httpClient.GetAsync($"/api/discount-policy?quantity={quantity}&isLoyaltyMember={loyalty}");
            _scenarioContext["response"] = response;
        }

        [When(@"^a client POSTs /api/order-total-from-policy with body$")]
        public async Task WhenAClientPostsOrderTotalFromPolicyWithBody(string body)
        {
            var content = new StringContent(body, Encoding.UTF8, "application/json");
            var response = await _httpClient.PostAsync("/api/order-total-from-policy", content);
            _scenarioContext["response"] = response;
        }

        [Then(@"^the response JSON should contain decimal ""([^""]+)"": ([0-9]+(?:\.[0-9]+)?)$")]
        public async Task ThenTheResponseJsonShouldContainDecimalField(string key, decimal expected)
        {
            var response = (HttpResponseMessage)_scenarioContext["response"];
            var body = await response.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(body);
            var actual = doc.RootElement.GetProperty(key).GetDecimal();
            Assert.Equal(expected, actual);
        }
    }
}
