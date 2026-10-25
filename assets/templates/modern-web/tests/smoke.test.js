// Smoke test for the modern-web template.
// Node-compatible and dependency-free. Run with: node tests/smoke.test.js
"use strict";

const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
let failures = 0;

function check(name, condition) {
  if (condition) {
    console.log("ok - " + name);
  } else {
    failures += 1;
    console.error("FAIL - " + name);
  }
}

const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "styles.css"), "utf8");
const js = fs.readFileSync(path.join(root, "app.js"), "utf8");

check("index.html is non-empty", html.length > 0);
check("index.html starts with doctype", /^<!DOCTYPE html>/i.test(html));
check("index.html links local stylesheet", /<link[^>]+href="styles\.css"/.test(html));
check("index.html loads local script", /<script[^>]+src="app\.js"/.test(html));
check("index.html is responsive", /name="viewport"/.test(html));
check("styles.css is non-empty", css.trim().length > 0);
check("app.js is non-empty", js.trim().length > 0);
check("app.js registers an event listener", /addEventListener/.test(js));

if (failures > 0) {
  console.error(failures + " smoke check(s) failed");
  process.exit(1);
}
console.log("All " + 8 + " smoke checks passed");
process.exit(0);
