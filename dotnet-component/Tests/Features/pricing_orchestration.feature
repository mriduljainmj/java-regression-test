Feature: Pricing orchestration

  As an API client
  I want API A to consume API B discount policy
  So that order totals are calculated from upstream policy responses

  Scenario: API B returns discount policy for quantity and loyalty
    When a client requests GET /api/discount-policy with quantity 25 and loyalty true
    Then the response status should be 200
    And the response JSON should contain "BaseDiscountPercent": 12
    And the response JSON should contain "LoyaltyDiscountPercent": 7
    And the response JSON should contain "TotalDiscountPercent": 19
    And the response JSON should contain "PolicyVersion": "v1"

  Scenario: API A calculates order total using API B response
    When a client POSTs /api/order-total-from-policy with body
      """
      { "UnitPrice": 100.00, "Quantity": 1, "IsLoyaltyMember": true }
      """
    Then the response status should be 200
    And the response JSON should contain "TotalDiscountPercent": 7
    And the response JSON should contain decimal "FinalTotal": 93.00
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
    And the response JSON should contain message "UnitPrice and Quantity must be greater than 0."
