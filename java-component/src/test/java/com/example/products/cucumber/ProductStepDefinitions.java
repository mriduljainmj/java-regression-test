package com.example.products.cucumber;

import com.example.products.ProductService;
import io.cucumber.java.Before;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.RestAssured;
import io.restassured.http.ContentType;
import io.restassured.response.Response;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalServerPort;

import java.util.HashMap;
import java.util.Map;

import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.notNullValue;

public class ProductStepDefinitions {

    @LocalServerPort
    private int port;

    @Autowired
    private ProductService productService;

    private Response lastResponse;
    private Long lastCreatedProductId;

    @Before
    public void setUp() {
        RestAssured.baseURI = "http://localhost";
        RestAssured.port = port;
        RestAssured.basePath = "/api/v1";
    }

    @Given("the product catalog is empty")
    public void theProductCatalogIsEmpty() {
        productService.clear();
    }

    @Given("a product exists with name {string} and price {double}")
    public void aProductExistsWithNameAndPrice(String name, double price) {
        Map<String, Object> body = new HashMap<>();
        body.put("name", name);
        body.put("price", price);
        Response response = RestAssured.given()
                .contentType(ContentType.JSON)
                .body(body)
                .post("/products");
        response.then().statusCode(201);
        lastCreatedProductId = response.jsonPath().getLong("id");
    }

    @When("a client requests all products")
    public void aClientRequestsAllProducts() {
        lastResponse = RestAssured.given().get("/products");
    }

    @When("a client requests the product with id {long}")
    public void aClientRequestsTheProductWithId(long id) {
        lastResponse = RestAssured.given().get("/products/" + id);
    }

    @When("a client requests the last created product")
    public void aClientRequestsTheLastCreatedProduct() {
        lastResponse = RestAssured.given().get("/products/" + lastCreatedProductId);
    }

    @When("a client creates a product with name {string} and price {double}")
    public void aClientCreatesAProductWithNameAndPrice(String name, double price) {
        Map<String, Object> body = new HashMap<>();
        body.put("name", name);
        body.put("price", price);
        lastResponse = RestAssured.given()
                .contentType(ContentType.JSON)
                .body(body)
                .post("/products");
        if (lastResponse.statusCode() == 201) {
            lastCreatedProductId = lastResponse.jsonPath().getLong("id");
        }
    }

    @When("a client creates a product with payload:")
    public void aClientCreatesAProductWithPayload(String payload) {
        lastResponse = RestAssured.given()
                .contentType(ContentType.JSON)
                .body(payload)
                .post("/products");
    }

    @When("a client updates the last created product with name {string} and price {double}")
    public void aClientUpdatesTheLastCreatedProduct(String name, double price) {
        Map<String, Object> body = new HashMap<>();
        body.put("name", name);
        body.put("price", price);
        lastResponse = RestAssured.given()
                .contentType(ContentType.JSON)
                .body(body)
                .put("/products/" + lastCreatedProductId);
    }

    @When("a client updates the product with id {long} with name {string} and price {double}")
    public void aClientUpdatesTheProductWithId(long id, String name, double price) {
        Map<String, Object> body = new HashMap<>();
        body.put("name", name);
        body.put("price", price);
        lastResponse = RestAssured.given()
                .contentType(ContentType.JSON)
                .body(body)
                .put("/products/" + id);
    }

    @When("a client deletes the last created product")
    public void aClientDeletesTheLastCreatedProduct() {
        lastResponse = RestAssured.given().delete("/products/" + lastCreatedProductId);
    }

    @When("a client deletes the product with id {long}")
    public void aClientDeletesTheProductWithId(long id) {
        lastResponse = RestAssured.given().delete("/products/" + id);
    }

    @Then("the response status should be {int}")
    public void theResponseStatusShouldBe(int status) {
        lastResponse.then().statusCode(status);
    }

    @Then("the response should contain a product id")
    public void theResponseShouldContainAProductId() {
        lastResponse.then().body("id", notNullValue());
    }

    @Then("the response should contain a product with name {string}")
    public void theResponseShouldContainAProductWithName(String name) {
        lastResponse.then().body("name", equalTo(name));
    }

    @Then("the response should contain {int} products")
    public void theResponseShouldContainProducts(int count) {
        lastResponse.then().body("size()", equalTo(count));
    }

    @Then("the error message should contain {string}")
    public void theErrorMessageShouldContain(String fragment) {
        assertThat(lastResponse.jsonPath().getString("error"), containsString(fragment));
    }
}
