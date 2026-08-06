const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.resolve(__dirname, "../../static/js/shared/analytics-variant-polling.js"),
  "utf8"
);

function loadSchedule() {
  const context = {
    __HymetryExposeTestHooks: true,
    document: { querySelector: () => null },
    setTimeout: () => 0
  };
  context.window = context;
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(source, context);
  return context.HymetryAnalyticsVariantPollingTesting;
}

function pollTimes(schedule, budgetMs) {
  const times = [];
  let delay = schedule.nextDelay(0);
  let elapsed = 0;
  while (elapsed < budgetMs && times.length < 1000) {
    elapsed += delay;
    times.push(elapsed);
    delay = schedule.nextDelay(delay);
  }
  return times;
}

// Worst-case wasted time for a build finishing at `readyAt` is the remainder of
// whichever gap it lands in.
function wastedIfReadyAt(times, readyAt) {
  const detectedAt = times.find((at) => at >= readyAt);
  return detectedAt === undefined ? Infinity : detectedAt - readyAt;
}

const schedule = loadSchedule();

assert.ok(schedule, "the polling schedule should be exposed under the test hook");

// A build already in flight when the page loaded can finish at any moment, so
// the first look must come well before the shortest plausible build.
assert.ok(
  schedule.FIRST_DELAY_MS <= 500,
  `first poll should be prompt, got ${schedule.FIRST_DELAY_MS}ms`
);

// Growth has to be gentle enough that the wasted fraction stays bounded.
assert.ok(
  schedule.BACKOFF > 1 && schedule.BACKOFF <= 1.35,
  `backoff should grow gently, got ${schedule.BACKOFF}`
);

assert.equal(schedule.nextDelay(0), schedule.FIRST_DELAY_MS);
assert.ok(schedule.nextDelay(1000) > 1000, "delay should grow");
assert.equal(
  schedule.nextDelay(schedule.MAX_DELAY_MS * 10),
  schedule.MAX_DELAY_MS,
  "delay should be capped"
);

const times = pollTimes(schedule, schedule.GIVE_UP_AFTER_MS);

// Monotonic and capped.
for (let i = 1; i < times.length; i += 1) {
  const gap = times[i] - times[i - 1];
  assert.ok(gap > 0, "poll times should advance");
  assert.ok(
    gap <= schedule.MAX_DELAY_MS,
    `gap ${gap}ms exceeded the cap at poll ${i}`
  );
}

// The property that matters: a short build must not spend most of its duration
// waiting to be noticed. These are the cases the previous 2s/1.4 schedule
// handled badly -- it wasted 3.9s on a build that finished at 5s.
const budgets = [
  { readyAt: 1000, maxWasted: 1000 },
  { readyAt: 2000, maxWasted: 1200 },
  { readyAt: 5000, maxWasted: 2000 },
  { readyAt: 10000, maxWasted: 3500 }
];
for (const { readyAt, maxWasted } of budgets) {
  const wasted = wastedIfReadyAt(times, readyAt);
  assert.ok(
    wasted <= maxWasted,
    `a build ready at ${readyAt}ms waited ${wasted}ms, over the ${maxWasted}ms budget`
  );
}

// Polling stays cheap: the endpoint is one indexed metadata lookup, but this
// should not become a stream of requests.
assert.ok(
  times.length <= 60,
  `expected at most 60 polls over the give-up window, got ${times.length}`
);

// And it does give up rather than polling a tab nobody is watching.
assert.ok(
  times[times.length - 1] >= schedule.GIVE_UP_AFTER_MS - schedule.MAX_DELAY_MS,
  "polling should continue until close to the give-up deadline"
);

console.log(
  `analytics-variant-polling: ${times.length} polls over ` +
    `${schedule.GIVE_UP_AFTER_MS / 1000}s; ` +
    `worst wait at 5s elapsed = ${wastedIfReadyAt(times, 5000)}ms`
);
