Feature: Review management
  As an API consumer
  I want to add reviews to products and retrieve rating summaries
  So that I can see aggregated feedback for each product

  Background:
    Given the product catalog is empty
    And a product exists with name "Phone" and price 299.99

  Scenario: Add a valid review
    When a client adds a review for the last created product with rating 4 and comment "Great phone"
    Then the response status should be 201
    And the response should contain a product id
    And the response should contain a rating of 4

  Scenario: Accept the minimum valid rating
    When a client adds a review for the last created product with rating 3 and comment "Okay"
    Then the response status should be 201
    And the response should contain a rating of 3

  Scenario: Rating summary after multiple reviews
    When a client adds a review for the last created product with rating 4 and comment "Good"
    And a client adds a review for the last created product with rating 5 and comment "Excellent"
    When a client requests the rating for the last created product
    Then the response status should be 200
    And the response should contain a rating summary with average 4.5 and count 2

  Scenario Outline: Reject out-of-range review ratings
    When a client adds a review for the last created product with rating <rating> and comment "Bad rating"
    Then the response status should be 400
    And the error message should contain "<message>"

    Examples:
      | rating | message                   |
      | 2      | rating must be at least 3 |
      | 6      | rating must not exceed 5  |

  Scenario: Reject a review without a rating
    When a client adds a review for the last created product with payload:
      """
      {"comment": "No rating given"}
      """
    Then the response status should be 400
    And the error message should contain "rating is required"

  Scenario: Reject a review for a product that does not exist
    When a client adds a review for product id 9999 with rating 4 and comment "Ghost"
    Then the response status should be 404
    And the error message should contain "Product not found"

  Scenario: Rating summary for a product with no reviews
    When a client requests the rating for the last created product
    Then the response status should be 404
    And the error message should contain "No reviews found"
