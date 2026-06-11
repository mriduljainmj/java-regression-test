package com.example.products.cucumber;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.RestAssured;
import io.restassured.http.ContentType;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.HashMap;
import java.util.Map;

import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.Matchers.closeTo;
import static org.hamcrest.Matchers.equalTo;

public class ReviewStepDefinitions {

    @Autowired
    private TestContext context;

    @When("a client adds a review for the last created product with rating {int} and comment {string}")
    public void addReviewLastProduct(int rating, String comment) {
        addReview(context.getLastCreatedId("product"), rating, comment);
    }

    @When("a client adds a review for product id {long} with rating {int} and comment {string}")
    public void addReviewWithId(long productId, int rating, String comment) {
        addReview(productId, rating, comment);
    }

    @When("a client adds a review for the last created product with payload:")
    public void addReviewWithPayload(String payload) {
        context.setLastResponse(RestAssured.given()
                .contentType(ContentType.JSON)
                .body(payload)
                .post("/products/" + context.getLastCreatedId("product") + "/reviews"));
    }

    private void addReview(long productId, int rating, String comment) {
        Map<String, Object> body = new HashMap<>();
        body.put("rating", rating);
        body.put("comment", comment);
        context.setLastResponse(RestAssured.given()
                .contentType(ContentType.JSON)
                .body(body)
                .post("/products/" + productId + "/reviews"));
    }

    @When("a client requests the rating for the last created product")
    public void requestRatingLastProduct() {
        context.setLastResponse(RestAssured.given()
                .get("/products/" + context.getLastCreatedId("product") + "/rating"));
    }

    @When("a client requests the rating for product id {long}")
    public void requestRatingForProductId(long productId) {
        context.setLastResponse(RestAssured.given()
                .get("/products/" + productId + "/rating"));
    }

    @Then("the response should contain a rating of {int}")
    public void responseContainsRating(int rating) {
        context.getLastResponse().then().body("rating", equalTo(rating));
    }

    @Then("the response should contain a rating summary with average {double} and count {int}")
    public void responseContainsRatingSummary(double average, int count) {
        assertThat(context.getLastResponse().jsonPath().getDouble("averageRating"),
                closeTo(average, 0.001));
        assertThat(context.getLastResponse().jsonPath().getInt("reviewCount"), equalTo(count));
    }
}
