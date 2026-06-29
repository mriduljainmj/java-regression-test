Feature: Product Rating
  As a customer
  I want to rate products
  So that other customers can see my feedback

  Scenario: Rate a product with valid rating
    Given a product exists with id
    When I submit a rating of 5 for the product
    Then the rating should be accepted

  Scenario: Rate a product with minimum rating
    Given a product exists with id
    When I submit a rating of 1 for the product
    Then the rating should be accepted

  Scenario: Reject rating with invalid high value
    Given a product exists with id
    When I submit an invalid rating of 6
    Then the rating should be rejected with 400 status

  Scenario: Reject rating with invalid low value
    Given a product exists with id
    When I submit an invalid rating of 0
    Then the rating should be rejected with 400 status

  Scenario Outline: Rate product with various ratings
    Given I want to rate a product
    When I provide rating <rating>
    Then the product rating should be recorded

    Examples:
      | rating |
      | 1      |
      | 2      |
      | 3      |
      | 4      |
      | 5      |
