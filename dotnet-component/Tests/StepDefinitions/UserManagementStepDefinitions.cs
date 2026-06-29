using System.Net;
using System.Net.Http;
using System.Threading.Tasks;
using TechTalk.SpecFlow;
using Xunit;

namespace BP.Tests.StepDefinitions
{
    [Binding]
    public class UserManagementStepDefinitions
    {
        private readonly ScenarioContext _scenarioContext;
        private readonly HttpClient _httpClient;

        public UserManagementStepDefinitions(ScenarioContext scenarioContext, HttpClient httpClient)
        {
            _scenarioContext = scenarioContext;
            _httpClient = httpClient;
        }

        [Given(@"^a user exists with id (\d+)$")]
        public async Task GivenAUserExistsWithId(int id)
        {
            var response = await _httpClient.GetAsync($"/api/GetUserById?userId={id}");
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        }

        [When(@"^a client requests GET /api/GetUserById with userId (\d+)$")]
        public async Task WhenAClientRequestsGetApiGetUserByIdWithUserId(int userId)
        {
            var response = await _httpClient.GetAsync($"/api/GetUserById?userId={userId}");
            _scenarioContext["response"] = response;
        }
    }
}
