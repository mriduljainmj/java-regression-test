Feature: In‑stock product count

  As a client of the Product API
  I want to know how many products are currently in stock
  So that I can display inventory information

  Scenario: Count is zero when no products exist
    Given the product catalog is empty
    When a client requests GET /api/products/in-stock-count
    Then the response status should be 200
    And the response JSON should contain "count": 0

  Scenario: Count reflects only in‑stock products
    Given the product catalog is empty
    And a product exists with payload:
      """
      { "Name": "Widget A", "Price": 10.0, "InStock": true }
      """
    And a product exists with payload:
      """
      { "Name": "Widget B", "Price": 15.0, "InStock": false }
      """
    And a product exists with payload:
      """
      { "Name": "Widget C", "Price": 20.0, "InStock": true }
      """
    When a client requests GET /api/products/in-stock-count
    Then the response status should be 200
    And the response JSON should contain "count": 2
