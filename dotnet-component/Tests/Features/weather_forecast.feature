Feature: Weather forecast

  As a client of the WeatherForecast API
  I want to retrieve the available forecasts
  So that I can show upcoming weather to users

  Scenario: Get weather forecasts returns five items
    When a client requests GET /WeatherForecast
    Then the response status should be 200
    And the response JSON array length should be 5
    And each item should contain fields "Date", "TemperatureC", "Summary"
