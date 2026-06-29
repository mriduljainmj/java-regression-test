using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using TechTalk.SpecFlow;
using Xunit;

namespace BP.Tests.StepDefinitions
{
    [Binding]
    public class WeatherForecastStepDefinitions
    {
        private readonly ScenarioContext _scenarioContext;
        private readonly HttpClient _httpClient;

        public WeatherForecastStepDefinitions(ScenarioContext scenarioContext, HttpClient httpClient)
        {
            _scenarioContext = scenarioContext;
            _httpClient = httpClient;
        }

        [When(@"^a client requests GET /WeatherForecast$")]
        public async Task WhenAClientRequestsGetWeatherForecast()
        {
            var response = await _httpClient.GetAsync("/WeatherForecast");
            _scenarioContext["response"] = response;
        }

        [Then(@"^the response JSON array length should be (\d+)$")]
        public async Task ThenTheResponseJsonArrayLengthShouldBe(int expected)
        {
            var response = (HttpResponseMessage)_scenarioContext["response"];
            var body = await response.Content.ReadAsStringAsync();
            var doc = JsonDocument.Parse(body);
            Assert.Equal(expected, doc.RootElement.GetArrayLength());
        }

        [Then(@"^each item should contain fields (.+)$")]
        public async Task ThenEachItemShouldContainFields(string fieldsArg)
        {
            var response = (HttpResponseMessage)_scenarioContext["response"];
            var body = await response.Content.ReadAsStringAsync();
            var doc = JsonDocument.Parse(body);

            var fieldNames = Regex.Matches(fieldsArg, @"""([^""]+)""")
                .Select(m => m.Groups[1].Value)
                .ToArray();

            foreach (var element in doc.RootElement.EnumerateArray())
            {
                foreach (var field in fieldNames)
                {
                    Assert.True(element.TryGetProperty(field, out _),
                        $"Expected field '{field}' not found in item");
                }
            }
        }
    }
}
