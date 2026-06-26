Feature: Calculate discount

  As a client of the Product API
  I want to calculate the discount for a product based on quantity
  So that I can see the pricing details before placing an order

  Scenario: Calculate discount for a product with no discount
    Given a product exists with name "Widget" and price 20.00
    When a client calculates discount for the last created product with quantity 5
    Then the response status should be 200
    And the response should contain a product id
    And the response should contain a product name "Widget"
    And the response should contain unit price of 20.00
    And the response should contain original total of 100.00
    And the response should contain a discount of 0.0 percent
    And the response should contain discount amount of 0.00
    And the response should contain final total of 100.00

  Scenario Outline: Calculate discount for bulk quantities
    Given a product exists with name "Widget" and price 20.00
    When a client calculates discount for the last created product with quantity <qty>
    Then the response status should be 200
    And the response should contain a product id
    And the response should contain a product name "Widget"
    And the response should contain unit price of 20.00
    And the response should contain original total of <original>
    And the response should contain a discount of <discount> percent
    And the response should contain discount amount of <amount>
    And the response should contain final total of <final>

    Examples:
      | qty | original | discount | amount | final |
      | 10  | 200.00   | 5.0      | 10.00  | 190.00 |
      | 50  | 1000.00  | 10.0     | 100.00 | 900.00 |
