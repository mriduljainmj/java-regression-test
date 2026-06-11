Feature: Product management
  As an API consumer
  I want to manage products through the REST API
  So that the product catalog stays accurate

  Background:
    Given the product catalog is empty

  Scenario: Retrieve an empty product catalog
    When a client requests all products
    Then the response status should be 200
    And the response should contain 0 products

  Scenario: Create a valid product
    When a client creates a product with name "Laptop" and price 999.99
    Then the response status should be 201
    And the response should contain a product id
    And the response should contain a product with name "Laptop"

  Scenario Outline: Reject invalid product creation requests
    When a client creates a product with name "<name>" and price <price>
    Then the response status should be 400
    And the error message should contain "<message>"

    Examples:
      | name   | price | message                         |
      |        | 9.99  | name must not be blank          |
      | Laptop | 0     | price must be greater than zero |
      | Laptop | -5.00 | price must be greater than zero |

  Scenario: Retrieve a product that does not exist
    When a client requests the product with id 9999
    Then the response status should be 404
    And the error message should contain "Product not found"

  Scenario: Update an existing product
    Given a product exists with name "Laptop" and price 999.99
    When a client updates the last created product with name "Gaming Laptop" and price 1299.99
    Then the response status should be 200
    And the response should contain a product with name "NewUpdatedProdGaming Laptop"

  Scenario: Delete an existing product
    Given a product exists with name "Laptop" and price 999.99
    When a client deletes the last created product
    Then the response status should be 204

  Scenario: Delete a product that does not exist
    When a client deletes the product with id 9999
    Then the response status should be 404
