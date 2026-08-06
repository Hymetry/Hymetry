const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "../..");

const storageKeysByFile = {
  "static/js/users/users-analytics.js": "hymetry:recent-users",
  "static/js/users/user-detail.js": "hymetry:recent-users",
  "static/js/companies/companies-analytics.js": "hymetry:recent-companies",
  "static/js/companies/company-detail.js": "hymetry:recent-companies",
  "static/js/pages/pages-analytics.js": "hymetry:recent-pages"
};

for (const [relativePath, storageKey] of Object.entries(storageKeysByFile)) {
  test(`${relativePath} scopes recent entries to the current project`, () => {
    const source = fs.readFileSync(path.join(root, relativePath), "utf8");

    assert.match(
      source,
      new RegExp(`${storageKey.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")}:\\$\\{document\\.body\\?\\.dataset\\.projectId`)
    );
  });
}

test("page selector deduplicates aliases within an area without hiding cross-area names", () => {
  const source = fs.readFileSync(path.join(root, "static/js/pages/pages-analytics.js"), "utf8");

  assert.match(source, /function pageSearchIdentity\(row\)/);
  assert.match(source, /row\?\.page_display_key \|\| row\?\.pageDisplayKey/);
  assert.match(source, /function slugifyPageSearchArea\(value\)/);
  assert.match(source, /row\?\.product_area_id[\s\S]*row\?\.productAreaId[\s\S]*slugifyPageSearchArea\(pageSearchArea\(row\)\)/);
  assert.match(source, /\$\{normalizePageSearchValue\(pageSearchAreaKey\(row\)\) \|\| "unassigned"\}::\$\{normalizedName\}/);
  assert.match(source, /const key = pageSearchIdentity\(row\)/);
  assert.match(source, /function dedupePageSearchRows\(rows\)/);
  assert.match(source, /dedupePageSearchRows\(\[\.\.\.recentPages, \.\.\.fallbackPages\]\)/);
  assert.match(source, /dedupePageSearchRows\(sortPageSearchRows\(rows, options\.preferredArea\)/);
});

test("page overview charts disambiguate colliding page names by Product Area", () => {
  const source = fs.readFileSync(path.join(root, "static/js/pages/pages-analytics.js"), "utf8");

  assert.match(source, /function pageChartLabels\(rows\)/);
  assert.match(source, /function disambiguatePageLabels\(items, nameForItem, areaNameForItem, areaKeyForItem\)/);
  assert.match(source, /const topLabels = pageChartLabels\(topRows\)/);
  assert.match(source, /const seriesLabels = pageChartLabels\(seriesRows\)/);
  assert.match(source, /const groupLabels = disambiguatePageLabels\(/);
  assert.match(source, /escapeHtml\(groupLabels\[groupIndex\]\)/);
  assert.match(source, /ensureNode\(link\.source, link\.sourceLabel/);
  assert.match(source, /ensureNode\(link\.target, link\.targetLabel/);
  assert.match(source, /const labels = disambiguatePageLabels\(/);
});

test("company selectors deduplicate matching company names or domains", () => {
  const overviewSource = fs.readFileSync(path.join(root, "static/js/companies/companies-analytics.js"), "utf8");
  const detailSource = fs.readFileSync(path.join(root, "static/js/companies/company-detail.js"), "utf8");

  assert.match(overviewSource, /function dedupeCompanySearchResults\(companies\)/);
  assert.match(overviewSource, /dedupeCompanySearchResults\(\[\.\.\.recentCompanies, \.\.\.fallbackCompanies\]\)/);
  assert.match(detailSource, /function dedupeCompanySelectorResults\(companies\)/);
  assert.match(detailSource, /dedupeCompanySelectorResults\(\[\.\.\.recentCompanies, \.\.\.fallbackCompanies\]\)/);
});

test("company detail replaces the path placeholder and loads an empty-query fallback", () => {
  const providerSource = fs.readFileSync(path.join(root, "static/js/companies/django-company-detail-data.js"), "utf8");
  const detailSource = fs.readFileSync(path.join(root, "static/js/companies/company-detail.js"), "utf8");

  assert.match(providerSource, /pathname\.replace\(\/detail\(\?=\\\/\|\$\)\/, encodeURIComponent\(companyId\)\)/);
  assert.match(detailSource, /const shouldLoadFallback = !normalizedQuery && !visibleRecentCompanies\.length/);
  assert.match(detailSource, /alphabetical: shouldLoadFallback/);
  assert.match(detailSource, /fallbackAlternatives\.length[\s\S]*dedupeCompanySelectorResults\(remoteResults\)/);
});

test("empty selectors fall back to the current item when it is the only option", () => {
  const usersSource = fs.readFileSync(path.join(root, "static/js/users/user-detail.js"), "utf8");
  const companiesSource = fs.readFileSync(path.join(root, "static/js/companies/company-detail.js"), "utf8");
  const pagesSource = fs.readFileSync(path.join(root, "static/js/pages/pages-analytics.js"), "utf8");

  assert.match(usersSource, /fallbackAlternatives\.length \? fallbackAlternatives : userSearchResults/);
  assert.match(companiesSource, /fallbackAlternatives\.length[\s\S]*dedupeCompanySelectorResults\(remoteResults\)/);
  assert.match(pagesSource, /if \(preferredResults\.length\)[\s\S]*dedupePageSearchRows\(rows\.slice\(\)/);
});

test("recent storage keeps identity fields instead of analytics payloads", () => {
  const userFiles = [
    "static/js/users/users-analytics.js",
    "static/js/users/user-detail.js"
  ];
  const companyFiles = [
    "static/js/companies/companies-analytics.js",
    "static/js/companies/company-detail.js"
  ];

  for (const relativePath of userFiles) {
    const source = fs.readFileSync(path.join(root, relativePath), "utf8");
    const writer = source.match(/function writeRecentUsers\(users\) \{[\s\S]*?\n  \}/)?.[0] || "";
    assert.match(writer, /companyId: user\.companyId/);
    assert.doesNotMatch(writer, /engagedSeconds|visitsCount|lastActiveSort/);
  }

  for (const relativePath of companyFiles) {
    const source = fs.readFileSync(path.join(root, relativePath), "utf8");
    const writer = source.match(/function writeRecentCompanies\(companies\) \{[\s\S]*?\n  \}/)?.[0] || "";
    assert.match(writer, /domain: company\.domain/);
    assert.doesNotMatch(writer, /activeUsers|engagedSeconds|interactionPct|lastSeenDays/);
  }
});
