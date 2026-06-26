using io.cucumber.java.en.Given;
using io.cucumber.java.en.Then;
using io.cucumber.java.en.When;
using io.restassured.RestAssured;
using io.restassured.http.ContentType;
using io.restassured.response.Response;
using org.hamcrest.Matchers;
using static org.hamcrest.MatcherAssert.assertThat;
using static org.hamcrest.Matchers.*;

public class InStockStepDefinitions
{
    private Response lastResponse;

    @When("a client requests the in-stock products")
    public void aClientRequestsTheInStockProducts()
    {
        lastResponse = RestAssured.given()
                .get("/products/in-stock");
    }

    @Then("the response should contain a total of {int}")
    public void theResponseShouldContainATotalOf(int total)
    {
        assertThat(lastResponse.jsonPath().getInt("total"), equalTo(total));
    }

    @Then("the response JSON array {string} should have length {int}")
    public void theResponseJSONArrayShouldHaveLength(String arrayName, int length)
    {
        assertThat(lastResponse.jsonPath().getList(arrayName).size(), equalTo(length));
    }

    @Then("the response JSON array {string} should contain a product with name {string}")
    public void theResponseJSONArrayShouldContainAProductWithName(String arrayName, String name)
    {
        assertThat(lastResponse.jsonPath().getList(arrayName + ".name"), hasItem(name));
    }

    @Given("a product exists with id {int}")
    public void aProductExistsWithId(int id)
    {
        // This step relies on existing ProductStepDefinitions to create a product.
        // It is kept here to satisfy the Gherkin step; the actual creation logic
        // is handled by the shared TestContext and step definitions in the Java
        // test suite. No additional code is required in this glue file.
    }
}
