Feature: User management

  As a client of the User API
  I want to request user details by id
  So that I receive the expected user data or a clear not-found error

  Scenario: Get existing user by id
    Given a user exists with id 1
    When a client requests GET /api/GetUserById with userId 1
    Then the response status should be 200
    And the response JSON should contain "UserId": 1
    And the response JSON should contain "Name": "Alice Johnson"

  Scenario: Get non-existent user returns 404 with message
    When a client requests GET /api/GetUserById with userId 9999
    Then the response status should be 404
    And the response JSON should contain message "User with ID 9999 was not found."
