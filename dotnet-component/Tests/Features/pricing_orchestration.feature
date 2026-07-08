Feature: Pricing orchestration

  As an API client
  I want API A to consume API B discount policy
  So that order totals are calculated from upstream policy responses

  Scenario: API B returns discount policy for quantity and loyalty
    When a client requests GET /api/discount-policy with quantity 25 and loyalty true
    Then the response status should be 200
    And the response JSON should contain "BaseDiscountPercent": 10
    And the response JSON should contain "LoyaltyDiscountPercent": 5
    And the response JSON should contain "TotalDiscountPercent": 15
    And the response JSON should contain "PolicyVersion": "v1"

  Scenario: API A calculates order total using API B response
    When a client POSTs /api/order-total-from-policy with body
      """
      { "UnitPrice": 100.00, "Quantity": 1, "IsLoyaltyMember": true }
      """
    Then the response status should be 200
    And the response JSON should contain "TotalDiscountPercent": 5
    And the response JSON should contain decimal "FinalTotal": 95.00
    And the response JSON should contain "PolicyVersion": "v1"
