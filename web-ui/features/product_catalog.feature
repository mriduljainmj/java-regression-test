Feature: Product catalog management
  As a catalog operator
  I want to add, filter, and remove products through the web UI
  So that the catalog stays correct and enforces the same rules as the Products API

  Background:
    Given I am on the product catalog page

  Scenario: Add a valid product
    When I add a product named "Wireless Mouse" priced "49.99"
    Then the product "Wireless Mouse" appears in the catalog
    And the catalog shows 4 products
    And I see the confirmation "Product \"Wireless Mouse\" added."

  Scenario: Reject a product with a blank name
    When I add a product named "" priced "19.99"
    Then I see the validation error "name must not be blank"
    And the catalog shows 3 products

  Scenario: Reject a non-positive price
    When I add a product named "Free Sample" priced "0"
    Then I see the validation error "price must be greater than zero"

  Scenario: Reject a price above the cap
    When I add a product named "Gold Bar" priced "300001"
    Then I see the validation error "price must not exceed 300000.00"

  Scenario: Filter products by price range
    When I filter products with min price "50" and max price "100"
    Then the catalog shows 1 product
    And the product "Wireless Keyboard" appears in the catalog

  Scenario: Reject an inverted price range
    When I filter products with min price "100" and max price "50"
    Then I see the validation error "minPrice must not be greater than maxPrice"

  Scenario: Delete a product
    When I delete the product "USB-C Hub"
    Then the product "USB-C Hub" is no longer in the catalog
    And the catalog shows 2 products
