const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const sourcePath = path.resolve(__dirname, "../../static/js/shared/product-area-colors.js");
const context = { window: {} };

vm.runInNewContext(fs.readFileSync(sourcePath, "utf8"), context, {
  filename: sourcePath
});

const { createResolver } = context.window.HymetryProductAreaColors;
const palette = ["#4269D0", "#EFB118"];
const resolveColor = (token) => ({
  "c-blue": "#4269D0",
  "c-orange": "#EFB118"
})[token] || token;

{
  const resolver = createResolver({ palette, resolveColor });
  resolver.add("Custom", "#A1B2C3");
  resolver.add("Token", "var(--color-c-orange)");
  resolver.finalize();

  assert.equal(resolver.color("Custom"), "#A1B2C3");
  assert.equal(resolver.color("Token"), "#EFB118");
}

{
  const resolver = createResolver({ palette, resolveColor });
  resolver.add("Unsafe", '\"><svg/onload=alert(1)>');
  resolver.add("Function", "rgb(1, 2, 3)");
  resolver.finalize();

  assert.equal(resolver.color("Unsafe"), "#4269D0");
  assert.equal(resolver.color("Function"), "#EFB118");
}

{
  const resolver = createResolver({ palette, resolveColor });
  resolver.add("Recovered", '\"><svg/onload=alert(1)>');
  resolver.add("Recovered", "#123456");
  resolver.finalize();

  assert.equal(resolver.color("Recovered"), "#123456");
}

console.log("product-area-colors tests passed");
