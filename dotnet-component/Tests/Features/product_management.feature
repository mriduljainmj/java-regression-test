Feature: Product management

  As a client of the Product API
  I want to create, retrieve, update and delete products
  So that I can manage inventory

  Scenario: Create a valid product
    When a client POSTs /api/products with body
      """
      { "Name": "New Thing", "Price": 12.5, "InStock": true }
      """
    Then the response status should be 201
    And the response JSON should contain "Name": "New Thing"

  Scenario: Create with invalid price returns 400
    When a client POSTs /api/products with body
      """
      { "Name": "Bad Price", "Price": 0, "InStock": true }
      """
    Then the response status should be 400

  Scenario: Get created product by id
    Given a product exists with id 1
    When a client requests GET /api/products/1
    Then the response status should be 200
    And the response JSON should contain "ProductId": 1

  Scenario: Get non-existent product returns 404 and message
    When a client requests GET /api/products/9999
    Then the response status should be 404
    And the response JSON should contain message "Product with ID 9999 was not found."

  Scenario: Update existing product
    Given a product exists with id 1
    When a client PUTs /api/products/1 with body
      """
      { "Name": "Widget Updated", "Price": 11.0, "InStock": false }
      """
    Then the response status should be 204

  Scenario: Delete a product
    Given a product exists with id 2
    When a client DELETEs /api/products/2
    Then the response status should be 204

  Scenario: Update product stock status to out of stock
    Given a product exists with id 1
    When a client PATCHes /api/products/1/stock with body
      """
      false
      """
    Then the response status should be 200
    And the response JSON should contain "InStock": false

  Scenario: Update product stock status to in stock
    Given a product exists with id 1
    When a client PATCHes /api/products/1/stock with body
      """
      true
      """
    Then the response status should be 200
    And the response JSON should contain "InStock": true

  Scenario: Update stock for non-existent product returns 404
    When a client PATCHes /api/products/9999/stock with body
      """
      false
      """
    Then the response status should be 404
    And the response JSON should contain message "Product with ID 9999 was not found."
