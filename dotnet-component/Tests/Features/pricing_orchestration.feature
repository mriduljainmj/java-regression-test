Feature: Pricing orchestration

  As an API client
  I want API A to consume API B discount policy
  So that order totals are calculated from upstream policy responses

  Scenario Outline: API B returns discount policy for quantity and loyalty
    When a client requests the discount policy for quantity <quantity> and loyalty <loyalty>
    Then the response status should be 200
    And the response JSON should contain "BaseDiscountPercent": <base>
    And the response JSON should contain "LoyaltyDiscountPercent": <loyaltyPercent>
    And the response JSON should contain "TotalDiscountPercent": <total>
    And the response JSON should contain "PolicyVersion": "v1"

    Examples:
      | quantity | loyalty | base | loyaltyPercent | total |
      | 1        | false   | 0    | 0              | 0     |
      | 1        | true    | 0    | 12             | 12    |
      | 5        | false   | 0    | 0              | 0     |
      | 5        | true    | 0    | 12             | 12    |
      | 10       | false   | 8    | 0              | 8     |
      | 10       | true    | 8    | 12             | 20    |
      | 24       | false   | 8    | 0              | 8     |
      | 24       | true    | 8    | 12             | 20    |
      | 25       | false   | 15   | 0              | 15    |
      | 25       | true    | 15   | 12             | 27    |
      | 49       | false   | 15   | 0              | 15    |
      | 49       | true    | 15   | 12             | 27    |
      | 50       | false   | 18   | 0              | 18    |
      | 50       | true    | 18   | 12             | 30    |
      | 100      | true    | 18   | 12             | 30    |

  Scenario: API B rejects non-positive quantity
    When a client requests the discount policy for quantity 0 and loyalty false
    Then the response status should be 400
    And the response JSON should contain message "Quantity must be greater than 0."

  Scenario: API B rejects negative quantity
    When a client requests the discount policy for quantity -1 and loyalty false
    Then the response status should be 400
    And the response JSON should contain message "Quantity must be greater than 0."

  Scenario: API A calculates order total using API B response for loyalty member
    When a client submits an order total request with body
      """
      { "UnitPrice": 100.00, "Quantity": 1, "IsLoyaltyMember": true }
      """
    Then the response status should be 200
    And the response JSON should contain "TotalDiscountPercent": 12
    And the response JSON should contain decimal "Subtotal": 100.00
    And the response JSON should contain decimal "DiscountAmount": 12.00
    And the response JSON should contain decimal "FinalTotal": 88.00
    And the response JSON should contain "PolicyVersion": "v1"

  Scenario: API A calculates order total using API B response for non-loyalty member
    When a client submits an order total request with body
      """
      { "UnitPrice": 100.00, "Quantity": 1, "IsLoyaltyMember": false }
      """
    Then the response status should be 200
    And the response JSON should contain "TotalDiscountPercent": 0
    And the response JSON should contain decimal "Subtotal": 100.00
    And the response JSON should contain decimal "DiscountAmount": 0.00
    And the response JSON should contain decimal "FinalTotal": 100.00
    And the response JSON should contain "PolicyVersion": "v1"

  Scenario: API A calculates order total with tiered base and loyalty discount
    When a client submits an order total request with body
      """
      { "UnitPrice": 100.00, "Quantity": 25, "IsLoyaltyMember": true }
      """
    Then the response status should be 200
    And the response JSON should contain "TotalDiscountPercent": 27
    And the response JSON should contain decimal "Subtotal": 2500.00
    And the response JSON should contain decimal "DiscountAmount": 675.00
    And the response JSON should contain decimal "FinalTotal": 1825.00
    And the response JSON should contain "PolicyVersion": "v1"

  Scenario: API A calculates order total for high-volume loyalty order
    When a client submits an order total request with body
      """
      { "UnitPrice": 10.00, "Quantity": 50, "IsLoyaltyMember": true }
      """
    Then the response status should be 200
    And the response JSON should contain "TotalDiscountPercent": 30
    And the response JSON should contain decimal "Subtotal": 500.00
    And the response JSON should contain decimal "DiscountAmount": 150.00
    And the response JSON should contain decimal "FinalTotal": 350.00
    And the response JSON should contain "PolicyVersion": "v1"

  Scenario: API A rejects request with non-positive quantity
    When a client submits an order total request with body
      """
      { "UnitPrice": 10.00, "Quantity": 0, "IsLoyaltyMember": false }
      """
    Then the response status should be 400
    And the response JSON should contain message "UnitPrice and Quantity must be greater than 0."

  Scenario: API A rejects request with negative quantity
    When a client submits an order total request with body
      """
      { "UnitPrice": 10.00, "Quantity": -1, "IsLoyaltyMember": false }
      """
    Then the response status should be 400
    And the response JSON should contain message "UnitPrice and Quantity must be greater than 0."

  Scenario: API A rejects request with non-positive unit price
    When a client submits an order total request with body
      """
      { "UnitPrice": 0, "Quantity": 5, "IsLoyaltyMember": false }
      """
    Then the response status should be 400
    And the response JSON should contain message "UnitPrice and Quantity must be greater than 0."

  Scenario: API A rejects request with negative unit price
    When a client submits an order total request with body
      """
      { "UnitPrice": -10.00, "Quantity": 5, "IsLoyaltyMember": false }
      """
    Then the response status should be 400
    And the response JSON should contain message "UnitPrice and Quantity must be greater than 0."
