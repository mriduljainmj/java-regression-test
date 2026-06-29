using BoDi;
using TechTalk.SpecFlow;

namespace BP.Tests
{
    [Binding]
    public class Hooks
    {
        private readonly IObjectContainer _objectContainer;

        public Hooks(IObjectContainer objectContainer)
        {
            _objectContainer = objectContainer;
        }

        [BeforeScenario]
        public void BeforeScenario()
        {
            // Create HttpClient for testing
            var httpClient = new HttpClient
            {
                BaseAddress = new Uri("http://localhost:5000")
            };
            
            // Register HttpClient in the DI container for step definitions
            _objectContainer.RegisterInstanceAs(httpClient);
            _objectContainer.RegisterInstanceAs(new ScenarioContext());
        }

        [AfterScenario]
        public void AfterScenario()
        {
            // Cleanup after each scenario
        }
    }
}
