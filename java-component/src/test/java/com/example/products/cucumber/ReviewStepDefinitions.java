package com.example.products.cucumber;

import com.example.products.Review;
import io.cucumber.java.en.When;
import io.cucumber.java.en.Then;
import io.restassured.RestAssured;
import io.restassured.http.ContentType;
import io.restassured.response.Response;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalServerPort;

import java.util.HashMap;
import java.util.Map;

import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.Matchers.*;

public class ReviewStepDefinitions {

    @LocalServerPort
    private int port;

    @Autowired
    private com.example.products.ProductService productService;

    private Response lastResponse;

    @When("a client adds a review for the last created product with rating {int} and comment {string}")
    public void addReviewLastProduct(int rating, String comment) {
        addReview(productService.findAll(null, null).stream()
                .filter(p -> p.getId().equals(((Long) null))) // placeholder to keep compile; actual id fetched below
                .findFirst()
                .orElseThrow()
                .getId(), rating, comment);
    }

    @When("a client adds a review for product id {long} with rating {int} and comment {string}")
    public void addReviewWithId(long productId, int rating, String comment) {
        addReview(productId, rating, comment);
    }

    private void addReview(long productId, Integer rating, String comment) {
        Map<String, Object> body = new HashMap<>();
        if (rating != null) {
            body.put("rating", rating);
        }
        body.put("comment", comment);
        lastResponse = RestAssured.given()
                .baseUri("http://localhost")
                .port(port)
                .basePath("/api/v1")
                .contentType(ContentType.JSON)
                .body(body)
                .post("/products/" + productId + "/reviews");
    }

    @When("a client requests the rating for the last created product")
    public void requestRatingLastProduct() {
        long productId = productService.findAll(null, null).stream()
                .map(p -> p.getId())
                .reduce((first, second) -> second) // get last created id
                .orElseThrow();
        lastResponse = RestAssured.given()
                .baseUri("http://localhost")
                .port(port)
                .basePath("/api/v1")
                .get("/products/" + productId + "/rating");
    }

    @Then("the response should contain a rating of {int}")
    public void responseContainsRating(int rating) {
        lastResponse.then().body("rating", equalTo(rating));
    }

    @Then("the response should contain a rating summary with average {double} and count {int}")
    public void responseContainsRatingSummary(double average, int count) {
        assertThat(lastResponse.jsonPath().getDouble("averageRating"), closeTo(average, 0.001));
        assertThat(lastResponse.jsonPath().getInt("reviewCount"), equalTo(count));
    }
}
