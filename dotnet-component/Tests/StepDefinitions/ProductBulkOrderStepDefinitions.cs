using System;
using System.Collections.Generic;
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
    public class ProductBulkOrderStepDefinitions
    {
        private readonly ScenarioContext _scenarioContext;
        private readonly HttpClient _httpClient;

        public ProductBulkOrderStepDefinitions(ScenarioContext scenarioContext, HttpClient httpClient)
        {
            _scenarioContext = scenarioContext;
            _httpClient = httpClient;
        }

        [Given("a product exists with name {string} and price {double} and in stock")]
        public async Task GivenAProductExistsWithNameAndPrice(string name, double price)
        {
            var payload = new { name, price, inStock = true };
            var json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync("/api/products", content);
            if (response.StatusCode == HttpStatusCode.Created)
            {
                var responseContent = await response.Content.ReadAsStringAsync();
                var jsonDoc = JsonDocument.Parse(responseContent);
                var productId = jsonDoc.RootElement.GetProperty("productId").GetInt32();
                _scenarioContext["productId"] = productId;
                _scenarioContext["productName"] = name;
                _scenarioContext["productPrice"] = price;
            }
        }

        [When("I validate a bulk order of {int} items")]
        public async Task WhenIValidateABulkOrderOfItems(int quantity)
        {
            var productId = _scenarioContext["productId"];
            var payload = new { quantity };
            var json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync($"/api/products/{productId}/validate-bulk-order", content);
            _scenarioContext["bulkOrderResponse"] = response;
            _scenarioContext["statusCode"] = response.StatusCode;

            if (response.StatusCode == HttpStatusCode.OK)
            {
                var responseContent = await response.Content.ReadAsStringAsync();
                var jsonDoc = JsonDocument.Parse(responseContent);
                _scenarioContext["bulkOrderData"] = jsonDoc;
            }
        }

        [When("a client validates bulk order for the last created product with quantity {int}")]
        public async Task WhenValidateBulkOrderForLastCreatedProductWithQuantity(int quantity)
        {
            var productId = _scenarioContext["productId"];
            var payload = new { quantity };
            var json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync($"/api/products/{productId}/validate-bulk-order", content);
            _scenarioContext["bulkOrderResponse"] = response;
            _scenarioContext["statusCode"] = response.StatusCode;

            if (response.StatusCode == HttpStatusCode.OK)
            {
                var responseContent = await response.Content.ReadAsStringAsync();
                var jsonDoc = JsonDocument.Parse(responseContent);
                _scenarioContext["bulkOrderData"] = jsonDoc;
            }
        }

        [When("a client validates bulk order for product id {int} with quantity {int}")]
        public async Task WhenValidateBulkOrderForProductIdWithQuantity(int productId, int quantity)
        {
            var payload = new { quantity };
            var json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync($"/api/products/{productId}/validate-bulk-order", content);
            _scenarioContext["bulkOrderResponse"] = response;
            _scenarioContext["statusCode"] = response.StatusCode;

            if (response.StatusCode == HttpStatusCode.OK)
            {
                var responseContent = await response.Content.ReadAsStringAsync();
                var jsonDoc = JsonDocument.Parse(responseContent);
                _scenarioContext["bulkOrderData"] = jsonDoc;
            }
        }

        [When("a client requests inventory summary")]
        public async Task WhenRequestInventorySummary()
        {
            var response = await _httpClient.GetAsync("/api/products/inventory-summary");
            _scenarioContext["inventoryResponse"] = response;
            _scenarioContext["statusCode"] = response.StatusCode;

            if (response.StatusCode == HttpStatusCode.OK)
            {
                var responseContent = await response.Content.ReadAsStringAsync();
                var jsonDoc = JsonDocument.Parse(responseContent);
                _scenarioContext["inventorySummaryData"] = jsonDoc;
            }
        }

        [Then("the bulk order should be valid")]
        public void ThenTheBulkOrderShouldBeValid()
        {
            var statusCode = (HttpStatusCode)_scenarioContext["statusCode"];
            if (statusCode != HttpStatusCode.OK)
            {
                throw new InvalidOperationException($"Expected OK, got {statusCode}");
            }
        }

        [Then("the bulk order should be invalid")]
        public void ThenTheBulkOrderShouldBeInvalid()
        {
            var statusCode = (HttpStatusCode)_scenarioContext["statusCode"];
            if (statusCode == HttpStatusCode.OK)
            {
                throw new InvalidOperationException("Expected validation to fail, but it succeeded");
            }
        }

        [Then("the response JSON should contain {string} with value {string}")]
        public void ThenResponseJsonShouldContainStringValue(string field, string expectedValue)
        {
            var data = (JsonDocument)_scenarioContext["bulkOrderData"];
            var actualValue = data.RootElement.GetProperty(field).GetString();
            if (actualValue != expectedValue)
            {
                throw new InvalidOperationException($"Expected {field}={expectedValue}, got {actualValue}");
            }
        }

        [Then("the response JSON should contain {string} with value {int}")]
        public void ThenResponseJsonShouldContainIntValue(string field, int expectedValue)
        {
            var data = (JsonDocument)_scenarioContext["bulkOrderData"];
            var actualValue = data.RootElement.GetProperty(field).GetInt32();
            if (actualValue != expectedValue)
            {
                throw new InvalidOperationException($"Expected {field}={expectedValue}, got {actualValue}");
            }
        }

        [Then("the response JSON should contain {string} with value {double}")]
        public void ThenResponseJsonShouldContainDoubleValue(string field, double expectedValue)
        {
            var data = (JsonDocument)_scenarioContext["bulkOrderData"];
            var actualValue = data.RootElement.GetProperty(field).GetDouble();
            if (Math.Abs(actualValue - expectedValue) > 0.001)
            {
                throw new InvalidOperationException($"Expected {field}={expectedValue}, got {actualValue}");
            }
        }

        [Then("the response JSON should contain {string} with value true")]
        public void ThenResponseJsonShouldContainTrue(string field)
        {
            var data = (JsonDocument)_scenarioContext["bulkOrderData"];
            var actualValue = data.RootElement.GetProperty(field).GetBoolean();
            if (!actualValue)
            {
                throw new InvalidOperationException($"Expected {field}=true, got false");
            }
        }
    }
}
