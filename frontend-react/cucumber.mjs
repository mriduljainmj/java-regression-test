// NOTE: no `default:` wrapper here, on purpose. cucumber-js loads an ESM config
// via `await import()` and uses the module namespace directly — the namespace's
// `default` key (this `export default`) already IS the "default" profile. Wrapping
// it in another `{ default: {...} }` nests the options one level too deep and they
// are silently ignored (0 scenarios). CJS configs (module.exports) DO need the
// wrapper; ESM export-default configs must not have it.
export default {
  // Feature files live under tests/features/ (not cucumber's default features/).
  paths: ["tests/features/**/*.feature"],
  import: ["tests/support/**/*.js", "tests/steps/**/*.js"],
  format: ["progress-bar", ["html", "reports/ui-report.html"], ["json", "reports/cucumber.json"]]
};
