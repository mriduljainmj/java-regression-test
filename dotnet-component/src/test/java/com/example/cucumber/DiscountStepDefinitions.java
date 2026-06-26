package com.example.cucumber;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.RestAssured;
import io.restassured.http.ContentType;
import io.restassured.response.Response;
import org.springframework.beans.factory.annotation.Autowired;

import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.closeTo;

public class DiscountStepDefinitions {

    @Autowired
    private TestContext context;

    @When("a client calculates discount for the last created product with quantity {int}")
    public void aClientCalculatesDiscountForTheLastCreatedProductWithQuantity(int quantity) {
        Long productId = context.getLastCreatedId("product");
        Response response = RestAssured.given()
                .contentType(ContentType.JSON)
                .body(quantity)
                .post("/products/" + productId + "/calculate-discount");
        context.setLastResponse(response);
    }

    @Then("the response should contain a product name {string}")
    public void theResponseShouldContainAProductName(String name) {
        assertThat(context.getLastResponse().jsonPath().getString("productName"), equalTo(name));
    }

    @Then("the response should contain unit price of {double}")
    public void theResponseShouldContainUnitPriceOf(double unitPrice) {
        assertThat(context.getLastResponse().jsonPath().getDouble("unitPrice"), closeTo(unitPrice, 0.001));
    }

    @Then("the response should contain original total of {double}")
    public void theResponseShouldContainOriginalTotalOf(double originalTotal) {
        assertThat(context.getLastResponse().jsonPath().getDouble("originalTotal"), closeTo(originalTotal, 0.001));
    }

    @Then("the response should contain discount amount of {double}")
    public void theResponseShouldContainDiscountAmountOf(double discountAmount) {
        assertThat(context.getLastResponse().jsonPath().getDouble("discountAmount"), closeTo(discountAmount, 0.001));
    }

    @Then("the response should contain final total of {double}")
    public void theResponseShouldContainFinalTotalOf(double finalTotal) {
        assertThat(context.getLastResponse().jsonPath().getDouble("finalTotal"), closeTo(finalTotal, 0.001));
    }
}
