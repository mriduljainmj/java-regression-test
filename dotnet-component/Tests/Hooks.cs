using System;
using System.Net.Http;
using Microsoft.AspNetCore.Mvc.Testing;
using BoDi;
using TechTalk.SpecFlow;

namespace BP.Tests
{
    [Binding]
    public class Hooks
    {
        private readonly IObjectContainer _objectContainer;
        private WebApplicationFactory<Program>? _factory;
        private HttpClient? _httpClient;

        public Hooks(IObjectContainer objectContainer)
        {
            _objectContainer = objectContainer;
        }

        [BeforeScenario]
        public void BeforeScenario()
        {
            _factory = new WebApplicationFactory<Program>();
            _httpClient = _factory.CreateClient();

            _objectContainer.RegisterInstanceAs(_httpClient);
        }

        [AfterScenario]
        public void AfterScenario()
        {
            _httpClient?.Dispose();
            _factory?.Dispose();
        }
    }
}
