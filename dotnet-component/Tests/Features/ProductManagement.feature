Feature: Product management
  As an API consumer
  I want to manage products through the REST API
  So that the product catalog stays accurate

  Scenario: Create a valid product
    When a client creates a product with name 'Laptop' and price 999.99
    Then the response status should be 201
    And the response should contain a product id
    And the response should contain a product with name 'Laptop'

  Scenario: Retrieve a product that does not exist
    When a client requests the product with id 9999
    Then the response status should be 404
    And the error message should contain 'Product not found'
