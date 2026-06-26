package com.example.cucumber;

import io.cucumber.java.en.And;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.RestAssured;
import io.restassured.http.ContentType;
import io.restassured.response.Response;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.HashMap;
import java.util.Map;

import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.Matchers.*;

public class ProductBulkOrderStepDefinitions {

    @Autowired
    private TestContext context;

    @Given("a product exists with name {string} and price {double} and in stock")
    public void aProductExistsWithNameAndPriceAndInStock(String name, double price) {
        Map<String, Object> body = new HashMap<>();
        body.put("Name", name);
        body.put("Price", price);
        body.put("InStock", true);
        Response response = RestAssured.given()
                .contentType(ContentType.JSON)
                .body(body)
                .post("/api/products");
        response.then().statusCode(201);
        context.setLastCreatedId("product", response.jsonPath().getLong("id"));
    }

    @When("a client validates bulk order for the last created product with quantity {int}")
    public void validateBulkOrderForLastCreatedProduct(int quantity) {
        Long productId = context.getLastCreatedId("product");
        Response response = RestAssured.given()
                .contentType(ContentType.JSON)
                .body(quantity)
                .post("/api/products/" + productId + "/validate-bulk-order");
        context.setLastResponse(response);
    }

    @When("a client validates bulk order for product id {int} with quantity {int}")
    public void validateBulkOrderForProductId(int productId, int quantity) {
        Response response = RestAssured.given()
                .contentType(ContentType.JSON)
                .body(quantity)
                .post("/api/products/" + productId + "/validate-bulk-order");
        context.setLastResponse(response);
    }

    @When("a client requests inventory summary")
    public void requestInventorySummary() {
        Response response = RestAssured.given()
                .get("/api/products/inventory-summary");
        context.setLastResponse(response);
    }

    @Then("the response JSON should contain {string} with value {string}")
    public void responseJsonShouldContainStringValue(String field, String expected) {
        assertThat(context.getLastResponse().jsonPath().getString(field), equalTo(expected));
    }

    @Then("the response JSON should contain {string} with value {int}")
    public void responseJsonShouldContainIntValue(String field, int expected) {
        assertThat(context.getLastResponse().jsonPath().getInt(field), equalTo(expected));
    }

    @Then("the response JSON should contain {string} with value {double}")
    public void responseJsonShouldContainDoubleValue(String field, double expected) {
        assertThat(context.getLastResponse().jsonPath().getDouble(field), closeTo(expected, 0.001));
    }

    @Then("the response JSON should contain {string} with value true")
    public void responseJsonShouldContainTrue(String field) {
        assertThat(context.getLastResponse().jsonPath().getBoolean(field), is(true));
    }

    @And("the response JSON should contain {string} with value <captured>")
    public void responseJsonShouldContainCaptured(String field) {
        // The placeholder <captured> refers to the last created product id.
        Long expected = context.getLastCreatedId("product");
        assertThat(context.getLastResponse().jsonPath().getLong(field), equalTo(expected));
    }
}
