Feature: Pricing orchestration

  As an API client
  I want API A to consume API B discount policy
  So that order totals are calculated from upstream policy responses

  Scenario Outline: API B returns discount policy for quantity and loyalty
    When a client requests GET /api/discount-policy with quantity <quantity> and loyalty <loyalty>
    Then the response status should be 200
    And the response JSON should contain "BaseDiscountPercent": <base>
    And the response JSON should contain "LoyaltyDiscountPercent": <loyaltyPercent>
    And the response JSON should contain "TotalDiscountPercent": <total>
    And the response JSON should contain "PolicyVersion": "v1"

    Examples:
      | quantity | loyalty | base | loyaltyPercent | total |
      | 5        | false   | 0    | 0               | 0     |
      | 5        | true    | 0    | 5               | 5     |
      | 10       | false   | 8    | 0               | 8     |
      | 10       | true    | 8    | 5               | 13    |
      | 24       | false   | 8    | 0               | 8     |
      | 24       | true    | 8    | 5               | 13    |
      | 25       | false   | 15   | 0               | 15    |
      | 25       | true    | 15   | 5               | 20    |
      | 49       | false   | 15   | 0               | 15    |
      | 49       | true    | 15   | 5               | 20    |
      | 50       | false   | 18   | 0               | 18    |
      | 50       | true    | 18   | 5               | 23    |
      | 100      | true    | 18   | 5               | 23    |

  Scenario: API A calculates order total using API B response
    When a client POSTs /api/order-total-from-policy with body
      """
      { "UnitPrice": 100.00, "Quantity": 1, "IsLoyaltyMember": true }
      """
    Then the response status should be 200
    And the response JSON should contain "TotalDiscountPercent": 5
    And the response JSON should contain decimal "FinalTotal": 95.00
    And the response JSON should contain "PolicyVersion": "v1"

  Scenario: API A rejects request with non‑positive quantity
    When a client POSTs /api/order-total-from-policy with body
      """
      { "UnitPrice": 10.00, "Quantity": 0, "IsLoyaltyMember": false }
      """
    Then the response status should be 400
    And the response JSON should contain message "UnitPrice and Quantity must be greater than 0."

  Scenario: API A rejects request with non‑positive unit price
    When a client POSTs /api/order-total-from-policy with body
      """
      { "UnitPrice": 0, "Quantity": 5, "IsLoyaltyMember": false }
      """
    Then the response status should be 400
