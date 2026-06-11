package com.example.products.cucumber;

import com.example.products.OrderService;
import com.example.products.ProductService;
import com.example.products.ReviewService;
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
import static org.hamcrest.Matchers.closeTo;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.hasItem;
import static org.hamcrest.Matchers.notNullValue;

public class ProductStepDefinitions {

    @LocalServerPort
    private int port;

    @Autowired
    private ProductService productService;

    @Autowired
    private OrderService orderService;

    @Autowired
    private ReviewService reviewService;

    // All response/id state is shared across glue classes via TestContext.
    @Autowired
    private TestContext context;

    @Before
    public void setUp() {
        RestAssured.baseURI = "http://localhost";
        RestAssured.port = port;
        RestAssured.basePath = "/api/v1";
    }

    @Given("the product catalog is empty")
    public void theProductCatalogIsEmpty() {
        reviewService.clear();
        orderService.clear();
        productService.clear();
    }

    @Given("no orders exist")
    public void noOrdersExist() {
        orderService.clear();
    }

    @Given("no reviews exist")
    public void noReviewsExist() {
        reviewService.clear();
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
        context.setLastCreatedId("product", response.jsonPath().getLong("id"));
    }

    @When("a client requests all products")
    public void aClientRequestsAllProducts() {
        context.setLastResponse(RestAssured.given().get("/products"));
    }

    @When("a client filters products with min price {double} and max price {double}")
    public void aClientFiltersProducts(double minPrice, double maxPrice) {
        context.setLastResponse(RestAssured.given()
                .queryParam("minPrice", minPrice)
                .queryParam("maxPrice", maxPrice)
                .get("/products"));
    }

    @When("a client filters products with min price {double}")
    public void aClientFiltersProductsByMinPrice(double minPrice) {
        context.setLastResponse(RestAssured.given()
                .queryParam("minPrice", minPrice)
                .get("/products"));
    }

    @When("a client filters products with max price {double}")
    public void aClientFiltersProductsByMaxPrice(double maxPrice) {
        context.setLastResponse(RestAssured.given()
                .queryParam("maxPrice", maxPrice)
                .get("/products"));
    }

    @When("a client places an order for the last created product with quantity {int}")
    public void aClientPlacesAnOrderForTheLastCreatedProduct(int quantity) {
        placeOrder(context.getLastCreatedId("product"), quantity);
    }

    @When("a client places an order for product id {long} with quantity {int}")
    public void aClientPlacesAnOrderForProductId(long productId, int quantity) {
        placeOrder(productId, quantity);
    }

    @When("a client places an order with payload:")
    public void aClientPlacesAnOrderWithPayload(String payload) {
        context.setLastResponse(RestAssured.given()
                .contentType(ContentType.JSON)
                .body(payload)
                .post("/orders"));
    }

    @When("a client requests the order with id {long}")
    public void aClientRequestsTheOrderWithId(long id) {
        context.setLastResponse(RestAssured.given().get("/orders/" + id));
    }

    @When("a client requests the last created order")
    public void aClientRequestsTheLastCreatedOrder() {
        context.setLastResponse(
                RestAssured.given().get("/orders/" + context.getLastCreatedId("order")));
    }

    private void placeOrder(Long productId, int quantity) {
        Map<String, Object> body = new HashMap<>();
        body.put("productId", productId);
        body.put("quantity", quantity);
        Response response = RestAssured.given()
                .contentType(ContentType.JSON)
                .body(body)
                .post("/orders");
        context.setLastResponse(response);
        if (response.statusCode() == 201) {
            context.setLastCreatedId("order", response.jsonPath().getLong("id"));
        }
    }

    @When("a client requests the product with id {long}")
    public void aClientRequestsTheProductWithId(long id) {
        context.setLastResponse(RestAssured.given().get("/products/" + id));
    }

    @When("a client requests the last created product")
    public void aClientRequestsTheLastCreatedProduct() {
        context.setLastResponse(
                RestAssured.given().get("/products/" + context.getLastCreatedId("product")));
    }

    @When("a client creates a product with name {string} and price {double}")
    public void aClientCreatesAProductWithNameAndPrice(String name, double price) {
        Map<String, Object> body = new HashMap<>();
        body.put("name", name);
        body.put("price", price);
        Response response = RestAssured.given()
                .contentType(ContentType.JSON)
                .body(body)
                .post("/products");
        context.setLastResponse(response);
        if (response.statusCode() == 201) {
            context.setLastCreatedId("product", response.jsonPath().getLong("id"));
        }
    }

    @When("a client creates a product with payload:")
    public void aClientCreatesAProductWithPayload(String payload) {
        context.setLastResponse(RestAssured.given()
                .contentType(ContentType.JSON)
                .body(payload)
                .post("/products"));
    }

    @When("a client updates the last created product with name {string} and price {double}")
    public void aClientUpdatesTheLastCreatedProduct(String name, double price) {
        Map<String, Object> body = new HashMap<>();
        body.put("name", name);
        body.put("price", price);
        context.setLastResponse(RestAssured.given()
                .contentType(ContentType.JSON)
                .body(body)
                .put("/products/" + context.getLastCreatedId("product")));
    }

    @When("a client updates the product with id {long} with name {string} and price {double}")
    public void aClientUpdatesTheProductWithId(long id, String name, double price) {
        Map<String, Object> body = new HashMap<>();
        body.put("name", name);
        body.put("price", price);
        context.setLastResponse(RestAssured.given()
                .contentType(ContentType.JSON)
                .body(body)
                .put("/products/" + id));
    }

    @When("a client deletes the last created product")
    public void aClientDeletesTheLastCreatedProduct() {
        context.setLastResponse(RestAssured.given()
                .delete("/products/" + context.getLastCreatedId("product")));
    }

    @When("a client deletes the product with id {long}")
    public void aClientDeletesTheProductWithId(long id) {
        context.setLastResponse(RestAssured.given().delete("/products/" + id));
    }

    @Then("the response status should be {int}")
    public void theResponseStatusShouldBe(int status) {
        context.getLastResponse().then().statusCode(status);
    }

    @Then("the response should contain a product id")
    public void theResponseShouldContainAProductId() {
        context.getLastResponse().then().body("id", notNullValue());
    }

    @Then("the response should contain a product with name {string}")
    public void theResponseShouldContainAProductWithName(String name) {
        // Works against both a single product object and a product list: on a
        // JSON array, jsonPath "name" collects every element's name.
        Response response = context.getLastResponse();
        String body = response.getBody().asString().trim();
        if (body.startsWith("[")) {
            response.then().body("name", hasItem(name));
        } else {
            response.then().body("name", equalTo(name));
        }
    }

    @Then("the response should contain {int} products")
    public void theResponseShouldContainProducts(int count) {
        context.getLastResponse().then().body("size()", equalTo(count));
    }

    @Then("the response should contain an order id")
    public void theResponseShouldContainAnOrderId() {
        context.getLastResponse().then().body("id", notNullValue());
    }

    @Then("the response should contain an order total of {double}")
    public void theResponseShouldContainAnOrderTotalOf(double total) {
        assertThat(context.getLastResponse().jsonPath().getDouble("total"), closeTo(total, 0.001));
    }

    @Then("the response should contain a discount of {double} percent")
    public void theResponseShouldContainADiscountOfPercent(double percent) {
        assertThat(context.getLastResponse().jsonPath().getDouble("discountPercent"),
                closeTo(percent, 0.001));
    }

    @Then("the error message should contain {string}")
    public void theErrorMessageShouldContain(String fragment) {
        assertThat(context.getLastResponse().jsonPath().getString("error"),
                containsString(fragment));
    }
}
