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
    public class ProductRatingStepDefinitions
    {
        private readonly ScenarioContext _scenarioContext;
        private readonly HttpClient _httpClient;

        public ProductRatingStepDefinitions(ScenarioContext scenarioContext, HttpClient httpClient)
        {
            _scenarioContext = scenarioContext;
            _httpClient = httpClient;
        }

        [Given("a product exists with id")]
        public void GivenAProductExistsWithId()
        {
            var productId = Guid.NewGuid().ToString();
            _scenarioContext["productId"] = productId;
        }

        [When("I submit a rating of {int} for the product")]
        public async Task WhenISubmitARatingForTheProduct(int rating)
        {
            var productId = _scenarioContext["productId"].ToString();
            var payload = new { rating };
            var json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync($"/api/products/{productId}/rate", content);
            _scenarioContext["ratingResponse"] = response;
            _scenarioContext["statusCode"] = response.StatusCode;
        }

        [Then("the rating should be accepted")]
        public void ThenTheRatingShouldBeAccepted()
        {
            var statusCode = (HttpStatusCode)_scenarioContext["statusCode"];
            if (statusCode == HttpStatusCode.OK || statusCode == HttpStatusCode.Created)
            {
                // Success
            }
            else
            {
                throw new InvalidOperationException($"Expected OK or Created, got {statusCode}");
            }
        }

        [Then("the rating should be rejected with {int} status")]
        public void ThenTheRatingShouldBeRejectedWithStatus(int expectedStatus)
        {
            var actualStatus = (int)_scenarioContext["statusCode"];
            if (actualStatus != expectedStatus)
            {
                throw new InvalidOperationException($"Expected status {expectedStatus}, got {actualStatus}");
            }
        }

        [When("I submit an invalid rating of {int}")]
        public async Task WhenISubmitAnInvalidRating(int rating)
        {
            var productId = _scenarioContext["productId"].ToString();
            var payload = new { rating };
            var json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync($"/api/products/{productId}/rate", content);
            _scenarioContext["ratingResponse"] = response;
            _scenarioContext["statusCode"] = response.StatusCode;
        }

        [Given("I want to rate a product")]
        public void GivenIWantToRateAProduct()
        {
            // Setup for rating test scenario
            var productId = Guid.NewGuid().ToString();
            _scenarioContext["productId"] = productId;
            _scenarioContext["rating"] = 0;
        }

        [When("I provide rating {int}")]
        public void WhenIProvideRating(int rating)
        {
            _scenarioContext["rating"] = rating;
        }

        [Then("the product rating should be recorded")]
        public async Task ThenTheProductRatingShouldBeRecorded()
        {
            var productId = _scenarioContext["productId"].ToString();
            var rating = (int)_scenarioContext["rating"];
            var payload = new { rating };
            var json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync($"/api/products/{productId}/rate", content);
            if (response.StatusCode != HttpStatusCode.OK && response.StatusCode != HttpStatusCode.Created)
            {
                throw new InvalidOperationException($"Failed to rate product: {response.StatusCode}");
            }
        }
    }
}
