Feature: Product price validation

  As a client of the Product API
  I want to ensure that product prices are within allowed limits
  So that I can prevent invalid data from being stored

  Scenario: Create product with price exceeding maximum returns 400
    When a client POSTs /api/products with body
      """
      { "Name": "Expensive Product", "Price": 1000001, "InStock": true }
      """
    Then the response status should be 400
    And the response JSON should contain message "Product price must not exceed 1000000."

  Scenario: Create product with price equal to maximum allowed succeeds
    When a client POSTs /api/products with body
      """
      { "Name": "Max Price Product", "Price": 1000000, "InStock": true }
      """
    Then the response status should be 201
    And the response JSON should contain "Price": 1000000

  Scenario: Create with invalid price returns 400
    When a client POSTs /api/products with body
      """
      { "Name": "Bad Price", "Price": 0, "InStock": true }
      """
    Then the response status should be 400
