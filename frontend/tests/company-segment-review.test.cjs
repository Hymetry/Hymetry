const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const segments = require("../../static/js/shared/company-segments.js");
const filters = require("../../static/js/shared/company-attribute-filters.js");
const root = path.resolve(__dirname, "../..");
const source = fs.readFileSync(
  path.join(root, "static/js/shared/company-segments.js"),
  "utf8"
);
const filterSource = fs.readFileSync(
  path.join(root, "static/js/shared/company-attribute-filters.js"),
  "utf8"
);
const dialogStyles = fs.readFileSync(
  path.join(root, "static/css/company-attribute-filters.css"),
  "utf8"
);
const bannerTemplate = fs.readFileSync(
  path.join(root, "templates/partials/company_segment_review_banner.html"),
  "utf8"
);
const warningIconTemplate = fs.readFileSync(
  path.join(root, "templates/partials/company_segment_warning_icon.html"),
  "utf8"
);
const builderTemplate = fs.readFileSync(
  path.join(root, "templates/partials/company_attribute_filter_dialog.html"),
  "utf8"
);

const flagged = {
  id: "7",
  name: "Enterprise Europe",
  definition: { 2: { op: "gte", value: "250000" } },
  needsReview: true,
  deletedAttributes: [
    {
      attributeId: "10",
      attributeName: "Region",
      deletedBy: "Alex",
      deletedOn: "July 24",
      detail: '"Region" was deleted by Alex on July 24.',
    },
  ],
};

test("a segment is marked as needing review, never renamed", () => {
  assert.equal(segments.segmentNeedsReview(flagged), true);
  assert.equal(segments.segmentNeedsReview({ id: "8", name: "Big spenders" }), false);
  assert.equal(flagged.name, "Enterprise Europe");

  // The row label is the stored name; the warning is a separate marker.
  assert.match(source, /label: segment\.name,/);
  assert.match(
    source,
    /'<span class="company-scope__name">'\s*\+ \(options\.needsReview\s*\?\s*'<span class="company-scope__warning"/
  );
  assert.match(source, /company-segment-row__warning/);
  assert.doesNotMatch(source, /"⚠\s*" \+/);
});

test("the warning mark is an svg with one definition per renderer", () => {
  // Two renderers, one glyph each: the template include for the server-rendered
  // banners, ICONS.warning for the rows the script builds. Changing the mark is
  // an edit in each, not a hunt through inlined copies.
  assert.match(warningIconTemplate, /<svg[\s\S]*<path d="m40-120 440-760/);
  assert.match(source, /warning:\s*[\r\n]+\s*'<svg[^']*<path d="m40-120 440-760/);

  const iconPathCount = (haystack) =>
    (haystack.match(/m40-120 440-760/g) || []).length;
  assert.equal(iconPathCount(bannerTemplate), 0, "the banner must include the icon, not inline it");
  assert.equal(iconPathCount(warningIconTemplate), 1);
  assert.equal(iconPathCount(source), 1);
  assert.equal(
    (bannerTemplate.match(/partials\/company_segment_warning_icon\.html/g) || []).length,
    2
  );

  // No literal character stands in for the icon anywhere it is rendered.
  [source, bannerTemplate, warningIconTemplate].forEach((text) => {
    assert.doesNotMatch(text, /⚠/);
  });
});

test("applying a flagged segment explains the refusal instead of navigating", () => {
  const message = segments.reviewBlockMessage(flagged);

  assert.match(message, /“Enterprise Europe” can’t be applied until it’s reviewed/);
  assert.match(message, /company attribute it used was deleted/);

  // The popover click path checks review state before it builds any scope URL.
  assert.match(
    source,
    /if \(segmentNeedsReview\(segment\)\) \{\s*openReviewRequiredDialog\(segment, null\);\s*return;\s*\}\s*navigateTo\(/
  );
  assert.match(source, /layerButton\("Edit segment", "edit-segment", "primary"\)/);
  assert.match(
    source,
    /action === "edit-segment"[\s\S]{0,220}beginSegmentEdit\(reviewSegment\)/
  );
});

test("a flagged segment shows no matching count to stand in for its cohort", () => {
  assert.match(source, /meta: needsReview \? undefined : segment\.matchingCompanyCount,/);
  assert.match(source, /company-segment-row__meta--review">Needs review/);
});

test("the editor accounts for the deleted attributes it cannot show as rows", () => {
  const notice = filters.segmentReviewNotice(flagged);

  assert.equal(notice.title, "A company attribute used by this segment was deleted");
  assert.deepEqual(notice.details, ['"Region" was deleted by Alex on July 24.']);
  assert.match(notice.copy, /conditions were removed from this editor/);
  assert.match(notice.copy, /Review the remaining filters and save/);

  const plural = filters.segmentReviewNotice({
    deletedAttributes: [
      { attributeName: "Region", deletedBy: "Alex", deletedOn: "July 24" },
      { attributeName: "Plan", deletedBy: "Sam", deletedOn: "July 25" },
    ],
  });
  assert.equal(plural.title, "Company attributes used by this segment were deleted");
  assert.deepEqual(plural.details, [
    '"Region" was deleted by Alex on July 24.',
    '"Plan" was deleted by Sam on July 25.',
  ]);

  assert.equal(filters.segmentReviewNotice({ deletedAttributes: [] }), null);
  assert.equal(filters.segmentReviewNotice(null), null);
});

test("deleted attributes never become filter rows", () => {
  // Rows are built from the attributes the project still has, and the draft is
  // normalized against that same list, so a stored condition for a deleted
  // attribute has nothing to render into and nothing to save back.
  assert.match(filterSource, /rows\.innerHTML = attributes\.map\(function \(attribute\) \{/);
  assert.match(
    filterSource,
    /draft = options && options\.definition\s*\?\s*normalizeApplied\(options\.definition, attributes\)/
  );
  assert.match(
    filterSource,
    /if \(attributeId && attributeIds\.has\(attributeId\) && filter\) \{/
  );

  // The notice is part of the edit-segment chrome only.
  assert.match(
    filterSource,
    /renderReviewNotice\(\s*mode === "edit-segment" && session \? segmentReviewNotice\(session\.segment\) : null\s*\)/
  );
  assert.match(builderTemplate, /data-attribute-filter-review/);
  assert.match(dialogStyles, /\.company-segment-builder-review \{/);
});

test("the page banner is server-rendered and carries the required action", () => {
  assert.match(bannerTemplate, /\{% if company_segment_review\.active %\}/);
  assert.match(bannerTemplate, /\{\{ message \}\}/);
  assert.match(bannerTemplate, /data-company-segment-review-action>Review segments</);
  assert.match(bannerTemplate, /data-company-segment-edit-action>Edit segment</);
  assert.match(bannerTemplate, /must be reviewed first/);
  assert.match(dialogStyles, /\.company-segment-review-banner \{/);

  [
    "apps/projects/templates/projects/companies.html",
    "apps/projects/templates/projects/users.html",
    "apps/pages/templates/pages/overview.html",
    "apps/tracker/templates/tracker/visits.html",
  ].forEach((relativePath) => {
    const template = fs.readFileSync(path.join(root, relativePath), "utf8");
    assert.ok(
      template.includes("partials/company_segment_review_banner.html"),
      `${relativePath}: the review banner must render on this surface`
    );
  });

  // Review segments opens the list where the affected segments are marked.
  assert.match(
    source,
    /data-company-segment-review-action[\s\S]{0,220}openManageDialog\(\)/
  );
  assert.match(
    source,
    /data-company-segment-edit-action[\s\S]{0,320}beginSegmentEdit\(segment\)/
  );
});

test("the banner survives until a refreshed list proves the work is done", () => {
  // Only adopting a server response can retire it, so nothing local — opening a
  // dialog, cancelling an edit — makes the warning disappear.
  assert.match(source, /segmentListState = "ready";[\s\S]{0,80}syncReviewBanners\(\);/);
  assert.match(
    source,
    /var outstanding = segments\.filter\(segmentNeedsReview\);\s*if \(reviewBanner && !outstanding\.length\)/
  );
  assert.doesNotMatch(source, /function closeLayer[\s\S]{0,400}reviewBanner\.remove/);
});
