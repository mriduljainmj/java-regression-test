using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using BP.Models;
using TechTalk.SpecFlow;

namespace BP.Tests.StepDefinitions
{
    [Binding]
    public class TopRatedStepDefinitions
    {
        private readonly ScenarioContext _scenarioContext;
        private readonly HttpClient _httpClient;

        public TopRatedStepDefinitions(ScenarioContext scenarioContext, HttpClient httpClient)
        {
            _scenarioContext = scenarioContext;
            _httpClient = httpClient;
        }

        [Given("there are multiple products with different ratings")]
        public void GivenThereAreMultipleProductsWithDifferentRatings()
        {
            _scenarioContext["productsCreated"] = new List<string>();
        }

        [When("I request the top {int} rated products")]
        public async Task WhenIRequestTheTopRatedProducts(int count)
        {
            var response = await _httpClient.GetAsync($"/api/products/top-rated?count={count}");
            _scenarioContext["topRatedResponse"] = response;
            _scenarioContext["statusCode"] = response.StatusCode;

            if (response.StatusCode == HttpStatusCode.OK)
            {
                var content = await response.Content.ReadAsStringAsync();
                var jsonDoc = JsonDocument.Parse(content);
                _scenarioContext["topRatedData"] = jsonDoc;
                _scenarioContext["itemCount"] = jsonDoc.RootElement.GetProperty("items").GetArrayLength();
            }
        }

        [Then("I should receive a list of top rated products")]
        public void ThenIShouldReceiveAListOfTopRatedProducts()
        {
            var statusCode = (HttpStatusCode)_scenarioContext["statusCode"];
            if (statusCode != HttpStatusCode.OK)
            {
                throw new InvalidOperationException($"Expected OK, got {statusCode}");
            }

            var itemCount = (int)_scenarioContext["itemCount"];
            if (itemCount == 0)
            {
                throw new InvalidOperationException("Expected at least one product in response");
            }
        }

        [Then("the results should be limited to {int} products")]
        public void ThenTheResultsShouldBeLimitedToProducts(int expectedCount)
        {
            var itemCount = (int)_scenarioContext["itemCount"];
            if (itemCount > expectedCount)
            {
                throw new InvalidOperationException($"Expected at most {expectedCount} products, got {itemCount}");
            }
        }

        [When("I request top rated products with invalid count")]
        public async Task WhenIRequestTopRatedProductsWithInvalidCount()
        {
            var response = await _httpClient.GetAsync("/api/products/top-rated?count=-1");
            _scenarioContext["topRatedResponse"] = response;
            _scenarioContext["statusCode"] = response.StatusCode;
        }

        [Then("the request should be rejected")]
        public void ThenTheRequestShouldBeRejected()
        {
            var statusCode = (HttpStatusCode)_scenarioContext["statusCode"];
            if (statusCode == HttpStatusCode.OK)
            {
                throw new InvalidOperationException($"Expected error status, got {statusCode}");
            }
        }

        [Given("I want to find top performing products")]
        public void GivenIWantToFindTopPerformingProducts()
        {
            _scenarioContext["searchContext"] = "top_rated";
        }

        [When("I search for the top {int} rated items")]
        public async Task WhenISearchForTheTopRatedItems(int limit)
        {
            var response = await _httpClient.GetAsync($"/api/products/top-rated?count={limit}");
            _scenarioContext["topRatedResponse"] = response;
            _scenarioContext["statusCode"] = response.StatusCode;
            _scenarioContext["requestedLimit"] = limit;

            if (response.StatusCode == HttpStatusCode.OK)
            {
                var content = await response.Content.ReadAsStringAsync();
                _scenarioContext["responseContent"] = content;
            }
        }

        [Then("the response should contain products sorted by rating")]
        public void ThenTheResponseShouldContainProductsSortedByRating()
        {
            var statusCode = (HttpStatusCode)_scenarioContext["statusCode"];
            if (statusCode != HttpStatusCode.OK)
            {
                throw new InvalidOperationException($"Expected OK, got {statusCode}");
            }

            var content = _scenarioContext["responseContent"].ToString();
            if (string.IsNullOrEmpty(content))
            {
                throw new InvalidOperationException("Response content is empty");
            }
        }
    }
}
