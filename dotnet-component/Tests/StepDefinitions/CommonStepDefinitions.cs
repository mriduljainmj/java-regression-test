using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using TechTalk.SpecFlow;
using Xunit;

namespace BP.Tests.StepDefinitions
{
    [Binding]
    public class CommonStepDefinitions
    {
        private readonly ScenarioContext _scenarioContext;

        public CommonStepDefinitions(ScenarioContext scenarioContext)
        {
            _scenarioContext = scenarioContext;
        }

        [Then(@"^the response status should be (\d+)$")]
        public void ThenTheResponseStatusShouldBe(int expectedStatus)
        {
            var response = (HttpResponseMessage)_scenarioContext["response"];
            Assert.Equal(expectedStatus, (int)response.StatusCode);
        }

        [Then(@"^the response JSON should contain message ""([^""]*)""$")]
        public async Task ThenTheResponseJsonShouldContainMessage(string message)
        {
            var response = (HttpResponseMessage)_scenarioContext["response"];
            var body = await response.Content.ReadAsStringAsync();
            var doc = JsonDocument.Parse(body);
            var actual = doc.RootElement.GetProperty("message").GetString();
            Assert.Equal(message, actual);
        }

        [Then(@"^the response JSON should contain ""([^""]+)"": ""([^""]*)""$")]
        public async Task ThenTheResponseJsonShouldContainStringField(string key, string value)
        {
            var response = (HttpResponseMessage)_scenarioContext["response"];
            var body = await response.Content.ReadAsStringAsync();
            var doc = JsonDocument.Parse(body);
            var actual = doc.RootElement.GetProperty(key).GetString();
            Assert.Equal(value, actual);
        }

        [Then(@"^the response JSON should contain ""([^""]+)"": (\d+)$")]
        public async Task ThenTheResponseJsonShouldContainIntField(string key, int value)
        {
            var response = (HttpResponseMessage)_scenarioContext["response"];
            var body = await response.Content.ReadAsStringAsync();
            var doc = JsonDocument.Parse(body);
            var actual = doc.RootElement.GetProperty(key).GetInt32();
            Assert.Equal(value, actual);
        }

        [Then(@"^the response JSON should contain ""([^""]+)"": (true|false)$")]
        public async Task ThenTheResponseJsonShouldContainBoolField(string key, string value)
        {
            var response = (HttpResponseMessage)_scenarioContext["response"];
            var body = await response.Content.ReadAsStringAsync();
            var doc = JsonDocument.Parse(body);
            bool expected = bool.Parse(value);
            bool actual = doc.RootElement.GetProperty(key).GetBoolean();
            Assert.Equal(expected, actual);
        }
    }
}
