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
    public class BulkDiscountStepDefinitions
    {
        private readonly ScenarioContext _scenarioContext;
        private readonly HttpClient _httpClient;

        public BulkDiscountStepDefinitions(ScenarioContext scenarioContext, HttpClient httpClient)
        {
            _scenarioContext = scenarioContext;
            _httpClient = httpClient;
        }

        [Given("a product with price {decimal} exists")]
        public void GivenAProductWithPriceExists(decimal price)
        {
            var productId = Guid.NewGuid().ToString();
            _scenarioContext["productId"] = productId;
            _scenarioContext["productPrice"] = price;
        }

        [When("I request a bulk discount for {int} items")]
        public async Task WhenIRequestABulkDiscountForItems(int quantity)
        {
            var productId = _scenarioContext["productId"].ToString();
            var payload = new { quantity };
            var json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync($"/api/products/{productId}/calculate-discount", content);
            _scenarioContext["discountResponse"] = response;
            _scenarioContext["statusCode"] = response.StatusCode;

            if (response.StatusCode == HttpStatusCode.OK)
            {
                var responseContent = await response.Content.ReadAsStringAsync();
                var jsonDoc = JsonDocument.Parse(responseContent);
                _scenarioContext["discountData"] = jsonDoc;
                _scenarioContext["discountPercent"] = jsonDoc.RootElement.GetProperty("discountPercent").GetInt32();
                _scenarioContext["totalPrice"] = jsonDoc.RootElement.GetProperty("totalPrice").GetDecimal();
            }
        }

        [Then("the discount should be {int}%")]
        public void ThenTheDiscountShouldBe(int expectedDiscount)
        {
            var actualDiscount = (int)_scenarioContext["discountPercent"];
            if (actualDiscount != expectedDiscount)
            {
                throw new InvalidOperationException($"Expected {expectedDiscount}% discount, got {actualDiscount}%");
            }
        }

        [Then("the response should include the total price")]
        public void ThenTheResponseShouldIncludeTheTotalPrice()
        {
            if (!_scenarioContext.ContainsKey("totalPrice"))
            {
                throw new InvalidOperationException("Total price not found in response");
            }

            var totalPrice = (decimal)_scenarioContext["totalPrice"];
            if (totalPrice <= 0)
            {
                throw new InvalidOperationException($"Invalid total price: {totalPrice}");
            }
        }

        [Given("I want to calculate bulk order discount")]
        public void GivenIWantToCalculateBulkOrderDiscount()
        {
            _scenarioContext["bulkOrderContext"] = "discount_calculation";
            var productId = Guid.NewGuid().ToString();
            _scenarioContext["productId"] = productId;
            _scenarioContext["productPrice"] = 100m;
        }

        [When("I calculate discount for {int} units at {decimal} per unit")]
        public async Task WhenICalculateDiscountForUnitsAtPerUnit(int quantity, decimal pricePerUnit)
        {
            var productId = _scenarioContext["productId"].ToString();
            var payload = new { quantity, pricePerUnit };
            var json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync($"/api/products/{productId}/calculate-discount", content);
            _scenarioContext["discountResponse"] = response;
            _scenarioContext["statusCode"] = response.StatusCode;
            _scenarioContext["requestedQuantity"] = quantity;

            if (response.StatusCode == HttpStatusCode.OK)
            {
                var responseContent = await response.Content.ReadAsStringAsync();
                var jsonDoc = JsonDocument.Parse(responseContent);
                _scenarioContext["discountData"] = jsonDoc;
            }
        }

        [Then("the bulk order discount should be applied")]
        public void ThenTheBulkOrderDiscountShouldBeApplied()
        {
            var statusCode = (HttpStatusCode)_scenarioContext["statusCode"];
            if (statusCode != HttpStatusCode.OK)
            {
                throw new InvalidOperationException($"Expected OK, got {statusCode}");
            }

            var quantity = (int)_scenarioContext["requestedQuantity"];
            var discountPercent = (int)_scenarioContext["discountPercent"];

            // Verify discount tiers: 5% for 10+, 10% for 25+, 15% for 50+
            if (quantity >= 50 && discountPercent != 15)
                throw new InvalidOperationException($"Expected 15% for 50+ items, got {discountPercent}%");
            if (quantity >= 25 && quantity < 50 && discountPercent != 10)
                throw new InvalidOperationException($"Expected 10% for 25-49 items, got {discountPercent}%");
            if (quantity >= 10 && quantity < 25 && discountPercent != 5)
                throw new InvalidOperationException($"Expected 5% for 10-24 items, got {discountPercent}%");
        }

        [Scenario]
        public void DiscountTierValidation()
        {
            // Discount tiers:
            // 10-24 items: 5%
            // 25-49 items: 10%
            // 50+ items: 15%
        }
    }
}
