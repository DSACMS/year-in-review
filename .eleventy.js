module.exports = function (config) {
  config.addPassthroughCopy({ "metrics_data/data": "data" });
  config.addPassthroughCopy("src/metrics-data.js");

  // Set pathPrefix for site
  let pathPrefix = '/';

  return {
    dir: {
      input: "src",
      includes: "_includes",
      output: "_site",
    },

    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
    templateFormats: ["md", "njk", "html"],
    pathPrefix,
  };
};
