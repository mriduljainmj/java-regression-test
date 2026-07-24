module.exports = {
  default: {
    require: ["features/support/**/*.js", "features/steps/**/*.js"],
    publishQuiet: true,
    format: ["progress-bar", ["html", "reports/ui-report.html"]]
  }
};
