package com.example.products.cucumber;

import io.cucumber.spring.ScenarioScope;
import io.restassured.response.Response;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

/**
 * Shared state for ALL step-definition classes. Scenario-scoped: a fresh
 * instance is created for every scenario, so state never leaks between
 * scenarios or between glue classes.
 *
 * New step-definition classes must @Autowired this class instead of declaring
 * their own lastResponse / last-created-id fields — private fields in one glue
 * class are invisible to every other glue class.
 */
@Component
@ScenarioScope
public class TestContext {

    private Response lastResponse;
    private final Map<String, Long> lastCreatedIds = new HashMap<>();

    public Response getLastResponse() {
        if (lastResponse == null) {
            throw new IllegalStateException("No request has been made yet in this scenario");
        }
        return lastResponse;
    }

    public void setLastResponse(Response lastResponse) {
        this.lastResponse = lastResponse;
    }

    public void setLastCreatedId(String entity, Long id) {
        lastCreatedIds.put(entity, id);
    }

    public Long getLastCreatedId(String entity) {
        Long id = lastCreatedIds.get(entity);
        if (id == null) {
            throw new IllegalStateException(
                    "No " + entity + " has been created in this scenario yet");
        }
        return id;
    }
}
