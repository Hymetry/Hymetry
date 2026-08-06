const assert = require("node:assert/strict");
const {
  calculateSegmentLabelLayout,
  buildProductAreaSegments,
  calculateVisibleMinutes,
  calculateP85ActiveMinutes,
  countDistinctPageIdentities,
  splitSegmentsForVisibleRange
} = require("../../static/js/tracker/visits-chart-helpers.js");

assert.deepEqual(calculateSegmentLabelLayout({
  labelText: "Customer settings",
  segmentWidth: 38
}), { show: true, width: 24 });
assert.deepEqual(calculateSegmentLabelLayout({
  labelText: "Customer settings",
  segmentWidth: 37
}), { show: false, width: 23 });
assert.deepEqual(calculateSegmentLabelLayout({
  labelText: "AI",
  segmentWidth: 37
}), { show: false, width: 23 });

const segments = buildProductAreaSegments([
  { page: "Task details", productArea: "Work management", seconds: 60, color: "#4269D0" },
  { page: "Meetings", productArea: "Collaboration", seconds: 100, color: "#EFB118" },
  { page: "Tasks", productArea: "Work management", seconds: 120, color: "#4269D0" },
  { page: "Task details", productArea: "Work management", seconds: 15, color: "#4269D0" },
  { page: "Mystery", productArea: "Unclassified", seconds: 20, color: "#CBD5E1", classified: false }
]);

assert.deepEqual(segments, [
  { productArea: "Work management", productAreaKey: "Work management", page: "Tasks", pageKey: "Tasks", seconds: 120, color: "#4269D0", isUnclassified: false },
  { productArea: "Work management", productAreaKey: "Work management", page: "Task details", pageKey: "Task details", seconds: 75, color: "#4269D0", isUnclassified: false },
  { productArea: "Collaboration", productAreaKey: "Collaboration", page: "Meetings", pageKey: "Meetings", seconds: 100, color: "#EFB118", isUnclassified: false },
  { productArea: "Unclassified", productAreaKey: "Unclassified", page: "Mystery", pageKey: "Mystery", seconds: 20, color: "#e2e8f0", isUnclassified: true }
]);

const conflictingAreaColors = buildProductAreaSegments([
  { page: "B", productArea: "Area", seconds: 20, color: "#BBBBBB" },
  { page: "A", productArea: "Area", seconds: 30, color: "#AAAAAA" }
]);
assert.equal(conflictingAreaColors[0].color, "#AAAAAA");
assert.equal(conflictingAreaColors[1].color, "#AAAAAA");

const missingClassifiedColor = buildProductAreaSegments([
  { page: "Known page", productArea: "Known area", seconds: 10 }
]);
assert.equal(missingClassifiedColor[0].color, "#4269d0");
assert.notEqual(missingClassifiedColor[0].color, "#e2e8f0");

const duplicateLabelsWithStableKeys = buildProductAreaSegments([
  {
    page: "Overview",
    pageKey: "rule:1",
    productArea: "Core",
    productAreaKey: "core-a",
    seconds: 20,
    color: "#4269D0"
  },
  {
    page: "Overview",
    pageKey: "rule:2",
    productArea: "Core",
    productAreaKey: "core-b",
    seconds: 10,
    color: "#EFB118"
  }
]);
assert.equal(duplicateLabelsWithStableKeys.length, 2);
assert.deepEqual(duplicateLabelsWithStableKeys.map((segment) => segment.color), ["#4269D0", "#EFB118"]);
assert.deepEqual(
  duplicateLabelsWithStableKeys.map(({ productAreaKey, pageKey }) => ({ productAreaKey, pageKey })),
  [
    { productAreaKey: "core-a", pageKey: "rule:1" },
    { productAreaKey: "core-b", pageKey: "rule:2" }
  ]
);

const repeatedCanonicalPage = buildProductAreaSegments([
  {
    page: "All projects",
    pageKey: "all-projects",
    productArea: "Projects",
    productAreaKey: "projects",
    seconds: 20,
    color: "#4269D0"
  },
  {
    page: "Projects list",
    pageKey: "all-projects",
    productArea: "Projects",
    productAreaKey: "projects",
    seconds: 10,
    color: "#4269D0"
  }
]);
assert.equal(repeatedCanonicalPage.length, 1);
assert.equal(repeatedCanonicalPage[0].seconds, 30);
assert.equal(repeatedCanonicalPage[0].productAreaKey, "projects");
assert.equal(repeatedCanonicalPage[0].pageKey, "all-projects");

const flaggedSegments = buildProductAreaSegments([
  {
    preserveSequence: true,
    page: "Overview",
    pageKey: "overview",
    productArea: "Work management",
    productAreaKey: "work",
    seconds: 10,
    color: "#4269D0"
  },
  {
    preserveSequence: true,
    page: "Login",
    pageKey: "login",
    productArea: "Authentication",
    productAreaKey: "authentication",
    seconds: 40,
    color: "#A463F2"
  },
  {
    preserveSequence: true,
    page: "Boards",
    pageKey: "boards",
    productArea: "Work management",
    productAreaKey: "work",
    seconds: 30,
    color: "#4269D0"
  },
  {
    preserveSequence: true,
    page: "Overview",
    pageKey: "overview",
    productArea: "Work management",
    productAreaKey: "work",
    seconds: 5,
    color: "#4269D0"
  }
]);
assert.deepEqual(
  flaggedSegments.map(({ productArea, page, seconds, color }) => ({ productArea, page, seconds, color })),
  [
    { productArea: "Work management", page: "Boards", seconds: 30, color: "#4269D0" },
    { productArea: "Work management", page: "Overview", seconds: 15, color: "#4269D0" },
    { productArea: "Authentication", page: "Login", seconds: 40, color: "#A463F2" }
  ]
);

assert.equal(countDistinctPageIdentities([
  { productArea: "Projects", productAreaKey: "projects", page: "Overview", pageKey: "overview" },
  { productArea: "Projects", productAreaKey: "projects", page: "Overview alias", pageKey: "overview" },
  { productArea: "Settings", productAreaKey: "settings", page: "Overview", pageKey: "overview" }
]), 2);

assert.equal(calculateVisibleMinutes({ plotWidth: 520, p85ActiveMinutes: 25 }), 25);
assert.equal(calculateVisibleMinutes({ plotWidth: 1080, p85ActiveMinutes: 25 }), 25);
assert.equal(calculateVisibleMinutes({ plotWidth: 1400, p85ActiveMinutes: 25 }), 25);
assert.equal(calculateVisibleMinutes({ plotWidth: 1700, p85ActiveMinutes: 25 }), 30);
assert.equal(calculateVisibleMinutes({ plotWidth: 2160, p85ActiveMinutes: 25 }), 40);

const representativeVisits = Array.from({ length: 19 }, (_, index) => (index < 3 ? 20 : 25) * 60);
representativeVisits.push(90 * 60);
assert.equal(calculateP85ActiveMinutes(representativeVisits), 25);
assert.equal(calculateVisibleMinutes({
  plotWidth: 520,
  p85ActiveMinutes: calculateP85ActiveMinutes(representativeVisits)
}), 25);

const crossing = splitSegmentsForVisibleRange([
  { page: "Tasks", productArea: "Work", seconds: 20 * 60, color: "#4269D0" },
  { page: "Meetings", productArea: "Collaboration", seconds: 10 * 60, color: "#EFB118" },
  { page: "Documents", productArea: "Collaboration", seconds: 10 * 60, color: "#EFB118" }
], 25 * 60);

assert.equal(crossing.visibleSegments.length, 2);
assert.equal(crossing.visibleSegments[1].seconds, 5 * 60);
assert.equal(crossing.visibleSegments[1].partiallyVisible, true);
assert.deepEqual(
  crossing.overflowSegments.map(({ page, seconds, partiallyVisible }) => ({ page, seconds, partiallyVisible })),
  [
    { page: "Meetings", seconds: 5 * 60, partiallyVisible: true },
    { page: "Documents", seconds: 10 * 60, partiallyVisible: false }
  ]
);
assert.equal(
  crossing.visibleActiveSeconds + crossing.hiddenActiveSeconds,
  crossing.totalObservedActiveSeconds
);

const keyedOverflow = splitSegmentsForVisibleRange([
  {
    page: "Overview",
    pageKey: "overview",
    productArea: "Projects",
    productAreaKey: "projects",
    seconds: 10 * 60,
    color: "#4269D0"
  },
  {
    page: "Overview",
    pageKey: "overview",
    productArea: "Settings",
    productAreaKey: "settings",
    seconds: 10 * 60,
    color: "#EFB118"
  }
], 5 * 60);
assert.deepEqual(
  keyedOverflow.overflowSegments.map(({ productAreaKey, pageKey }) => ({ productAreaKey, pageKey })),
  [
    { productAreaKey: "projects", pageKey: "overview" },
    { productAreaKey: "settings", pageKey: "overview" }
  ]
);
assert.equal(countDistinctPageIdentities(keyedOverflow.overflowSegments), 2);

const normalVisit = splitSegmentsForVisibleRange([
  { page: "Home", productArea: "Navigation", seconds: 10 * 60, color: "#3CA951" }
], 25 * 60);
assert.equal(normalVisit.hiddenActiveSeconds, 0);
assert.deepEqual(normalVisit.overflowSegments, []);

console.log("visits chart helper tests passed");
