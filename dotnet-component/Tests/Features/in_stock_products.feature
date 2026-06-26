Feature: In-stock product listing

  As a client of the Product API
  I want to retrieve products that are in stock
  So that I can see available inventory

  Scenario: Get all in-stock products
    When a client requests the in-stock products
    Then the response status should be 200
    And the response should contain a total of 0
    And the response JSON array "items" should have length 0

  Scenario: Get in-stock products when some are available
    Given a product exists with id 1
    And a product exists with id 2
    When a client requests the in-stock products
    Then the response status should be 200
    And the response should contain a total of 2
    And the response JSON array "items" should have length 2
    And the response JSON array "items" should contain a product with name "Widget"
    And the response JSON array "items" should contain a product with name "Gadget"
