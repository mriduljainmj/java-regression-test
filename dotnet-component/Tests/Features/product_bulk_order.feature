Feature: Bulk order validation and inventory summary

  As a client of the Product API
  I want to validate bulk orders and view inventory statistics
  So that I can ensure orders are acceptable and monitor stock levels

  Scenario: Validate a valid bulk order
    Given a product exists with name "Widget" and price 20.00 and in stock
    When a client validates bulk order for the last created product with quantity 20
    Then the response status should be 200
    And the response JSON should contain "isValid" with value true
    And the response JSON should contain "productId" with value <captured>
    And the response JSON should contain "quantity" with value 20
    And the response JSON should contain "totalPrice" with value 380.0
    And the response JSON should contain "discountPercent" with value 5

  Scenario: Validate bulk order for a non‑existent product
    When a client validates bulk order for product id 9999 with quantity 10
    Then the response status should be 400
    And the response JSON should contain "message" with value "Invalid bulk order: product not found, out of stock, quantity invalid, or exceeds limit (1000)."

  Scenario: Inventory summary reflects current stock
    Given a product exists with name "Alpha" and price 10.00 and in stock
    And a product exists with name "Beta" and price 15.00 and in stock
    When a client requests inventory summary
    Then the response status should be 200
    And the response JSON should contain "totalProducts" with value 2
    And the response JSON should contain "inStockCount" with value 2
    And the response JSON should contain "outOfStockCount" with value 0
    And the response JSON should contain "inventoryPercentage" with value 100.0
