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
            // Setup before each scenario
        }

        [AfterScenario]
        public void AfterScenario()
        {
            // Cleanup after each scenario
        }
    }
}
