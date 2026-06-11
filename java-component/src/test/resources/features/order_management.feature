Feature: Order management
  As an API consumer
  I want to place and retrieve orders through the REST API
  So that I can purchase products with correct pricing and discounts

  Background:
    Given the product catalog is empty
    And no orders exist
    And a product exists with name "Widget" and price 20.00

  Scenario: Place a simple order without discount
    When a client places an order for the last created product with quantity 5
    Then the response status should be 201
    And the response should contain an order id
    And the response should contain an order total of 100.00
    And the response should contain a discount of 0.0 percent

  Scenario Outline: Bulk discount tiers
    When a client places an order for the last created product with quantity <qty>
    Then the response status should be 201
    And the response should contain an order total of <total>
    And the response should contain a discount of <discount> percent

    Examples:
      | qty | total | discount |
      | 10  | 190.00 | 5.0 |
      | 50  | 900.00 | 10.0 |

  Scenario: Reject order exceeding total limit
    Given a product exists with name "Server" and price 100.00
    When a client places an order for the last created product with quantity 60
    Then the response status should be 422
    And the error message should contain "order total 5400.00 exceeds the 5000.00 limit"

  Scenario: Retrieve an existing order
    Given a product exists with name "Gizmo" and price 15.00
    When a client places an order for the last created product with quantity 2
    And a client requests the last created order
    Then the response status should be 200
    And the response should contain an order id
    And the response should contain an order total of 30.00

  Scenario: Retrieve a non‑existent order
    When a client requests the order with id 9999
    Then the response status should be 404
    And the error message should contain "Order not found"

  Scenario Outline: Order request validation errors
    When a client places an order with payload:
      """
      <payload>
      """
    Then the response status should be 400
    And the error message should contain "<message>"

    Examples:
      | payload                                 | message                                 |
      | {"productId": null, "quantity": 1}   | productId is required                   |
      | {"productId": 1, "quantity": 0}     | quantity must be at least 1             |
      | {"productId": 1, "quantity": 101}   | quantity must not exceed 100            |
