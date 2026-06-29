Feature: Bulk Order Discount Calculation
  As a bulk buyer
  I want to know the discount for large orders
  So that I can calculate the total cost

  Scenario: 5% discount for 10-24 items
    Given a product with price 100 exists
    When I request a bulk discount for 15 items
    Then the discount should be 5%
    And the response should include the total price

  Scenario: 10% discount for 25-49 items
    Given a product with price 100 exists
    When I request a bulk discount for 30 items
    Then the discount should be 10%
    And the response should include the total price

  Scenario: 15% discount for 50+ items
    Given a product with price 100 exists
    When I request a bulk discount for 75 items
    Then the discount should be 15%
    And the response should include the total price

  Scenario: No discount for less than 10 items
    Given a product with price 100 exists
    When I request a bulk discount for 5 items
    Then the discount should be 0%
    And the response should include the total price

  Scenario Outline: Validate discount tiers
    Given I want to calculate bulk order discount
    When I calculate discount for <quantity> units at 100 per unit
    Then the bulk order discount should be applied

    Examples:
      | quantity |
      | 1        |
      | 10       |
      | 25       |
      | 50       |
      | 100      |
