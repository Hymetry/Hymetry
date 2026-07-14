from django.db import connection


FIXED_PALETTE = (
    '#4269D0',
    '#6CC5B0',
    '#EFB118',
    '#A463F2',
    '#3CA951',
    '#97BBF5',
    '#FF725C',
    '#FF8AB7',
    '#9C6B4E',
    '#64748B',
)


def fetch_all(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_one(sql, params=None):
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.rowcount


PROJECT_INFO_SQL = """
SELECT p.id, p.name, p.timezone
FROM projects_project p
JOIN projects_workspace w ON w.id = p.workspace_id
WHERE p.id = %s
  AND p.lifecycle_status = 'active'
  AND w.archived_at IS NULL
"""


RECENT_ANALYTICS_PROJECTS_SQL = """
SELECT DISTINCT s.project_id
FROM tracker_analyticsevent e
JOIN tracker_analyticssession s ON s.session_id = e.session_id
JOIN projects_project p ON p.id = s.project_id
JOIN projects_workspace w ON w.id = p.workspace_id
WHERE e.timestamp >= %s
  AND p.lifecycle_status = 'active'
  AND w.archived_at IS NULL
ORDER BY s.project_id
"""


SOURCE_MAX_EVENT_TS_SQL = """
SELECT MAX(e.timestamp) AS source_max_event_ts
FROM tracker_analyticsevent e
JOIN tracker_analyticssession s ON s.session_id = e.session_id
WHERE s.project_id = %s
"""


ENSURE_PRODUCT_AREAS_SQL = """
WITH raw_candidates AS (
    SELECT
        project_id,
        trim(product_area) AS name,
        trim(product_area_short_name) AS short_name,
        COALESCE(NULLIF(area_role, ''), 'unknown') AS area_role,
        COALESCE(is_adoption_recommendable, false) AS is_adoption_recommendable
    FROM tracker_projectpagerule
    WHERE project_id = %s
      AND is_active = true
      AND trim(product_area) <> ''

    UNION ALL

    SELECT
        s.project_id,
        trim(COALESCE(NULLIF(e.product_area, ''), NULLIF(e.page_name, ''), 'Unassigned')) AS name,
        '' AS short_name,
        'unknown' AS area_role,
        false AS is_adoption_recommendable
    FROM tracker_analyticsevent e
    JOIN tracker_analyticssession s ON s.session_id = e.session_id
    WHERE s.project_id = %s
      AND e.timestamp >= %s
      AND e.timestamp < %s
      AND trim(COALESCE(NULLIF(e.url_normalized, ''), NULLIF(e.url, ''))) <> ''
),
normalized AS (
    SELECT
        project_id,
        name,
        short_name,
        area_role,
        is_adoption_recommendable,
        COALESCE(NULLIF(lower(trim(both '-' from regexp_replace(name, '[^[:alnum:]]+', '-', 'g'))), ''), 'unassigned') AS slug
    FROM (
        SELECT *
        FROM raw_candidates
        WHERE name <> ''
    ) candidates
),
candidates AS (
    SELECT
        project_id,
        slug,
        MIN(name) AS name,
        COALESCE(MAX(NULLIF(short_name, '')), '') AS short_name,
        CASE
            WHEN BOOL_OR(area_role = 'product') THEN 'product'
            WHEN BOOL_OR(area_role = 'setup') THEN 'setup'
            WHEN BOOL_OR(area_role = 'admin') THEN 'admin'
            WHEN BOOL_OR(area_role = 'support') THEN 'support'
            WHEN BOOL_OR(area_role = 'system') THEN 'system'
            ELSE 'unknown'
        END AS area_role,
        BOOL_OR(is_adoption_recommendable) AS is_adoption_recommendable
    FROM normalized
    GROUP BY project_id, slug
)
INSERT INTO pages_productarea (
    project_id,
    name,
    slug,
    short_name,
    color,
    category,
    category_color,
    description,
    area_role,
    is_adoption_recommendable,
    source,
    created_at,
    updated_at
)
SELECT
    project_id,
    name,
    slug,
    short_name,
    (ARRAY['#4269D0', '#6CC5B0', '#EFB118', '#A463F2', '#3CA951', '#97BBF5', '#FF725C', '#FF8AB7', '#9C6B4E', '#64748B'])[1 + abs(hashtext(slug)::bigint) %% 10],
    '',
    '',
    '',
    area_role,
    is_adoption_recommendable,
    'system',
    NOW(),
    NOW()
FROM candidates
ON CONFLICT (project_id, slug)
DO UPDATE SET
    name = EXCLUDED.name,
    short_name = COALESCE(NULLIF(EXCLUDED.short_name, ''), pages_productarea.short_name),
    area_role = CASE
        WHEN EXCLUDED.area_role <> 'unknown' THEN EXCLUDED.area_role
        ELSE pages_productarea.area_role
    END,
    is_adoption_recommendable = pages_productarea.is_adoption_recommendable OR EXCLUDED.is_adoption_recommendable,
    updated_at = NOW()
"""


DELETE_TRANSITIONS_FOR_WINDOW_SQL = """
DELETE FROM pages_pagetransition
WHERE project_id = %s
  AND (
    (transition_ts >= %s AND transition_ts < %s)
    OR from_visit_id IN (
      SELECT id
      FROM pages_pagevisit
      WHERE project_id = %s
        AND visit_start_ts >= %s
        AND visit_start_ts < %s
    )
    OR to_visit_id IN (
      SELECT id
      FROM pages_pagevisit
      WHERE project_id = %s
        AND visit_start_ts >= %s
        AND visit_start_ts < %s
    )
  )
"""


DELETE_VISITS_FOR_WINDOW_SQL = """
DELETE FROM pages_pagevisit
WHERE project_id = %s
  AND visit_start_ts >= %s
  AND visit_start_ts < %s
"""


INSERT_PAGE_VISITS_SQL = """
WITH base AS (
    SELECT
        s.project_id,
        e.id AS event_id,
        e.session_id,
        e.timestamp,
        e.event_type,
        COALESCE(e.visitor_guid, s.visitor_guid) AS visitor_guid,
        NULLIF(COALESCE(NULLIF(e.user_id, ''), NULLIF(s.user_id, '')), '') AS user_id,
        COALESCE(NULLIF(e.user_traits ->> 'name', ''), '') AS user_name,
        NULLIF(COALESCE(NULLIF(e.company_id, ''), NULLIF(s.company_id, '')), '') AS company_id,
        COALESCE(NULLIF(e.company_traits ->> 'name', ''), '') AS company_name,
        COALESCE(NULLIF(e.url_normalized, ''), NULLIF(e.url, '')) AS url_key,
        COALESCE(NULLIF(e.page_name_original, ''), NULLIF(e.page_name, ''), '') AS page_name_original,
        e.page_rule_id,
        COALESCE(NULLIF(pr.product_area, ''), NULLIF(e.product_area, ''), NULLIF(e.page_name, ''), 'Unassigned') AS product_area_name,
        lower(trim(both '-' from regexp_replace(
            COALESCE(NULLIF(pr.product_area, ''), NULLIF(e.product_area, ''), NULLIF(e.page_name, ''), 'Unassigned'),
            '[^[:alnum:]]+',
            '-',
            'g'
        ))) AS product_area_slug
    FROM tracker_analyticsevent e
    JOIN tracker_analyticssession s ON s.session_id = e.session_id
    LEFT JOIN tracker_projectpagerule pr ON pr.id = e.page_rule_id
    WHERE s.project_id = %s
      AND e.timestamp >= %s
      AND e.timestamp < %s
      AND COALESCE(NULLIF(e.url_normalized, ''), NULLIF(e.url, '')) IS NOT NULL
      AND COALESCE(NULLIF(e.url_normalized, ''), NULLIF(e.url, '')) <> ''
),
ordered AS (
    SELECT
        base.*,
        LAG(url_key) OVER (PARTITION BY session_id ORDER BY timestamp, event_id) AS prev_url_key,
        LAG(page_rule_id) OVER (PARTITION BY session_id ORDER BY timestamp, event_id) AS prev_page_rule_id,
        LAG(timestamp) OVER (PARTITION BY session_id ORDER BY timestamp, event_id) AS prev_timestamp
    FROM base
),
marked AS (
    SELECT
        ordered.*,
        CASE
            WHEN prev_timestamp IS NULL THEN 1
            WHEN url_key IS DISTINCT FROM prev_url_key THEN 1
            WHEN page_rule_id IS DISTINCT FROM prev_page_rule_id THEN 1
            WHEN timestamp - prev_timestamp > (%s::int * INTERVAL '1 second') THEN 1
            ELSE 0
        END AS starts_new_visit
    FROM ordered
),
segmented AS (
    SELECT
        marked.*,
        SUM(starts_new_visit) OVER (
            PARTITION BY session_id
            ORDER BY timestamp, event_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS visit_ordinal
    FROM marked
),
with_next AS (
    SELECT
        segmented.*,
        LEAD(timestamp) OVER (PARTITION BY session_id, visit_ordinal ORDER BY timestamp, event_id) AS next_timestamp
    FROM segmented
),
rolled AS (
    SELECT
        project_id,
        session_id,
        visit_ordinal,
        (ARRAY_AGG(visitor_guid) FILTER (WHERE visitor_guid IS NOT NULL))[1] AS visitor_guid,
        MIN(user_id) FILTER (WHERE user_id IS NOT NULL AND user_id <> '') AS user_id,
        MIN(user_name) FILTER (WHERE user_name <> '') AS user_name_sample,
        MIN(company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> '') AS company_id,
        MIN(company_name) FILTER (WHERE company_name <> '') AS company_name_sample,
        MIN(url_key) AS url_normalized,
        MIN(page_name_original) FILTER (WHERE page_name_original <> '') AS page_name_original,
        page_rule_id,
        COALESCE(NULLIF(MIN(product_area_slug), ''), 'unassigned') AS product_area_key,
        MIN(product_area_name) AS product_area_name,
        MIN(timestamp) AS visit_start_ts,
        MAX(timestamp) AS visit_end_ts,
        COALESCE(SUM(
            CASE
                WHEN next_timestamp IS NULL THEN 0
                ELSE LEAST(EXTRACT(EPOCH FROM (next_timestamp - timestamp)), 30)
            END
        ), 0)::bigint AS engaged_seconds,
        COUNT(*) FILTER (WHERE event_type = 'click') AS click_count,
        COUNT(*) FILTER (WHERE event_type = 'scroll') AS scroll_count,
        COUNT(*) FILTER (WHERE event_type = 'mouse_move') AS mouse_move_count,
        MIN(event_id) AS first_event_id,
        MAX(event_id) AS last_event_id
    FROM with_next
    GROUP BY project_id, session_id, visit_ordinal, page_rule_id
)
INSERT INTO pages_pagevisit (
    project_id,
    session_id,
    visitor_guid,
    user_id,
    user_name_sample,
    company_id,
    company_name_sample,
    url_normalized,
    page_name_original,
    page_rule_id,
    product_area_id,
    product_area_key,
    product_area_name,
    visit_start_ts,
    visit_end_ts,
    engaged_seconds,
    click_count,
    scroll_count,
    mouse_move_count,
    had_click,
    had_scroll,
    had_mouse_move,
    first_event_id,
    last_event_id,
    created_at,
    updated_at
)
SELECT
    rolled.project_id,
    rolled.session_id,
    rolled.visitor_guid,
    rolled.user_id,
    COALESCE(rolled.user_name_sample, ''),
    rolled.company_id,
    COALESCE(rolled.company_name_sample, ''),
    rolled.url_normalized,
    COALESCE(rolled.page_name_original, ''),
    rolled.page_rule_id,
    pa.id,
    rolled.product_area_key,
    rolled.product_area_name,
    rolled.visit_start_ts,
    rolled.visit_end_ts,
    rolled.engaged_seconds,
    rolled.click_count,
    rolled.scroll_count,
    rolled.mouse_move_count,
    rolled.click_count > 0,
    rolled.scroll_count > 0,
    rolled.mouse_move_count > 0,
    rolled.first_event_id,
    rolled.last_event_id,
    NOW(),
    NOW()
FROM rolled
LEFT JOIN pages_productarea pa
    ON pa.project_id = rolled.project_id
   AND pa.slug = rolled.product_area_key
WHERE rolled.visit_start_ts >= %s
  AND rolled.visit_start_ts < %s
"""


INSERT_PAGE_TRANSITIONS_SQL = """
WITH ordered AS (
    SELECT
        pv.*,
        LEAD(id) OVER (PARTITION BY project_id, session_id ORDER BY visit_start_ts, id) AS to_visit_id,
        LEAD(visit_start_ts) OVER (PARTITION BY project_id, session_id ORDER BY visit_start_ts, id) AS to_visit_start_ts,
        LEAD(page_rule_id) OVER (PARTITION BY project_id, session_id ORDER BY visit_start_ts, id) AS to_page_rule_id,
        LEAD(product_area_id) OVER (PARTITION BY project_id, session_id ORDER BY visit_start_ts, id) AS to_product_area_id,
        LEAD(product_area_key) OVER (PARTITION BY project_id, session_id ORDER BY visit_start_ts, id) AS to_product_area_key,
        LEAD(product_area_name) OVER (PARTITION BY project_id, session_id ORDER BY visit_start_ts, id) AS to_product_area_name,
        LEAD(url_normalized) OVER (PARTITION BY project_id, session_id ORDER BY visit_start_ts, id) AS to_url_normalized
    FROM pages_pagevisit pv
    WHERE pv.project_id = %s
      AND pv.visit_start_ts >= %s
      AND pv.visit_start_ts < %s
)
INSERT INTO pages_pagetransition (
    project_id,
    session_id,
    company_id,
    user_id,
    from_visit_id,
    to_visit_id,
    from_page_rule_id,
    to_page_rule_id,
    from_product_area_id,
    to_product_area_id,
    from_product_area_key,
    to_product_area_key,
    from_product_area_name,
    to_product_area_name,
    from_url_normalized,
    to_url_normalized,
    transition_ts
)
SELECT
    project_id,
    session_id,
    company_id,
    user_id,
    id,
    to_visit_id,
    page_rule_id,
    to_page_rule_id,
    product_area_id,
    to_product_area_id,
    product_area_key,
    to_product_area_key,
    product_area_name,
    to_product_area_name,
    url_normalized,
    to_url_normalized,
    to_visit_start_ts
FROM ordered
WHERE to_visit_id IS NOT NULL
  AND to_visit_start_ts - visit_end_ts <= (%s::int * INTERVAL '1 second')
  AND (
      page_rule_id IS DISTINCT FROM to_page_rule_id
      OR url_normalized IS DISTINCT FROM to_url_normalized
      OR product_area_key IS DISTINCT FROM to_product_area_key
  )
"""


DELETE_DAILY_METRICS_SQL = (
    "DELETE FROM pages_pagedailymetric WHERE project_id = %s AND date >= %s AND date <= %s",
    "DELETE FROM pages_pagecompanydailymetric WHERE project_id = %s AND date >= %s AND date <= %s",
    "DELETE FROM pages_pageuserdailymetric WHERE project_id = %s AND date >= %s AND date <= %s",
    "DELETE FROM pages_rawpagedailymetric WHERE project_id = %s AND date >= %s AND date <= %s",
    "DELETE FROM pages_rawpageactiondailymetric WHERE project_id = %s AND date >= %s AND date <= %s",
    "DELETE FROM pages_projectdailymetric WHERE project_id = %s AND date >= %s AND date <= %s",
)


INSERT_PAGE_DAILY_METRICS_SQL = """
WITH visits AS (
    SELECT
        (visit_start_ts AT TIME ZONE %s)::date AS metric_date,
        *
    FROM pages_pagevisit
    WHERE project_id = %s
      AND (visit_start_ts AT TIME ZONE %s)::date >= %s
      AND (visit_start_ts AT TIME ZONE %s)::date <= %s
)
INSERT INTO pages_pagedailymetric (
    project_id, date, page_rule_id, product_area_id, product_area_key, product_area_name,
    visits_count, engaged_seconds, click_count, scroll_count, mouse_move_count,
    visits_with_click_count, companies_count_daily, users_count_daily
)
SELECT
    project_id,
    metric_date,
    page_rule_id,
    MIN(product_area_id),
    product_area_key,
    COALESCE(MIN(product_area_name) FILTER (WHERE product_area_name <> ''), ''),
    COUNT(*),
    COALESCE(SUM(engaged_seconds), 0),
    COALESCE(SUM(click_count), 0),
    COALESCE(SUM(scroll_count), 0),
    COALESCE(SUM(mouse_move_count), 0),
    COUNT(*) FILTER (WHERE had_click),
    COUNT(DISTINCT company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> ''),
    COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL AND user_id <> '')
FROM visits
GROUP BY project_id, metric_date, page_rule_id, product_area_key
"""


INSERT_PAGE_COMPANY_DAILY_METRICS_SQL = """
WITH visits AS (
    SELECT
        (visit_start_ts AT TIME ZONE %s)::date AS metric_date,
        *
    FROM pages_pagevisit
    WHERE project_id = %s
      AND (visit_start_ts AT TIME ZONE %s)::date >= %s
      AND (visit_start_ts AT TIME ZONE %s)::date <= %s
      AND company_id IS NOT NULL
      AND company_id <> ''
)
INSERT INTO pages_pagecompanydailymetric (
    project_id, date, page_rule_id, product_area_id, product_area_key, product_area_name,
    company_id, company_name_sample, visits_count, engaged_seconds, click_count,
    visits_with_click_count, active_users_count_daily
)
SELECT
    project_id,
    metric_date,
    page_rule_id,
    MIN(product_area_id),
    product_area_key,
    COALESCE(MIN(product_area_name) FILTER (WHERE product_area_name <> ''), ''),
    company_id,
    COALESCE(MIN(company_name_sample) FILTER (WHERE company_name_sample <> ''), ''),
    COUNT(*),
    COALESCE(SUM(engaged_seconds), 0),
    COALESCE(SUM(click_count), 0),
    COUNT(*) FILTER (WHERE had_click),
    COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL AND user_id <> '')
FROM visits
GROUP BY project_id, metric_date, page_rule_id, product_area_key, company_id
"""


INSERT_PAGE_USER_DAILY_METRICS_SQL = """
WITH visits AS (
    SELECT
        (visit_start_ts AT TIME ZONE %s)::date AS metric_date,
        *
    FROM pages_pagevisit
    WHERE project_id = %s
      AND (visit_start_ts AT TIME ZONE %s)::date >= %s
      AND (visit_start_ts AT TIME ZONE %s)::date <= %s
      AND user_id IS NOT NULL
      AND user_id <> ''
)
INSERT INTO pages_pageuserdailymetric (
    project_id, date, page_rule_id, product_area_id, product_area_key, product_area_name,
    company_id, user_id, user_name_sample, visits_count, engaged_seconds, click_count
)
SELECT
    project_id,
    metric_date,
    page_rule_id,
    MIN(product_area_id),
    product_area_key,
    COALESCE(MIN(product_area_name) FILTER (WHERE product_area_name <> ''), ''),
    MIN(company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> ''),
    user_id,
    COALESCE(MIN(user_name_sample) FILTER (WHERE user_name_sample <> ''), ''),
    COUNT(*),
    COALESCE(SUM(engaged_seconds), 0),
    COALESCE(SUM(click_count), 0)
FROM visits
GROUP BY project_id, metric_date, page_rule_id, product_area_key, user_id
"""


INSERT_RAW_PAGE_DAILY_METRICS_SQL = """
WITH visits AS (
    SELECT
        (visit_start_ts AT TIME ZONE %s)::date AS metric_date,
        *
    FROM pages_pagevisit
    WHERE project_id = %s
      AND (visit_start_ts AT TIME ZONE %s)::date >= %s
      AND (visit_start_ts AT TIME ZONE %s)::date <= %s
)
INSERT INTO pages_rawpagedailymetric (
    project_id, date, url_normalized, page_rule_id, product_area_id, product_area_key,
    product_area_name, page_label, page_title_sample, visits_count, engaged_seconds,
    click_count, visits_with_click_count, companies_count_daily, users_count_daily
)
SELECT
    project_id,
    metric_date,
    url_normalized,
    MIN(page_rule_id),
    MIN(product_area_id),
    MIN(product_area_key),
    MIN(product_area_name),
    COALESCE(NULLIF(MIN(page_name_original) FILTER (WHERE page_name_original <> ''), ''), url_normalized),
    COALESCE(NULLIF(MIN(page_name_original) FILTER (WHERE page_name_original <> ''), ''), ''),
    COUNT(*),
    COALESCE(SUM(engaged_seconds), 0),
    COALESCE(SUM(click_count), 0),
    COUNT(*) FILTER (WHERE had_click),
    COUNT(DISTINCT company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> ''),
    COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL AND user_id <> '')
FROM visits
GROUP BY project_id, metric_date, url_normalized
"""


INSERT_RAW_PAGE_ACTION_DAILY_METRICS_SQL = """
WITH events AS (
    SELECT
        s.project_id,
        (e.timestamp AT TIME ZONE %s)::date AS metric_date,
        COALESCE(NULLIF(e.url_normalized, ''), NULLIF(e.url, '')) AS url_normalized,
        e.page_rule_id,
        COALESCE(NULLIF(pr.product_area, ''), NULLIF(e.product_area, ''), NULLIF(e.page_name, ''), 'Unassigned') AS product_area_name,
        lower(trim(both '-' from regexp_replace(
            COALESCE(NULLIF(pr.product_area, ''), NULLIF(e.product_area, ''), NULLIF(e.page_name, ''), 'Unassigned'),
            '[^[:alnum:]]+',
            '-',
            'g'
        ))) AS product_area_key,
        e.element_key,
        NULLIF(COALESCE(NULLIF(e.user_id, ''), NULLIF(s.user_id, '')), '') AS user_id,
        NULLIF(COALESCE(NULLIF(e.company_id, ''), NULLIF(s.company_id, '')), '') AS company_id,
        pv.id AS visit_id
    FROM tracker_analyticsevent e
    JOIN tracker_analyticssession s ON s.session_id = e.session_id
    LEFT JOIN tracker_projectpagerule pr ON pr.id = e.page_rule_id
    LEFT JOIN pages_pagevisit pv
      ON pv.project_id = s.project_id
     AND pv.session_id = e.session_id
     AND pv.url_normalized = COALESCE(NULLIF(e.url_normalized, ''), NULLIF(e.url, ''))
     AND pv.visit_start_ts <= e.timestamp
     AND pv.visit_end_ts >= e.timestamp
    WHERE s.project_id = %s
      AND e.event_type = 'click'
      AND e.element_key IS NOT NULL
      AND e.element_key <> ''
      AND (e.timestamp AT TIME ZONE %s)::date >= %s
      AND (e.timestamp AT TIME ZONE %s)::date <= %s
      AND COALESCE(NULLIF(e.url_normalized, ''), NULLIF(e.url, '')) IS NOT NULL
      AND COALESCE(NULLIF(e.url_normalized, ''), NULLIF(e.url, '')) <> ''
)
INSERT INTO pages_rawpageactiondailymetric (
    project_id, date, url_normalized, page_rule_id, product_area_id, product_area_key,
    product_area_name, element_key, clicks_count, users_count_daily,
    companies_count_daily, visits_with_action_count
)
SELECT
    events.project_id,
    events.metric_date,
    events.url_normalized,
    MIN(events.page_rule_id),
    MIN(pa.id),
    MIN(events.product_area_key),
    MIN(events.product_area_name),
    events.element_key,
    COUNT(*),
    COUNT(DISTINCT events.user_id) FILTER (WHERE events.user_id IS NOT NULL AND events.user_id <> ''),
    COUNT(DISTINCT events.company_id) FILTER (WHERE events.company_id IS NOT NULL AND events.company_id <> ''),
    COUNT(DISTINCT events.visit_id) FILTER (WHERE events.visit_id IS NOT NULL)
FROM events
LEFT JOIN pages_productarea pa
  ON pa.project_id = events.project_id
 AND pa.slug = events.product_area_key
GROUP BY events.project_id, events.metric_date, events.url_normalized, events.element_key
"""


INSERT_PROJECT_DAILY_METRICS_SQL = """
WITH visits AS (
    SELECT
        (visit_start_ts AT TIME ZONE %s)::date AS metric_date,
        *
    FROM pages_pagevisit
    WHERE project_id = %s
      AND (visit_start_ts AT TIME ZONE %s)::date >= %s
      AND (visit_start_ts AT TIME ZONE %s)::date <= %s
)
INSERT INTO pages_projectdailymetric (
    project_id, date, active_companies_count, active_users_count, visits_count, engaged_seconds, click_count
)
SELECT
    project_id,
    metric_date,
    COUNT(DISTINCT company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> ''),
    COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL AND user_id <> ''),
    COUNT(*),
    COALESCE(SUM(engaged_seconds), 0),
    COALESCE(SUM(click_count), 0)
FROM visits
GROUP BY project_id, metric_date
"""


AREA_SUMMARY_SQL = """
WITH daily AS (
    SELECT
        product_area_key,
        MIN(product_area_name) AS product_area_name,
        MIN(product_area_id) AS product_area_id,
        COUNT(DISTINCT COALESCE(page_rule_id::text, product_area_key)) AS page_count,
        SUM(visits_count) AS visits_count,
        SUM(engaged_seconds) AS engaged_seconds,
        SUM(click_count) AS click_count,
        SUM(visits_with_click_count) AS visits_with_click_count
    FROM pages_pagedailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY product_area_key
),
companies AS (
    SELECT product_area_key, COUNT(DISTINCT company_id) AS companies_count
    FROM pages_pagecompanydailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY product_area_key
),
users AS (
    SELECT product_area_key, COUNT(DISTINCT user_id) AS users_count
    FROM pages_pageuserdailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY product_area_key
),
company_engaged AS (
    SELECT DISTINCT ON (product_area_key)
        product_area_key,
        company_id AS top_company_id,
        COALESCE(company_name_sample, company_id) AS top_company_name,
        SUM(engaged_seconds) AS company_engaged_seconds,
        SUM(visits_count) AS company_visits_count
    FROM pages_pagecompanydailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY product_area_key, company_id, company_name_sample
    ORDER BY product_area_key, SUM(engaged_seconds) DESC, SUM(visits_count) DESC, COALESCE(company_name_sample, company_id)
)
SELECT
    daily.product_area_key,
    daily.product_area_name,
    daily.product_area_id,
    daily.page_count,
    COALESCE(companies.companies_count, 0) AS companies_count,
    COALESCE(users.users_count, 0) AS users_count,
    daily.visits_count,
    daily.engaged_seconds,
    daily.click_count,
    daily.visits_with_click_count,
    company_engaged.top_company_id,
    company_engaged.top_company_name
FROM daily
LEFT JOIN companies ON companies.product_area_key = daily.product_area_key
LEFT JOIN users ON users.product_area_key = daily.product_area_key
LEFT JOIN company_engaged ON company_engaged.product_area_key = daily.product_area_key
ORDER BY daily.visits_count DESC, daily.product_area_name
"""


PAGE_SUMMARY_SQL = """
WITH daily AS (
    SELECT
        COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned') AS product_area_key,
        COALESCE(NULLIF(MIN(pdm.product_area_name), ''), 'Unassigned') AS product_area_name,
        MIN(pdm.product_area_id) AS product_area_id,
        pdm.page_rule_id,
        COALESCE(NULLIF(MIN(pr.page_name), ''), NULLIF(MIN(pdm.product_area_name), ''), 'Unassigned') AS page_name,
        SUM(pdm.visits_count) AS visits_count,
        SUM(pdm.engaged_seconds) AS engaged_seconds,
        SUM(pdm.click_count) AS click_count,
        SUM(pdm.visits_with_click_count) AS visits_with_click_count
    FROM pages_pagedailymetric pdm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pdm.page_rule_id
    WHERE pdm.project_id = %s
      AND pdm.date >= %s
      AND pdm.date <= %s
    GROUP BY COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned'), pdm.page_rule_id
),
companies AS (
    SELECT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        page_rule_id,
        COUNT(DISTINCT company_id) AS companies_count
    FROM pages_pagecompanydailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY COALESCE(NULLIF(product_area_key, ''), 'unassigned'), page_rule_id
),
users AS (
    SELECT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        page_rule_id,
        COUNT(DISTINCT user_id) AS users_count
    FROM pages_pageuserdailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY COALESCE(NULLIF(product_area_key, ''), 'unassigned'), page_rule_id
),
company_engaged AS (
    SELECT DISTINCT ON (product_area_key, page_rule_id)
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        page_rule_id,
        company_id AS top_company_id,
        COALESCE(company_name_sample, company_id) AS top_company_name,
        SUM(engaged_seconds) AS company_engaged_seconds,
        SUM(visits_count) AS company_visits_count
    FROM pages_pagecompanydailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY COALESCE(NULLIF(product_area_key, ''), 'unassigned'), page_rule_id, company_id, company_name_sample
    ORDER BY product_area_key, page_rule_id, SUM(engaged_seconds) DESC, SUM(visits_count) DESC, COALESCE(company_name_sample, company_id)
)
SELECT
    daily.product_area_key,
    daily.product_area_name,
    daily.product_area_id,
    daily.page_rule_id,
    daily.page_name,
    COALESCE(companies.companies_count, 0) AS companies_count,
    COALESCE(users.users_count, 0) AS users_count,
    daily.visits_count,
    daily.engaged_seconds,
    daily.click_count,
    daily.visits_with_click_count,
    company_engaged.top_company_id,
    company_engaged.top_company_name
FROM daily
LEFT JOIN companies
  ON companies.product_area_key = daily.product_area_key
 AND companies.page_rule_id IS NOT DISTINCT FROM daily.page_rule_id
LEFT JOIN users
  ON users.product_area_key = daily.product_area_key
 AND users.page_rule_id IS NOT DISTINCT FROM daily.page_rule_id
LEFT JOIN company_engaged
  ON company_engaged.product_area_key = daily.product_area_key
 AND company_engaged.page_rule_id IS NOT DISTINCT FROM daily.page_rule_id
ORDER BY daily.visits_count DESC, daily.page_name
"""


PAGE_DISPLAY_SUMMARY_SQL = """
WITH rule_daily AS (
    SELECT
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(pdm.product_area_name), ''),
                'Unassigned'
            )
        ) AS page_display_key,
        COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned') AS product_area_key,
        COALESCE(NULLIF(BTRIM(pdm.product_area_name), ''), 'Unassigned') AS product_area_name,
        pdm.product_area_id,
        pdm.page_rule_id,
        COALESCE(
            NULLIF(BTRIM(pr.page_name), ''),
            NULLIF(BTRIM(pdm.product_area_name), ''),
            'Unassigned'
        ) AS page_name,
        SUM(pdm.visits_count) AS visits_count,
        SUM(pdm.engaged_seconds) AS engaged_seconds,
        SUM(pdm.click_count) AS click_count,
        SUM(pdm.visits_with_click_count) AS visits_with_click_count
    FROM pages_pagedailymetric pdm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pdm.page_rule_id
    WHERE pdm.project_id = %s
      AND pdm.date >= %s
      AND pdm.date <= %s
    GROUP BY
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(pdm.product_area_name), ''),
                'Unassigned'
            )
        ),
        COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned'),
        COALESCE(NULLIF(BTRIM(pdm.product_area_name), ''), 'Unassigned'),
        pdm.product_area_id,
        pdm.page_rule_id,
        COALESCE(
            NULLIF(BTRIM(pr.page_name), ''),
            NULLIF(BTRIM(pdm.product_area_name), ''),
            'Unassigned'
        )
),
leaders AS (
    SELECT DISTINCT ON (page_display_key)
        page_display_key,
        product_area_key,
        product_area_name,
        product_area_id,
        page_rule_id,
        page_name
    FROM rule_daily
    ORDER BY
        page_display_key,
        (page_rule_id IS NULL),
        visits_count DESC,
        engaged_seconds DESC,
        page_rule_id,
        product_area_key,
        page_name
),
daily AS (
    SELECT
        page_display_key,
        COUNT(DISTINCT page_rule_id) AS page_count,
        ARRAY_AGG(DISTINCT page_rule_id ORDER BY page_rule_id)
            FILTER (WHERE page_rule_id IS NOT NULL) AS page_rule_ids,
        SUM(visits_count) AS visits_count,
        SUM(engaged_seconds) AS engaged_seconds,
        SUM(click_count) AS click_count,
        SUM(visits_with_click_count) AS visits_with_click_count
    FROM rule_daily
    GROUP BY page_display_key
),
company_rows AS (
    SELECT
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(pcdm.product_area_name), ''),
                'Unassigned'
            )
        ) AS page_display_key,
        pcdm.company_id,
        pcdm.company_name_sample,
        pcdm.engaged_seconds,
        pcdm.visits_count
    FROM pages_pagecompanydailymetric pcdm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pcdm.page_rule_id
    WHERE pcdm.project_id = %s
      AND pcdm.date >= %s
      AND pcdm.date <= %s
),
companies AS (
    SELECT
        page_display_key,
        COUNT(DISTINCT company_id)
            FILTER (WHERE company_id IS NOT NULL AND BTRIM(company_id) <> '') AS companies_count
    FROM company_rows
    GROUP BY page_display_key
),
users AS (
    SELECT
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(pudm.product_area_name), ''),
                'Unassigned'
            )
        ) AS page_display_key,
        COUNT(DISTINCT pudm.user_id)
            FILTER (WHERE pudm.user_id IS NOT NULL AND BTRIM(pudm.user_id) <> '') AS users_count
    FROM pages_pageuserdailymetric pudm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pudm.page_rule_id
    WHERE pudm.project_id = %s
      AND pudm.date >= %s
      AND pudm.date <= %s
    GROUP BY
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(pudm.product_area_name), ''),
                'Unassigned'
            )
        )
),
company_totals AS (
    SELECT
        page_display_key,
        company_id,
        COALESCE(MAX(NULLIF(BTRIM(company_name_sample), '')), company_id) AS company_name,
        SUM(engaged_seconds) AS company_engaged_seconds,
        SUM(visits_count) AS company_visits_count
    FROM company_rows
    WHERE company_id IS NOT NULL
      AND BTRIM(company_id) <> ''
    GROUP BY page_display_key, company_id
),
company_engaged AS (
    SELECT DISTINCT ON (page_display_key)
        page_display_key,
        company_id AS top_company_id,
        company_name AS top_company_name
    FROM company_totals
    ORDER BY
        page_display_key,
        company_engaged_seconds DESC,
        company_visits_count DESC,
        company_name,
        company_id
)
SELECT
    leaders.product_area_key,
    leaders.product_area_name,
    leaders.product_area_id,
    leaders.page_rule_id,
    COALESCE(daily.page_rule_ids, ARRAY[]::bigint[]) AS page_rule_ids,
    leaders.page_name,
    daily.page_display_key,
    daily.page_count,
    COALESCE(companies.companies_count, 0) AS companies_count,
    COALESCE(users.users_count, 0) AS users_count,
    daily.visits_count,
    daily.engaged_seconds,
    daily.click_count,
    daily.visits_with_click_count,
    company_engaged.top_company_id,
    company_engaged.top_company_name
FROM daily
JOIN leaders ON leaders.page_display_key = daily.page_display_key
LEFT JOIN companies ON companies.page_display_key = daily.page_display_key
LEFT JOIN users ON users.page_display_key = daily.page_display_key
LEFT JOIN company_engaged ON company_engaged.page_display_key = daily.page_display_key
ORDER BY daily.visits_count DESC, leaders.page_name, daily.page_display_key
"""


PROJECT_DISTINCT_COUNTS_SQL = """
SELECT
    (
        SELECT COUNT(DISTINCT company_id)
        FROM pages_pagecompanydailymetric
        WHERE project_id = %s AND date >= %s AND date <= %s
    ) AS active_companies_count,
    (
        SELECT COUNT(DISTINCT user_id)
        FROM pages_pageuserdailymetric
        WHERE project_id = %s AND date >= %s AND date <= %s
    ) AS active_users_count
"""


TREEMAP_PAGE_ROWS_SQL = """
WITH current_pages AS (
    SELECT
        COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned') AS product_area_key,
        COALESCE(NULLIF(MIN(pdm.product_area_name), ''), 'Unassigned') AS product_area_name,
        pdm.page_rule_id,
        COALESCE(NULLIF(MIN(pr.page_name), ''), NULLIF(MIN(pdm.product_area_name), ''), 'Unassigned') AS page_name,
        SUM(pdm.visits_count) AS visits_count,
        SUM(pdm.engaged_seconds) AS engaged_seconds
    FROM pages_pagedailymetric pdm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pdm.page_rule_id
    WHERE pdm.project_id = %s
      AND pdm.date >= %s
      AND pdm.date <= %s
    GROUP BY COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned'), pdm.page_rule_id
    HAVING SUM(pdm.engaged_seconds) > 0
),
page_companies AS (
    SELECT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        page_rule_id,
        COUNT(DISTINCT company_id) AS companies_count
    FROM pages_pagecompanydailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY COALESCE(NULLIF(product_area_key, ''), 'unassigned'), page_rule_id
),
area_companies AS (
    SELECT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        COUNT(DISTINCT company_id) AS area_companies_count
    FROM pages_pagecompanydailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY COALESCE(NULLIF(product_area_key, ''), 'unassigned')
),
previous_pages AS (
    SELECT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        page_rule_id,
        SUM(engaged_seconds) AS previous_engaged_seconds
    FROM pages_pagedailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY COALESCE(NULLIF(product_area_key, ''), 'unassigned'), page_rule_id
)
SELECT
    current_pages.product_area_key,
    current_pages.product_area_name,
    current_pages.page_rule_id,
    current_pages.page_name,
    current_pages.visits_count,
    current_pages.engaged_seconds,
    COALESCE(page_companies.companies_count, 0) AS companies_count,
    COALESCE(area_companies.area_companies_count, 0) AS area_companies_count,
    COALESCE(previous_pages.previous_engaged_seconds, 0) AS previous_engaged_seconds
FROM current_pages
LEFT JOIN page_companies
  ON page_companies.product_area_key = current_pages.product_area_key
 AND page_companies.page_rule_id IS NOT DISTINCT FROM current_pages.page_rule_id
LEFT JOIN area_companies
  ON area_companies.product_area_key = current_pages.product_area_key
LEFT JOIN previous_pages
  ON previous_pages.product_area_key = current_pages.product_area_key
 AND previous_pages.page_rule_id IS NOT DISTINCT FROM current_pages.page_rule_id
ORDER BY current_pages.engaged_seconds DESC, current_pages.page_name
"""


PENETRATION_DENOMINATOR_SQL = """
WITH area_companies AS (
    SELECT DISTINCT product_area_key, company_id
    FROM pages_pagecompanydailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
),
area_users AS (
    SELECT
        area_companies.product_area_key,
        COUNT(DISTINCT users.user_id) AS active_users_in_adopted_companies
    FROM area_companies
    JOIN pages_pageuserdailymetric users
      ON users.project_id = %s
     AND users.date >= %s
     AND users.date <= %s
     AND users.company_id = area_companies.company_id
    GROUP BY area_companies.product_area_key
)
SELECT * FROM area_users
"""


PAGE_PENETRATION_DENOMINATOR_SQL = """
WITH page_companies AS (
    SELECT DISTINCT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        page_rule_id,
        company_id
    FROM pages_pagecompanydailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
),
page_users AS (
    SELECT
        page_companies.product_area_key,
        page_companies.page_rule_id,
        COUNT(DISTINCT users.user_id) AS active_users_in_adopted_companies
    FROM page_companies
    JOIN pages_pageuserdailymetric users
      ON users.project_id = %s
     AND users.date >= %s
     AND users.date <= %s
     AND COALESCE(NULLIF(users.product_area_key, ''), 'unassigned') = page_companies.product_area_key
     AND users.page_rule_id IS NOT DISTINCT FROM page_companies.page_rule_id
     AND users.company_id = page_companies.company_id
    GROUP BY page_companies.product_area_key, page_companies.page_rule_id
)
SELECT * FROM page_users
"""


PAGE_DISPLAY_PENETRATION_DENOMINATOR_SQL = """
WITH page_companies AS (
    SELECT DISTINCT
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(companies.product_area_name), ''),
                'Unassigned'
            )
        ) AS page_display_key,
        companies.company_id
    FROM pages_pagecompanydailymetric companies
    LEFT JOIN tracker_projectpagerule pr ON pr.id = companies.page_rule_id
    WHERE companies.project_id = %s
      AND companies.date >= %s
      AND companies.date <= %s
      AND companies.company_id IS NOT NULL
      AND BTRIM(companies.company_id) <> ''
),
display_users AS (
    SELECT DISTINCT
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(users.product_area_name), ''),
                'Unassigned'
            )
        ) AS page_display_key,
        users.company_id,
        users.user_id
    FROM pages_pageuserdailymetric users
    LEFT JOIN tracker_projectpagerule pr ON pr.id = users.page_rule_id
    WHERE users.project_id = %s
      AND users.date >= %s
      AND users.date <= %s
      AND users.company_id IS NOT NULL
      AND BTRIM(users.company_id) <> ''
      AND users.user_id IS NOT NULL
      AND BTRIM(users.user_id) <> ''
),
page_users AS (
    SELECT
        page_companies.page_display_key,
        COUNT(DISTINCT display_users.user_id) AS active_users_in_adopted_companies
    FROM page_companies
    JOIN display_users
      ON display_users.page_display_key = page_companies.page_display_key
     AND display_users.company_id = page_companies.company_id
    GROUP BY page_companies.page_display_key
)
SELECT * FROM page_users
"""


DAILY_AREA_METRICS_SQL = """
WITH daily AS (
    SELECT
        pdm.date,
        COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned') AS product_area_key,
        COALESCE(NULLIF(MIN(pdm.product_area_name), ''), 'Unassigned') AS product_area_name,
        SUM(pdm.visits_count) AS visits_count,
        SUM(pdm.engaged_seconds) AS engaged_seconds,
        SUM(pdm.click_count) AS click_count,
        SUM(pdm.visits_with_click_count) AS visits_with_click_count
    FROM pages_pagedailymetric pdm
    WHERE pdm.project_id = %s
      AND pdm.date >= %s
      AND pdm.date <= %s
    GROUP BY pdm.date, COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned')
),
companies AS (
    SELECT
        date,
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        COUNT(DISTINCT company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> '') AS companies_count_daily
    FROM pages_pagecompanydailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY date, COALESCE(NULLIF(product_area_key, ''), 'unassigned')
),
users AS (
    SELECT
        date,
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL AND user_id <> '') AS users_count_daily
    FROM pages_pageuserdailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY date, COALESCE(NULLIF(product_area_key, ''), 'unassigned')
)
SELECT
    daily.date,
    daily.product_area_key,
    daily.product_area_name,
    daily.visits_count,
    daily.engaged_seconds,
    daily.click_count,
    daily.visits_with_click_count,
    COALESCE(companies.companies_count_daily, 0) AS companies_count_daily,
    COALESCE(users.users_count_daily, 0) AS users_count_daily,
    COALESCE(prdm.active_companies_count, 0) AS active_companies_count,
    COALESCE(prdm.active_users_count, 0) AS active_users_count
FROM daily
LEFT JOIN companies
  ON companies.date = daily.date
 AND companies.product_area_key = daily.product_area_key
LEFT JOIN users
  ON users.date = daily.date
 AND users.product_area_key = daily.product_area_key
LEFT JOIN pages_projectdailymetric prdm
  ON prdm.project_id = %s
 AND prdm.date = daily.date
ORDER BY daily.date, daily.product_area_key
"""


DAILY_PAGE_METRICS_SQL = """
SELECT
    pdm.date,
    COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned') AS product_area_key,
    MIN(pdm.product_area_name) AS product_area_name,
    pdm.page_rule_id,
    SUM(pdm.visits_count) AS visits_count,
    SUM(pdm.engaged_seconds) AS engaged_seconds,
    SUM(pdm.click_count) AS click_count,
    SUM(pdm.visits_with_click_count) AS visits_with_click_count,
    SUM(pdm.companies_count_daily) AS companies_count_daily,
    SUM(pdm.users_count_daily) AS users_count_daily,
    MAX(prdm.active_companies_count) AS active_companies_count,
    MAX(prdm.active_users_count) AS active_users_count
FROM pages_pagedailymetric pdm
LEFT JOIN pages_projectdailymetric prdm
  ON prdm.project_id = pdm.project_id
 AND prdm.date = pdm.date
WHERE pdm.project_id = %s
  AND pdm.date >= %s
  AND pdm.date <= %s
GROUP BY pdm.date, COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned'), pdm.page_rule_id
ORDER BY pdm.date, product_area_key, pdm.page_rule_id
"""


DAILY_PAGE_DISPLAY_METRICS_SQL = """
WITH daily AS (
    SELECT
        pdm.date,
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(pdm.product_area_name), ''),
                'Unassigned'
            )
        ) AS page_display_key,
        SUM(pdm.visits_count) AS visits_count,
        SUM(pdm.engaged_seconds) AS engaged_seconds,
        SUM(pdm.click_count) AS click_count,
        SUM(pdm.visits_with_click_count) AS visits_with_click_count
    FROM pages_pagedailymetric pdm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pdm.page_rule_id
    WHERE pdm.project_id = %s
      AND pdm.date >= %s
      AND pdm.date <= %s
    GROUP BY
        pdm.date,
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(pdm.product_area_name), ''),
                'Unassigned'
            )
        )
),
companies AS (
    SELECT
        companies.date,
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(companies.product_area_name), ''),
                'Unassigned'
            )
        ) AS page_display_key,
        COUNT(DISTINCT companies.company_id)
            FILTER (WHERE companies.company_id IS NOT NULL AND BTRIM(companies.company_id) <> '') AS companies_count_daily
    FROM pages_pagecompanydailymetric companies
    LEFT JOIN tracker_projectpagerule pr ON pr.id = companies.page_rule_id
    WHERE companies.project_id = %s
      AND companies.date >= %s
      AND companies.date <= %s
    GROUP BY
        companies.date,
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(companies.product_area_name), ''),
                'Unassigned'
            )
        )
),
users AS (
    SELECT
        users.date,
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(users.product_area_name), ''),
                'Unassigned'
            )
        ) AS page_display_key,
        COUNT(DISTINCT users.user_id)
            FILTER (WHERE users.user_id IS NOT NULL AND BTRIM(users.user_id) <> '') AS users_count_daily
    FROM pages_pageuserdailymetric users
    LEFT JOIN tracker_projectpagerule pr ON pr.id = users.page_rule_id
    WHERE users.project_id = %s
      AND users.date >= %s
      AND users.date <= %s
    GROUP BY
        users.date,
        LOWER(
            COALESCE(
                NULLIF(BTRIM(pr.page_name), ''),
                NULLIF(BTRIM(users.product_area_name), ''),
                'Unassigned'
            )
        )
)
SELECT
    daily.date,
    daily.page_display_key,
    daily.visits_count,
    daily.engaged_seconds,
    daily.click_count,
    daily.visits_with_click_count,
    COALESCE(companies.companies_count_daily, 0) AS companies_count_daily,
    COALESCE(users.users_count_daily, 0) AS users_count_daily,
    COALESCE(prdm.active_companies_count, 0) AS active_companies_count,
    COALESCE(prdm.active_users_count, 0) AS active_users_count
FROM daily
LEFT JOIN companies
  ON companies.date = daily.date
 AND companies.page_display_key = daily.page_display_key
LEFT JOIN users
  ON users.date = daily.date
 AND users.page_display_key = daily.page_display_key
LEFT JOIN pages_projectdailymetric prdm
  ON prdm.project_id = %s
 AND prdm.date = daily.date
ORDER BY daily.date, daily.page_display_key
"""


DAILY_PAGE_METRICS_FOR_RULES_SQL = """
SELECT
    pdm.date,
    COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned') AS product_area_key,
    MIN(pdm.product_area_name) AS product_area_name,
    pdm.page_rule_id,
    SUM(pdm.visits_count) AS visits_count,
    SUM(pdm.engaged_seconds) AS engaged_seconds,
    SUM(pdm.click_count) AS click_count,
    SUM(pdm.visits_with_click_count) AS visits_with_click_count,
    SUM(pdm.companies_count_daily) AS companies_count_daily,
    SUM(pdm.users_count_daily) AS users_count_daily,
    MAX(prdm.active_companies_count) AS active_companies_count,
    MAX(prdm.active_users_count) AS active_users_count
FROM pages_pagedailymetric pdm
LEFT JOIN pages_projectdailymetric prdm
  ON prdm.project_id = pdm.project_id
 AND prdm.date = pdm.date
WHERE pdm.project_id = %s
  AND pdm.date >= %s
  AND pdm.date <= %s
  AND pdm.page_rule_id = ANY(%s::bigint[])
GROUP BY pdm.date, COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned'), pdm.page_rule_id
ORDER BY pdm.date, product_area_key, pdm.page_rule_id
"""


TOP_ACTIONS_SQL = """
WITH current_page_rows AS (
    SELECT
        CONCAT_WS(
            '::',
            COALESCE(NULLIF(rule.product_area, ''), NULLIF(metrics.product_area_key, ''), 'unassigned'),
            COALESCE(NULLIF(rule.page_name, ''), NULLIF(metrics.page_label, ''), metrics.url_normalized)
        ) AS page_key,
        COALESCE(NULLIF(rule.product_area, ''), NULLIF(metrics.product_area_name, ''), 'Unassigned') AS page_group,
        COALESCE(NULLIF(rule.page_name, ''), NULLIF(metrics.page_label, ''), metrics.url_normalized) AS page_label,
        metrics.url_normalized,
        metrics.page_rule_id,
        metrics.visits_count,
        metrics.engaged_seconds
    FROM pages_rawpagedailymetric metrics
    LEFT JOIN tracker_projectpagerule rule ON rule.id = metrics.page_rule_id
    WHERE metrics.project_id = %s
      AND metrics.date >= %s
      AND metrics.date <= %s
),
top_pages AS (
    SELECT
        page_key,
        MIN(page_group) AS page_group,
        MIN(page_label) AS page_label,
        MIN(url_normalized) AS url_normalized,
        MIN(page_rule_id) AS page_rule_id,
        SUM(visits_count) AS visits_count,
        SUM(engaged_seconds) AS engaged_seconds
    FROM current_page_rows
    GROUP BY page_key
    ORDER BY SUM(visits_count) DESC, MIN(page_label)
    LIMIT 10
),
previous_page_rows AS (
    SELECT
        CONCAT_WS(
            '::',
            COALESCE(NULLIF(rule.product_area, ''), NULLIF(metrics.product_area_key, ''), 'unassigned'),
            COALESCE(NULLIF(rule.page_name, ''), NULLIF(metrics.page_label, ''), metrics.url_normalized)
        ) AS page_key,
        metrics.visits_count
    FROM pages_rawpagedailymetric metrics
    LEFT JOIN tracker_projectpagerule rule ON rule.id = metrics.page_rule_id
    WHERE metrics.project_id = %s
      AND metrics.date >= %s
      AND metrics.date <= %s
),
previous_pages AS (
    SELECT
        previous_page_rows.page_key,
        SUM(previous_page_rows.visits_count) AS previous_visits_count
    FROM previous_page_rows
    JOIN top_pages ON top_pages.page_key = previous_page_rows.page_key
    GROUP BY previous_page_rows.page_key
),
current_action_rows AS (
    SELECT
        CONCAT_WS(
            '::',
            COALESCE(NULLIF(rule.product_area, ''), NULLIF(actions.product_area_key, ''), 'unassigned'),
            COALESCE(NULLIF(rule.page_name, ''), actions.url_normalized)
        ) AS page_key,
        actions.element_key,
        actions.clicks_count,
        actions.visits_with_action_count,
        actions.users_count_daily,
        actions.companies_count_daily
    FROM pages_rawpageactiondailymetric actions
    LEFT JOIN tracker_projectpagerule rule ON rule.id = actions.page_rule_id
    WHERE actions.project_id = %s
      AND actions.date >= %s
      AND actions.date <= %s
),
actions AS (
    SELECT
        current_action_rows.page_key,
        current_action_rows.element_key,
        SUM(current_action_rows.clicks_count) AS clicks_count,
        SUM(current_action_rows.visits_with_action_count) AS visits_with_action_count,
        SUM(current_action_rows.users_count_daily) AS users_count_daily,
        SUM(current_action_rows.companies_count_daily) AS companies_count_daily,
        ROW_NUMBER() OVER (
            PARTITION BY current_action_rows.page_key
            ORDER BY SUM(current_action_rows.clicks_count) DESC, current_action_rows.element_key
        ) AS action_rank
    FROM current_action_rows
    JOIN top_pages ON top_pages.page_key = current_action_rows.page_key
    GROUP BY current_action_rows.page_key, current_action_rows.element_key
),
previous_action_rows AS (
    SELECT
        CONCAT_WS(
            '::',
            COALESCE(NULLIF(rule.product_area, ''), NULLIF(actions.product_area_key, ''), 'unassigned'),
            COALESCE(NULLIF(rule.page_name, ''), actions.url_normalized)
        ) AS page_key,
        actions.element_key,
        actions.clicks_count,
        actions.visits_with_action_count
    FROM pages_rawpageactiondailymetric actions
    LEFT JOIN tracker_projectpagerule rule ON rule.id = actions.page_rule_id
    WHERE actions.project_id = %s
      AND actions.date >= %s
      AND actions.date <= %s
),
previous_actions AS (
    SELECT
        previous_action_rows.page_key,
        previous_action_rows.element_key,
        SUM(previous_action_rows.clicks_count) AS previous_clicks_count,
        SUM(previous_action_rows.visits_with_action_count) AS previous_visits_with_action_count
    FROM previous_action_rows
    JOIN top_pages ON top_pages.page_key = previous_action_rows.page_key
    GROUP BY previous_action_rows.page_key, previous_action_rows.element_key
)
SELECT
    top_pages.page_key,
    top_pages.url_normalized,
    top_pages.page_rule_id,
    top_pages.page_group,
    top_pages.page_label,
    top_pages.visits_count,
    top_pages.engaged_seconds,
    actions.element_key,
    COALESCE(actions.clicks_count, 0) AS clicks_count,
    COALESCE(actions.visits_with_action_count, 0) AS visits_with_action_count,
    COALESCE(actions.users_count_daily, 0) AS users_count_daily,
    COALESCE(actions.companies_count_daily, 0) AS companies_count_daily,
    COALESCE(previous_pages.previous_visits_count, 0) AS previous_page_visits_count,
    COALESCE(previous_actions.previous_clicks_count, 0) AS previous_clicks_count,
    COALESCE(previous_actions.previous_visits_with_action_count, 0) AS previous_visits_with_action_count
FROM top_pages
LEFT JOIN actions
  ON actions.page_key = top_pages.page_key
 AND actions.action_rank <= 5
LEFT JOIN previous_pages
  ON previous_pages.page_key = top_pages.page_key
LEFT JOIN previous_actions
  ON previous_actions.page_key = actions.page_key
 AND previous_actions.element_key = actions.element_key
ORDER BY top_pages.visits_count DESC, top_pages.page_label, actions.action_rank
"""


SANKEY_SQL = """
WITH normalized AS (
    SELECT
        COALESCE(from_page_rule_id::text, NULLIF(from_url_normalized, ''), NULLIF(from_product_area_key, ''), 'unassigned') AS from_page_key,
        COALESCE(to_page_rule_id::text, NULLIF(to_url_normalized, ''), NULLIF(to_product_area_key, ''), 'unassigned') AS to_page_key,
        COALESCE(NULLIF(from_rule.page_name, ''), NULLIF(from_url_normalized, ''), NULLIF(from_product_area_name, ''), 'Unassigned') AS from_page_name,
        COALESCE(NULLIF(to_rule.page_name, ''), NULLIF(to_url_normalized, ''), NULLIF(to_product_area_name, ''), 'Unassigned') AS to_page_name,
        from_product_area_key,
        from_product_area_name,
        to_product_area_key,
        to_product_area_name,
        session_id,
        company_id
    FROM pages_pagetransition transitions
    LEFT JOIN tracker_projectpagerule from_rule ON from_rule.id = transitions.from_page_rule_id
    LEFT JOIN tracker_projectpagerule to_rule ON to_rule.id = transitions.to_page_rule_id
    WHERE transitions.project_id = %s
      AND (transition_ts AT TIME ZONE %s)::date >= %s
      AND (transition_ts AT TIME ZONE %s)::date <= %s
),
links AS (
    SELECT
        from_page_key,
        MIN(from_page_name) AS from_page_name,
        MIN(from_product_area_key) AS from_product_area_key,
        MIN(from_product_area_name) AS from_product_area_name,
        to_page_key,
        MIN(to_page_name) AS to_page_name,
        MIN(to_product_area_key) AS to_product_area_key,
        MIN(to_product_area_name) AS to_product_area_name,
        COUNT(*) AS transition_count,
        COUNT(DISTINCT session_id) AS sessions_count,
        COUNT(DISTINCT company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> '') AS companies_count
    FROM normalized
    WHERE from_page_key <> to_page_key
    GROUP BY from_page_key, to_page_key
    ORDER BY COUNT(*) DESC
    LIMIT 40
)
SELECT * FROM links
"""


DETAIL_FLOW_SQL = """
WITH normalized AS (
    SELECT
        COALESCE(from_page_rule_id::text, NULLIF(from_url_normalized, ''), NULLIF(from_product_area_key, ''), 'unassigned') AS from_page_key,
        COALESCE(to_page_rule_id::text, NULLIF(to_url_normalized, ''), NULLIF(to_product_area_key, ''), 'unassigned') AS to_page_key,
        COALESCE(NULLIF(from_rule.page_name, ''), NULLIF(from_url_normalized, ''), NULLIF(from_product_area_name, ''), 'Unassigned') AS from_page_name,
        COALESCE(NULLIF(to_rule.page_name, ''), NULLIF(to_url_normalized, ''), NULLIF(to_product_area_name, ''), 'Unassigned') AS to_page_name,
        transitions.from_page_rule_id,
        transitions.to_page_rule_id,
        from_product_area_key,
        from_product_area_name,
        to_product_area_key,
        to_product_area_name,
        session_id,
        company_id
    FROM pages_pagetransition transitions
    LEFT JOIN tracker_projectpagerule from_rule ON from_rule.id = transitions.from_page_rule_id
    LEFT JOIN tracker_projectpagerule to_rule ON to_rule.id = transitions.to_page_rule_id
    WHERE transitions.project_id = %s
      AND transitions.transition_ts >= %s
      AND transitions.transition_ts < %s
      AND (
        (
            %s IS NOT NULL
            AND (transitions.from_page_rule_id = %s OR transitions.to_page_rule_id = %s)
        )
        OR (
            %s IS NULL
            AND (
                COALESCE(NULLIF(from_rule.page_name, ''), NULLIF(transitions.from_url_normalized, ''), NULLIF(transitions.from_product_area_name, ''), 'Unassigned') = %s
                OR COALESCE(NULLIF(to_rule.page_name, ''), NULLIF(transitions.to_url_normalized, ''), NULLIF(transitions.to_product_area_name, ''), 'Unassigned') = %s
            )
        )
      )
),
filtered AS (
    SELECT *
    FROM normalized
),
links AS (
    SELECT
        from_page_key,
        MIN(from_page_name) AS from_page_name,
        MIN(from_product_area_key) AS from_product_area_key,
        MIN(from_product_area_name) AS from_product_area_name,
        to_page_key,
        MIN(to_page_name) AS to_page_name,
        MIN(to_product_area_key) AS to_product_area_key,
        MIN(to_product_area_name) AS to_product_area_name,
        COUNT(*) AS transition_count,
        COUNT(DISTINCT session_id) AS sessions_count,
        COUNT(DISTINCT company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> '') AS companies_count
    FROM filtered
    WHERE from_page_key <> to_page_key
    GROUP BY from_page_key, to_page_key
    ORDER BY COUNT(*) DESC
    LIMIT 60
)
SELECT * FROM links
"""


DETAIL_FLOW_BY_RULE_SQL = """
WITH normalized AS (
    SELECT
        COALESCE(from_page_rule_id::text, NULLIF(from_url_normalized, ''), NULLIF(from_product_area_key, ''), 'unassigned') AS from_page_key,
        COALESCE(to_page_rule_id::text, NULLIF(to_url_normalized, ''), NULLIF(to_product_area_key, ''), 'unassigned') AS to_page_key,
        COALESCE(NULLIF(from_rule.page_name, ''), NULLIF(from_url_normalized, ''), NULLIF(from_product_area_name, ''), 'Unassigned') AS from_page_name,
        COALESCE(NULLIF(to_rule.page_name, ''), NULLIF(to_url_normalized, ''), NULLIF(to_product_area_name, ''), 'Unassigned') AS to_page_name,
        transitions.from_page_rule_id,
        transitions.to_page_rule_id,
        from_product_area_key,
        from_product_area_name,
        to_product_area_key,
        to_product_area_name,
        session_id,
        company_id
    FROM pages_pagetransition transitions
    LEFT JOIN tracker_projectpagerule from_rule ON from_rule.id = transitions.from_page_rule_id
    LEFT JOIN tracker_projectpagerule to_rule ON to_rule.id = transitions.to_page_rule_id
    WHERE transitions.project_id = %s
      AND transitions.transition_ts >= %s
      AND transitions.transition_ts < %s
      AND transitions.from_page_rule_id = %s

    UNION ALL

    SELECT
        COALESCE(from_page_rule_id::text, NULLIF(from_url_normalized, ''), NULLIF(from_product_area_key, ''), 'unassigned') AS from_page_key,
        COALESCE(to_page_rule_id::text, NULLIF(to_url_normalized, ''), NULLIF(to_product_area_key, ''), 'unassigned') AS to_page_key,
        COALESCE(NULLIF(from_rule.page_name, ''), NULLIF(from_url_normalized, ''), NULLIF(from_product_area_name, ''), 'Unassigned') AS from_page_name,
        COALESCE(NULLIF(to_rule.page_name, ''), NULLIF(to_url_normalized, ''), NULLIF(to_product_area_name, ''), 'Unassigned') AS to_page_name,
        transitions.from_page_rule_id,
        transitions.to_page_rule_id,
        from_product_area_key,
        from_product_area_name,
        to_product_area_key,
        to_product_area_name,
        session_id,
        company_id
    FROM pages_pagetransition transitions
    LEFT JOIN tracker_projectpagerule from_rule ON from_rule.id = transitions.from_page_rule_id
    LEFT JOIN tracker_projectpagerule to_rule ON to_rule.id = transitions.to_page_rule_id
    WHERE transitions.project_id = %s
      AND transitions.transition_ts >= %s
      AND transitions.transition_ts < %s
      AND transitions.to_page_rule_id = %s
),
links AS (
    SELECT
        from_page_key,
        MIN(from_page_name) AS from_page_name,
        MIN(from_product_area_key) AS from_product_area_key,
        MIN(from_product_area_name) AS from_product_area_name,
        to_page_key,
        MIN(to_page_name) AS to_page_name,
        MIN(to_product_area_key) AS to_product_area_key,
        MIN(to_product_area_name) AS to_product_area_name,
        COUNT(*) AS transition_count,
        COUNT(DISTINCT session_id) AS sessions_count,
        COUNT(DISTINCT company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> '') AS companies_count
    FROM normalized
    WHERE from_page_key <> to_page_key
    GROUP BY from_page_key, to_page_key
    ORDER BY COUNT(*) DESC
    LIMIT 60
)
SELECT * FROM links
"""


SCATTER_SQL = """
WITH top_areas AS (
    SELECT product_area_key, MIN(product_area_name) AS product_area_name, SUM(engaged_seconds) AS engaged_seconds
    FROM pages_pagedailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY product_area_key
    ORDER BY SUM(engaged_seconds) DESC
    LIMIT 8
),
company_engagement AS (
    SELECT
        product_area_key,
        company_id,
        COALESCE(MIN(company_name_sample) FILTER (WHERE company_name_sample <> ''), company_id) AS company_name,
        SUM(engaged_seconds) AS total_engaged_seconds,
        SUM(visits_count) AS visits_count,
        SUM(click_count) AS clicks_count
    FROM pages_pagecompanydailymetric
    WHERE project_id = %s
      AND date >= %s
      AND date <= %s
    GROUP BY product_area_key, company_id
),
company_users AS (
    SELECT product_area_key, company_id, AVG(active_users * 1.0) AS active_users
    FROM (
        SELECT product_area_key, company_id, date, COUNT(DISTINCT user_id) AS active_users
        FROM pages_pageuserdailymetric
        WHERE project_id = %s
          AND date >= %s
          AND date <= %s
        GROUP BY product_area_key, company_id, date
    ) daily_users
    GROUP BY product_area_key, company_id
),
ranked AS (
    SELECT
        top_areas.product_area_key,
        top_areas.product_area_name,
        company_engagement.company_id,
        company_engagement.company_name,
        COALESCE(company_users.active_users, 0) AS active_users,
        company_engagement.total_engaged_seconds,
        company_engagement.visits_count,
        company_engagement.clicks_count,
        ROW_NUMBER() OVER (
            PARTITION BY top_areas.product_area_key
            ORDER BY company_engagement.total_engaged_seconds DESC, company_engagement.company_name
        ) AS row_number
    FROM top_areas
    JOIN company_engagement ON company_engagement.product_area_key = top_areas.product_area_key
    LEFT JOIN company_users
      ON company_users.product_area_key = company_engagement.product_area_key
     AND company_users.company_id = company_engagement.company_id
)
SELECT *
FROM ranked
WHERE row_number <= 80
ORDER BY product_area_name, row_number
"""


UPSERT_OVERVIEW_CACHE_SQL = """
INSERT INTO pages_pagesoverviewcache (
    project_id,
    range_key,
    start_date,
    end_date,
    filters_hash,
    payload_json,
    source_max_event_ts,
    generated_at,
    expires_at,
    is_stale
)
VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, false)
ON CONFLICT (project_id, range_key, filters_hash)
DO UPDATE SET
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date,
    payload_json = EXCLUDED.payload_json,
    source_max_event_ts = EXCLUDED.source_max_event_ts,
    generated_at = EXCLUDED.generated_at,
    expires_at = EXCLUDED.expires_at,
    is_stale = false
"""


FETCH_OVERVIEW_CACHE_SQL = """
SELECT
    payload_json,
    source_max_event_ts,
    generated_at,
    expires_at,
    is_stale,
    start_date,
    end_date
FROM pages_pagesoverviewcache
WHERE project_id = %s
  AND range_key = %s
  AND filters_hash = %s
LIMIT 1
"""


FETCH_OVERVIEW_CACHE_JSON_SQL = """
SELECT
    payload_json::text AS payload_json_text,
    payload_json ->> 'schema_version' AS schema_version,
    source_max_event_ts,
    generated_at,
    expires_at,
    is_stale,
    start_date,
    end_date
FROM pages_pagesoverviewcache
WHERE project_id = %s
  AND range_key = %s
  AND filters_hash = %s
LIMIT 1
"""


FETCH_OVERVIEW_CACHE_DETAIL_ROWS_SQL = """
SELECT
    payload_json -> 'change_aware_rows' AS change_aware_rows,
    payload_json -> 'project' AS project,
    payload_json ->> 'schema_version' AS schema_version
FROM pages_pagesoverviewcache
WHERE project_id = %s
  AND range_key = %s
  AND filters_hash = %s
LIMIT 1
"""


UPSERT_COMPANIES_OVERVIEW_CACHE_SQL = """
INSERT INTO pages_companiesoverviewcache (
    project_id,
    range_key,
    start_date,
    end_date,
    filters_hash,
    payload_json,
    source_max_event_ts,
    generated_at,
    expires_at,
    is_stale
)
VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, false)
ON CONFLICT (project_id, range_key, filters_hash)
DO UPDATE SET
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date,
    payload_json = EXCLUDED.payload_json,
    source_max_event_ts = EXCLUDED.source_max_event_ts,
    generated_at = EXCLUDED.generated_at,
    expires_at = EXCLUDED.expires_at,
    is_stale = false
"""


FETCH_COMPANIES_OVERVIEW_CACHE_SQL = """
SELECT
    payload_json,
    source_max_event_ts,
    generated_at,
    expires_at,
    is_stale,
    start_date,
    end_date
FROM pages_companiesoverviewcache
WHERE project_id = %s
  AND range_key = %s
  AND filters_hash = %s
LIMIT 1
"""


FETCH_COMPANIES_OVERVIEW_CACHE_JSON_SQL = """
SELECT
    payload_json::text AS payload_json_text,
    payload_json ->> 'schema_version' AS schema_version,
    source_max_event_ts,
    generated_at,
    expires_at,
    is_stale,
    start_date,
    end_date
FROM pages_companiesoverviewcache
WHERE project_id = %s
  AND range_key = %s
  AND filters_hash = %s
LIMIT 1
"""


UPSERT_USERS_OVERVIEW_CACHE_SQL = """
INSERT INTO pages_usersoverviewcache (
    project_id,
    range_key,
    start_date,
    end_date,
    filters_hash,
    payload_json,
    source_max_event_ts,
    generated_at,
    expires_at,
    is_stale
)
VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, false)
ON CONFLICT (project_id, range_key, filters_hash)
DO UPDATE SET
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date,
    payload_json = EXCLUDED.payload_json,
    source_max_event_ts = EXCLUDED.source_max_event_ts,
    generated_at = EXCLUDED.generated_at,
    expires_at = EXCLUDED.expires_at,
    is_stale = false
"""


FETCH_USERS_OVERVIEW_CACHE_SQL = """
SELECT
    payload_json,
    source_max_event_ts,
    generated_at,
    expires_at,
    is_stale,
    start_date,
    end_date
FROM pages_usersoverviewcache
WHERE project_id = %s
  AND range_key = %s
  AND filters_hash = %s
LIMIT 1
"""


FETCH_USERS_OVERVIEW_CACHE_JSON_SQL = """
SELECT
    payload_json::text AS payload_json_text,
    payload_json ->> 'schema_version' AS schema_version,
    source_max_event_ts,
    generated_at,
    expires_at,
    is_stale,
    start_date,
    end_date
FROM pages_usersoverviewcache
WHERE project_id = %s
  AND range_key = %s
  AND filters_hash = %s
LIMIT 1
"""


UPSERT_COMPANY_DETAIL_CACHE_SQL = """
INSERT INTO pages_companiesdetailcache (
    project_id,
    range_key,
    company_id,
    start_date,
    end_date,
    filters_hash,
    payload_json,
    generated_at,
    expires_at,
    is_stale
)
VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, false)
ON CONFLICT (project_id, range_key, company_id, filters_hash)
DO UPDATE SET
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date,
    payload_json = EXCLUDED.payload_json,
    generated_at = EXCLUDED.generated_at,
    expires_at = EXCLUDED.expires_at,
    is_stale = false
"""


FETCH_COMPANY_DETAIL_CACHE_SQL = """
SELECT
    payload_json,
    payload_json ->> 'schema_version' AS schema_version,
    generated_at,
    expires_at,
    is_stale,
    start_date,
    end_date
FROM pages_companiesdetailcache
WHERE project_id = %s
  AND range_key = %s
  AND company_id = %s
  AND filters_hash = %s
LIMIT 1
"""


UPSERT_DETAIL_CACHE_SQL = """
INSERT INTO pages_pagesdetailcache (
    project_id,
    range_key,
    page_rule_id,
    start_date,
    end_date,
    filters_hash,
    payload_json,
    generated_at,
    expires_at,
    is_stale
)
VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, false)
ON CONFLICT (project_id, range_key, page_rule_id, filters_hash)
DO UPDATE SET
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date,
    payload_json = EXCLUDED.payload_json,
    generated_at = EXCLUDED.generated_at,
    expires_at = EXCLUDED.expires_at,
    is_stale = false
"""


FETCH_DETAIL_CACHE_SQL = """
SELECT
    payload_json,
    payload_json ->> 'schema_version' AS schema_version,
    generated_at,
    expires_at,
    is_stale,
    start_date,
    end_date
FROM pages_pagesdetailcache
WHERE project_id = %s
  AND range_key = %s
  AND page_rule_id = %s
  AND filters_hash = %s
LIMIT 1
"""


UPSERT_SCATTER_TOOLTIP_CACHE_SQL = """
INSERT INTO pages_pagesscattertooltipcache (
    project_id,
    range_key,
    start_date,
    end_date,
    filters_hash,
    payload_json,
    generated_at,
    expires_at,
    is_stale
)
VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, false)
ON CONFLICT (project_id, range_key, filters_hash)
DO UPDATE SET
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date,
    payload_json = EXCLUDED.payload_json,
    generated_at = EXCLUDED.generated_at,
    expires_at = EXCLUDED.expires_at,
    is_stale = false
"""


FETCH_SCATTER_TOOLTIP_CACHE_SQL = """
SELECT payload_json, generated_at, expires_at, is_stale
FROM pages_pagesscattertooltipcache
WHERE project_id = %s
  AND range_key = %s
  AND filters_hash = %s
LIMIT 1
"""
