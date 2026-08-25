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


def execute_values(prefix, values_template, suffix, rows, *, page_size=100):
    """
    Run one statement per *page_size* rows instead of one per row.

    Repeats *values_template* once per row so a batch costs a single round
    trip. Callers must not put the same conflict target twice in one batch:
    ``ON CONFLICT`` cannot update a row it has already inserted in the same
    statement, which Postgres rejects outright.
    """

    rows = list(rows or [])
    if not rows:
        return 0

    affected = 0
    with connection.cursor() as cursor:
        for start in range(0, len(rows), page_size):
            page = rows[start:start + page_size]
            statement = f'{prefix} {", ".join([values_template] * len(page))} {suffix}'
            params = [value for row in page for value in row]
            cursor.execute(statement, params)
            affected += cursor.rowcount
    return affected


def _period_to_date_row_key_sql(alias, grain, rule_alias=''):
    if grain == 'product_area':
        return f"COALESCE(NULLIF({alias}.product_area_key, ''), 'unassigned')"
    if grain == 'page':
        return (
            "CONCAT("
            f"COALESCE(NULLIF({alias}.product_area_key, ''), 'unassigned'),"
            "'::',"
            f"COALESCE({alias}.page_rule_id::text, '')"
            ")"
        )
    if grain == 'display_page':
        return (
            "CONCAT("
            f"LOWER(COALESCE(NULLIF(BTRIM({alias}.product_area_key), ''), 'unassigned')),"
            "'::',"
            "LOWER(COALESCE("
            f"NULLIF(BTRIM({rule_alias}.page_name), ''),"
            f"NULLIF(BTRIM({alias}.product_area_name), ''),"
            "'Unassigned'"
            "))"
            ")"
        )
    raise ValueError(f'Unsupported analytics grain: {grain}')


def cumulative_identity_first_seen_sql(grain, *, filtered=False):
    """Return exact first-seen identity dates used by period-to-date KPI series."""

    if grain not in {'page', 'display_page', 'product_area'}:
        raise ValueError(f'Unsupported analytics grain: {grain}')

    company_join = ''
    user_join = ''
    linked_user_join = ''
    if grain == 'display_page':
        company_join = 'LEFT JOIN tracker_projectpagerule company_rule ON company_rule.id = pcdm.page_rule_id'
        user_join = 'LEFT JOIN tracker_projectpagerule user_rule ON user_rule.id = pudm.page_rule_id'
        linked_user_join = 'LEFT JOIN tracker_projectpagerule linked_rule ON linked_rule.id = pudm.page_rule_id'

    company_row_key = _period_to_date_row_key_sql('pcdm', grain, 'company_rule')
    user_row_key = _period_to_date_row_key_sql('pudm', grain, 'user_rule')
    linked_user_row_key = _period_to_date_row_key_sql('pudm', grain, 'linked_rule')
    company_cohort = 'AND pcdm.company_id = ANY(%(cohort)s)' if filtered else ''
    user_cohort = 'AND pudm.company_id = ANY(%(cohort)s)' if filtered else ''
    company_identity_filter = "AND BTRIM(pcdm.company_id) <> ''" if grain == 'display_page' else ''
    user_identity_filter = "AND BTRIM(pudm.user_id) <> ''" if grain == 'display_page' else ''
    linked_company_filter = "AND BTRIM(pudm.company_id) <> ''" if grain == 'display_page' else ''
    linked_user_filter = "AND BTRIM(pudm.user_id) <> ''" if grain == 'display_page' else ''

    if grain == 'product_area':
        linked_user_columns = """
            pudm.company_id,
            pudm.user_id,
            pudm.date
        """
        linked_user_group = 'company_id, user_id'
        penetration_join = 'lu.company_id = ec.company_id'
    else:
        linked_user_columns = f"""
            {linked_user_row_key} AS row_key,
            pudm.company_id,
            pudm.user_id,
            pudm.date
        """
        linked_user_group = 'row_key, company_id, user_id'
        penetration_join = 'lu.row_key = ec.row_key AND lu.company_id = ec.company_id'

    return f"""
WITH entity_company_rows AS (
    SELECT
        {company_row_key} AS row_key,
        pcdm.company_id,
        pcdm.date
    FROM pages_pagecompanydailymetric pcdm
    {company_join}
    WHERE pcdm.project_id = %(project_id)s
      AND pcdm.date >= %(start_date)s
      AND pcdm.date <= %(end_date)s
      AND pcdm.company_id IS NOT NULL
      {company_identity_filter}
      {company_cohort}
),
entity_company_first AS (
    SELECT row_key, company_id, MIN(date) AS first_date
    FROM entity_company_rows
    GROUP BY row_key, company_id
),
entity_user_rows AS (
    SELECT
        {user_row_key} AS row_key,
        pudm.user_id,
        pudm.date
    FROM pages_pageuserdailymetric pudm
    {user_join}
    WHERE pudm.project_id = %(project_id)s
      AND pudm.date >= %(start_date)s
      AND pudm.date <= %(end_date)s
      AND pudm.user_id IS NOT NULL
      {user_identity_filter}
      {user_cohort}
),
entity_user_first AS (
    SELECT row_key, user_id, MIN(date) AS first_date
    FROM entity_user_rows
    GROUP BY row_key, user_id
),
project_company_rows AS (
    SELECT pcdm.company_id, pcdm.date
    FROM pages_pagecompanydailymetric pcdm
    WHERE pcdm.project_id = %(project_id)s
      AND pcdm.date >= %(start_date)s
      AND pcdm.date <= %(end_date)s
      AND pcdm.company_id IS NOT NULL
      {company_cohort}
),
project_company_first AS (
    SELECT company_id, MIN(date) AS first_date
    FROM project_company_rows
    GROUP BY company_id
),
linked_user_rows AS (
    SELECT
        {linked_user_columns}
    FROM pages_pageuserdailymetric pudm
    {linked_user_join}
    WHERE pudm.project_id = %(project_id)s
      AND pudm.date >= %(start_date)s
      AND pudm.date <= %(end_date)s
      AND pudm.company_id IS NOT NULL
      {linked_company_filter}
      AND pudm.user_id IS NOT NULL
      {linked_user_filter}
),
linked_user_first AS (
    SELECT {linked_user_group}, MIN(date) AS first_date
    FROM linked_user_rows
    GROUP BY {linked_user_group}
),
penetration_first AS (
    SELECT
        ec.row_key,
        lu.user_id,
        MIN(GREATEST(ec.first_date, lu.first_date)) AS first_date
    FROM entity_company_first ec
    JOIN linked_user_first lu ON {penetration_join}
    GROUP BY ec.row_key, lu.user_id
),
identity_first AS (
    SELECT 'company' AS kind, row_key, company_id AS identity_id, first_date
    FROM entity_company_first
    UNION ALL
    SELECT 'user' AS kind, row_key, user_id AS identity_id, first_date
    FROM entity_user_first
    UNION ALL
    SELECT 'project_company' AS kind, '' AS row_key, company_id AS identity_id, first_date
    FROM project_company_first
    UNION ALL
    SELECT 'penetration' AS kind, row_key, user_id AS identity_id, first_date
    FROM penetration_first
)
SELECT kind, row_key, first_date, COUNT(*) AS identities_count
FROM identity_first
GROUP BY kind, row_key, first_date
ORDER BY kind, row_key, first_date
"""


PROJECT_INFO_SQL = """
SELECT
    p.id,
    p.name,
    p.timezone,
    p.analytics_facts_revision,
    p.filtered_analytics_revision
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
    '',
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
        COUNT(*) FILTER (WHERE event_type = 'key_press') AS key_press_count,
        COUNT(*) FILTER (WHERE event_type = 'touch_move') AS touch_move_count,
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
    key_press_count,
    touch_move_count,
    had_click,
    had_scroll,
    had_mouse_move,
    had_key_press,
    had_touch_move,
    first_event_id,
    last_event_id,
    is_analytics_eligible,
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
    rolled.key_press_count,
    rolled.touch_move_count,
    rolled.click_count > 0,
    rolled.scroll_count > 0,
    rolled.mouse_move_count > 0,
    rolled.key_press_count > 0,
    rolled.touch_move_count > 0,
    rolled.first_event_id,
    rolled.last_event_id,
    -- Every visit starts eligible; UPDATE_LOW_CONFIDENCE_VISITS_SQL runs next
    -- and demotes the ones belonging to a completed low-confidence session.
    TRUE,
    NOW(),
    NOW()
FROM rolled
LEFT JOIN pages_productarea pa
    ON pa.project_id = rolled.project_id
   AND pa.slug = rolled.product_area_key
WHERE rolled.visit_start_ts >= %s
  AND rolled.visit_start_ts < %s
"""



# Marks the visits of completed low-confidence anonymous sessions ineligible.
# Runs between INSERT_PAGE_VISITS_SQL and every consumer of pages_pagevisit, so
# a rebuild always recomputes the flag from events rather than inheriting it.
#
# Scopes are rebuilt here as visitor runs split on the session timeout, which is
# how the tracker defines a recording session in the first place.  The obvious
# alternative, grouping by COALESCE(visit_session_id, session_id), is wrong over
# history: recording retention deletes Session rows after 30 days and
# AnalyticsSession.visit_session is SET_NULL, so every fragment of an older
# visit becomes its own scope.  The nightly job rebuilds 180 days, so it would
# re-judge months of already-unlinked data and drop the anonymous opening of
# visits that did identify themselves.  A visitor GUID is never nulled, so this
# grouping keeps meaning the same thing for as long as the events exist.
#
# Facts are read from the widened event window the rebuild passes, not from the
# strict window it writes.  Only sessions under
# analytics_eligibility.LOW_CONFIDENCE_MAX_DURATION_SECONDS can be marked, and a
# window widened by a day on each side contains such a session whole, so a
# session straddling a local midnight cannot be mistaken for a single-page one.
#
# The page count uses distinct (url, rule) pairs rather than a count of visit
# rows, because those rows exist only for the strict window.  The two agree at
# the boundary that matters here; see analytics_eligibility.is_meaningful.
#
# Interaction is the latest click or scroll rather than a count of them, because
# the rule asks whether one landed clear of the session's opening second and the
# latest is the only one that can.  That keeps this a grouped aggregate; ranking
# each event against its own scope would need a third window pass over the same
# rows.
#
# A scope that qualifies holds at most one page and spans under ten seconds, so
# matching its visit by visitor and start time is unambiguous.  A visit whose
# visitor GUID is null joins nothing and stays eligible.
UPDATE_LOW_CONFIDENCE_VISITS_SQL = """
WITH visitor_events AS (
    SELECT
        COALESCE(e.visitor_guid, s.visitor_guid) AS visitor_guid,
        e.id AS event_id,
        e.timestamp,
        e.event_type,
        CASE
            WHEN COALESCE(NULLIF(e.url_normalized, ''), NULLIF(e.url, '')) IS NULL THEN NULL
            ELSE COALESCE(NULLIF(e.url_normalized, ''), NULLIF(e.url, ''))
                 || CHR(31)
                 || COALESCE(e.page_rule_id::text, '')
        END AS page_key,
        NULLIF(COALESCE(NULLIF(e.user_id, ''), NULLIF(s.user_id, '')), '') AS user_id,
        NULLIF(COALESCE(NULLIF(e.company_id, ''), NULLIF(s.company_id, '')), '') AS company_id
    FROM tracker_analyticsevent e
    JOIN tracker_analyticssession s ON s.session_id = e.session_id
    WHERE s.project_id = %s
      AND e.timestamp >= %s
      AND e.timestamp < %s
      AND COALESCE(e.visitor_guid, s.visitor_guid) IS NOT NULL
),
ordered AS (
    SELECT
        visitor_events.*,
        LAG(timestamp) OVER (
            PARTITION BY visitor_guid ORDER BY timestamp, event_id
        ) AS prev_timestamp
    FROM visitor_events
),
marked AS (
    SELECT
        ordered.*,
        CASE
            WHEN prev_timestamp IS NULL THEN 1
            WHEN timestamp - prev_timestamp > (%s::int * INTERVAL '1 second') THEN 1
            ELSE 0
        END AS starts_new_scope
    FROM ordered
),
scoped AS (
    SELECT
        marked.*,
        SUM(starts_new_scope) OVER (
            PARTITION BY visitor_guid
            ORDER BY timestamp, event_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS scope_ordinal
    FROM marked
),
scope_facts AS (
    SELECT
        visitor_guid,
        scope_ordinal,
        MIN(timestamp) AS first_ts,
        MAX(timestamp) AS last_ts,
        MAX(timestamp) FILTER (WHERE event_type = ANY(%s)) AS last_meaningful_ts,
        COUNT(*) FILTER (WHERE user_id IS NOT NULL OR company_id IS NOT NULL) AS identified_events,
        COUNT(DISTINCT page_key) AS page_keys
    FROM scoped
    GROUP BY visitor_guid, scope_ordinal
),
low_confidence AS (
    SELECT visitor_guid, first_ts, last_ts
    FROM scope_facts
    WHERE identified_events = 0
      AND (
        last_meaningful_ts IS NULL
        OR EXTRACT(EPOCH FROM (last_meaningful_ts - first_ts)) < %s
      )
      AND page_keys <= 1
      AND last_ts < %s
      AND EXTRACT(EPOCH FROM (last_ts - first_ts)) < %s
)
UPDATE pages_pagevisit pv
SET is_analytics_eligible = FALSE
FROM low_confidence lc
WHERE pv.project_id = %s
  AND pv.visit_start_ts >= %s
  AND pv.visit_start_ts < %s
  AND pv.visitor_guid = lc.visitor_guid
  AND pv.visit_start_ts >= lc.first_ts
  AND pv.visit_start_ts <= lc.last_ts
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
      AND pv.is_analytics_eligible
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
      AND is_analytics_eligible
)
INSERT INTO pages_pagedailymetric (
    project_id, date, page_rule_id, product_area_id, product_area_key, product_area_name,
    visits_count, engaged_seconds, click_count, scroll_count, mouse_move_count,
    key_press_count, touch_move_count,
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
    COALESCE(SUM(key_press_count), 0),
    COALESCE(SUM(touch_move_count), 0),
    COUNT(*) FILTER (WHERE had_click),
    COUNT(DISTINCT company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> ''),
    COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL AND user_id <> '')
FROM visits
GROUP BY project_id, metric_date, page_rule_id, product_area_key
"""


# Deliberately carries no is_analytics_eligible predicate.  A low-confidence
# session is anonymous by definition, and this statement already drops every
# visit without a company ID, so the predicate would be a no-op here.  Leaving
# it out keeps Companies provably unaffected by the rule rather than affected
# in a way that happens to cancel.  Guarded by
# apps.pages.tests.test_low_confidence_sessions.CompaniesAndUsersUnchangedTests.
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


# No is_analytics_eligible predicate, for the reason given above the company
# rollup: this statement already drops every visit without a user ID.
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
      AND is_analytics_eligible
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


# This one needs the eligibility predicate spelled out.  It used to be able to
# skip it: the rule excluded only sessions with no click at all, so an excluded
# session could not reach a statement that counts clicks.  Once a click inside
# the session's opening second stopped qualifying a session, that stopped being
# true — an excluded bounce can now hold exactly one click, the load-time one,
# and it must not turn up in top actions.
#
# The statement reads events rather than prepared visits, so it filters through
# the visit each click already LEFT JOINs: a click whose visit was marked
# ineligible is dropped, while a click matching no visit row is kept as before.
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
      -- Drop a click whose visit was excluded; an unmatched click stays.
      AND (pv.id IS NULL OR pv.is_analytics_eligible)
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
      AND is_analytics_eligible
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


# Company-attribute variants of the analytical Pages queries are generated from
# the same templates as their unfiltered originals, so the two cannot drift.
#
# Only `pages_pagecompanydailymetric` and `pages_pageuserdailymetric` carry a
# company identity. A filtered variant therefore also has to move its base page
# measures off the project-wide `pages_pagedailymetric` rollup and onto the
# per-company table, which stores the same four measures at a finer grain.
#
# These templates take named parameters because a filtered variant binds one
# extra value; positional lists would have to be rebuilt per variant.

_COHORT_PREDICATE = 'AND {column} = ANY(%(cohort)s)'


def _cohort(column='company_id'):
    return _COHORT_PREDICATE.format(column=column)


_PAGE_MEASURE_SOURCE = 'pages_pagedailymetric'
_PAGE_MEASURE_SOURCE_BY_COMPANY = 'pages_pagecompanydailymetric'


AREA_SUMMARY_TEMPLATE = """
WITH daily AS (
    SELECT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        MIN(product_area_name) AS product_area_name,
        MIN(product_area_id) AS product_area_id,
        COUNT(
            DISTINCT COALESCE(
                page_rule_id::text,
                COALESCE(NULLIF(product_area_key, ''), 'unassigned')
            )
        ) AS page_count,
        SUM(visits_count) AS visits_count,
        SUM(engaged_seconds) AS engaged_seconds,
        SUM(click_count) AS click_count,
        SUM(visits_with_click_count) AS visits_with_click_count
    FROM {measure_source}
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {measure_cohort}
    GROUP BY COALESCE(NULLIF(product_area_key, ''), 'unassigned')
),
companies AS (
    SELECT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        COUNT(DISTINCT company_id) AS companies_count
    FROM pages_pagecompanydailymetric
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {company_cohort}
    GROUP BY COALESCE(NULLIF(product_area_key, ''), 'unassigned')
),
users AS (
    SELECT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        COUNT(DISTINCT user_id) AS users_count
    FROM pages_pageuserdailymetric
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {user_cohort}
    GROUP BY COALESCE(NULLIF(product_area_key, ''), 'unassigned')
),
company_engaged AS (
    SELECT DISTINCT ON (COALESCE(NULLIF(product_area_key, ''), 'unassigned'))
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        company_id AS top_company_id,
        COALESCE(company_name_sample, company_id) AS top_company_name,
        SUM(engaged_seconds) AS company_engaged_seconds,
        SUM(visits_count) AS company_visits_count
    FROM pages_pagecompanydailymetric
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {company_cohort}
    GROUP BY COALESCE(NULLIF(product_area_key, ''), 'unassigned'), company_id, company_name_sample
    ORDER BY COALESCE(NULLIF(product_area_key, ''), 'unassigned'), SUM(engaged_seconds) DESC, SUM(visits_count) DESC, COALESCE(company_name_sample, company_id)
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

AREA_SUMMARY_SQL = AREA_SUMMARY_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE,
    measure_cohort='',
    company_cohort='',
    user_cohort='',
)

AREA_SUMMARY_FILTERED_SQL = AREA_SUMMARY_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE_BY_COMPANY,
    measure_cohort=_cohort(),
    company_cohort=_cohort(),
    user_cohort=_cohort(),
)


PAGE_SUMMARY_TEMPLATE = """
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
    FROM {measure_source} pdm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pdm.page_rule_id
    WHERE pdm.project_id = %(project_id)s
      AND pdm.date >= %(start_date)s
      AND pdm.date <= %(end_date)s
      {measure_cohort}
    GROUP BY COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned'), pdm.page_rule_id
),
companies AS (
    SELECT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        page_rule_id,
        COUNT(DISTINCT company_id) AS companies_count
    FROM pages_pagecompanydailymetric
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {company_cohort}
    GROUP BY COALESCE(NULLIF(product_area_key, ''), 'unassigned'), page_rule_id
),
users AS (
    SELECT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        page_rule_id,
        COUNT(DISTINCT user_id) AS users_count
    FROM pages_pageuserdailymetric
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {user_cohort}
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
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {company_cohort}
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

PAGE_SUMMARY_SQL = PAGE_SUMMARY_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE,
    measure_cohort='',
    company_cohort='',
    user_cohort='',
)

PAGE_SUMMARY_FILTERED_SQL = PAGE_SUMMARY_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE_BY_COMPANY,
    measure_cohort=_cohort('pdm.company_id'),
    company_cohort=_cohort(),
    user_cohort=_cohort(),
)


PAGE_DISPLAY_SUMMARY_TEMPLATE = """
WITH rule_daily AS (
    SELECT
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(pdm.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(pdm.product_area_name), ''),
                    'Unassigned'
                )
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
    FROM {measure_source} pdm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pdm.page_rule_id
    WHERE pdm.project_id = %(project_id)s
      AND pdm.date >= %(start_date)s
      AND pdm.date <= %(end_date)s
      {measure_cohort}
    GROUP BY
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(pdm.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(pdm.product_area_name), ''),
                    'Unassigned'
                )
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
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(pcdm.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(pcdm.product_area_name), ''),
                    'Unassigned'
                )
            )
        ) AS page_display_key,
        pcdm.company_id,
        pcdm.company_name_sample,
        pcdm.engaged_seconds,
        pcdm.visits_count
    FROM pages_pagecompanydailymetric pcdm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pcdm.page_rule_id
    WHERE pcdm.project_id = %(project_id)s
      AND pcdm.date >= %(start_date)s
      AND pcdm.date <= %(end_date)s
      {company_cohort}
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
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(pudm.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(pudm.product_area_name), ''),
                    'Unassigned'
                )
            )
        ) AS page_display_key,
        COUNT(DISTINCT pudm.user_id)
            FILTER (WHERE pudm.user_id IS NOT NULL AND BTRIM(pudm.user_id) <> '') AS users_count
    FROM pages_pageuserdailymetric pudm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pudm.page_rule_id
    WHERE pudm.project_id = %(project_id)s
      AND pudm.date >= %(start_date)s
      AND pudm.date <= %(end_date)s
      {user_cohort}
    GROUP BY
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(pudm.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(pudm.product_area_name), ''),
                    'Unassigned'
                )
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

PAGE_DISPLAY_SUMMARY_SQL = PAGE_DISPLAY_SUMMARY_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE,
    measure_cohort='',
    company_cohort='',
    user_cohort='',
)

PAGE_DISPLAY_SUMMARY_FILTERED_SQL = PAGE_DISPLAY_SUMMARY_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE_BY_COMPANY,
    measure_cohort=_cohort('pdm.company_id'),
    company_cohort=_cohort('pcdm.company_id'),
    user_cohort=_cohort('pudm.company_id'),
)


PROJECT_DISTINCT_COUNTS_TEMPLATE = """
SELECT
    (
        SELECT COUNT(DISTINCT company_id)
        FROM pages_pagecompanydailymetric
        WHERE project_id = %(project_id)s
          AND date >= %(start_date)s
          AND date <= %(end_date)s
          {company_cohort}
    ) AS active_companies_count,
    (
        SELECT COUNT(DISTINCT user_id)
        FROM pages_pageuserdailymetric
        WHERE project_id = %(project_id)s
          AND date >= %(start_date)s
          AND date <= %(end_date)s
          {user_cohort}
    ) AS active_users_count
"""

PROJECT_DISTINCT_COUNTS_SQL = PROJECT_DISTINCT_COUNTS_TEMPLATE.format(
    company_cohort='',
    user_cohort='',
)

PROJECT_DISTINCT_COUNTS_FILTERED_SQL = PROJECT_DISTINCT_COUNTS_TEMPLATE.format(
    company_cohort=_cohort(),
    user_cohort=_cohort(),
)


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


# A denominator only needs its cohort predicate on the company CTE: the user
# join already keys on company_id, so restricting the adopted companies
# restricts their users along with them.

PENETRATION_DENOMINATOR_TEMPLATE = """
WITH area_companies AS (
    SELECT DISTINCT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        company_id
    FROM pages_pagecompanydailymetric
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {company_cohort}
),
area_users AS (
    SELECT
        area_companies.product_area_key,
        COUNT(DISTINCT users.user_id) AS active_users_in_adopted_companies
    FROM area_companies
    JOIN pages_pageuserdailymetric users
      ON users.project_id = %(project_id)s
     AND users.date >= %(start_date)s
     AND users.date <= %(end_date)s
     AND users.company_id = area_companies.company_id
    GROUP BY area_companies.product_area_key
)
SELECT * FROM area_users
"""

PENETRATION_DENOMINATOR_SQL = PENETRATION_DENOMINATOR_TEMPLATE.format(company_cohort='')

PENETRATION_DENOMINATOR_FILTERED_SQL = PENETRATION_DENOMINATOR_TEMPLATE.format(
    company_cohort=_cohort(),
)


PAGE_PENETRATION_DENOMINATOR_TEMPLATE = """
WITH page_companies AS (
    SELECT DISTINCT
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        page_rule_id,
        company_id
    FROM pages_pagecompanydailymetric
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {company_cohort}
),
page_users AS (
    SELECT
        page_companies.product_area_key,
        page_companies.page_rule_id,
        COUNT(DISTINCT users.user_id) AS active_users_in_adopted_companies
    FROM page_companies
    JOIN pages_pageuserdailymetric users
      ON users.project_id = %(project_id)s
     AND users.date >= %(start_date)s
     AND users.date <= %(end_date)s
     AND COALESCE(NULLIF(users.product_area_key, ''), 'unassigned') = page_companies.product_area_key
     AND users.page_rule_id IS NOT DISTINCT FROM page_companies.page_rule_id
     AND users.company_id = page_companies.company_id
    GROUP BY page_companies.product_area_key, page_companies.page_rule_id
)
SELECT * FROM page_users
"""

PAGE_PENETRATION_DENOMINATOR_SQL = PAGE_PENETRATION_DENOMINATOR_TEMPLATE.format(
    company_cohort='',
)

PAGE_PENETRATION_DENOMINATOR_FILTERED_SQL = PAGE_PENETRATION_DENOMINATOR_TEMPLATE.format(
    company_cohort=_cohort(),
)


PAGE_DISPLAY_PENETRATION_DENOMINATOR_TEMPLATE = """
WITH page_companies AS (
    SELECT DISTINCT
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(companies.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(companies.product_area_name), ''),
                    'Unassigned'
                )
            )
        ) AS page_display_key,
        companies.company_id
    FROM pages_pagecompanydailymetric companies
    LEFT JOIN tracker_projectpagerule pr ON pr.id = companies.page_rule_id
    WHERE companies.project_id = %(project_id)s
      AND companies.date >= %(start_date)s
      AND companies.date <= %(end_date)s
      AND companies.company_id IS NOT NULL
      AND BTRIM(companies.company_id) <> ''
      {company_cohort}
),
display_users AS (
    SELECT DISTINCT
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(users.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(users.product_area_name), ''),
                    'Unassigned'
                )
            )
        ) AS page_display_key,
        users.company_id,
        users.user_id
    FROM pages_pageuserdailymetric users
    LEFT JOIN tracker_projectpagerule pr ON pr.id = users.page_rule_id
    WHERE users.project_id = %(project_id)s
      AND users.date >= %(start_date)s
      AND users.date <= %(end_date)s
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

PAGE_DISPLAY_PENETRATION_DENOMINATOR_SQL = (
    PAGE_DISPLAY_PENETRATION_DENOMINATOR_TEMPLATE.format(company_cohort='')
)

PAGE_DISPLAY_PENETRATION_DENOMINATOR_FILTERED_SQL = (
    PAGE_DISPLAY_PENETRATION_DENOMINATOR_TEMPLATE.format(
        company_cohort=_cohort('companies.company_id'),
    )
)


# `pages_projectdailymetric` stores project-wide daily actives, which are the
# wrong denominator once a cohort is selected. A filtered variant swaps that
# table for an equivalent per-day rollup restricted to the cohort.
_COHORT_PROJECT_DAILY = """(
    SELECT
        company_days.project_id,
        company_days.date,
        company_days.active_companies_count,
        COALESCE(user_days.active_users_count, 0) AS active_users_count
    FROM (
        SELECT project_id, date, COUNT(DISTINCT company_id) AS active_companies_count
        FROM pages_pagecompanydailymetric
        WHERE project_id = %(project_id)s
          AND date >= %(start_date)s
          AND date <= %(end_date)s
          AND company_id = ANY(%(cohort)s)
        GROUP BY project_id, date
    ) AS company_days
    LEFT JOIN (
        SELECT project_id, date, COUNT(DISTINCT user_id) AS active_users_count
        FROM pages_pageuserdailymetric
        WHERE project_id = %(project_id)s
          AND date >= %(start_date)s
          AND date <= %(end_date)s
          AND company_id = ANY(%(cohort)s)
        GROUP BY project_id, date
    ) AS user_days
      ON user_days.project_id = company_days.project_id
     AND user_days.date = company_days.date
)"""

_PROJECT_DAILY_SOURCE = 'pages_projectdailymetric'


DAILY_AREA_METRICS_TEMPLATE = """
WITH daily AS (
    SELECT
        pdm.date,
        COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned') AS product_area_key,
        COALESCE(NULLIF(MIN(pdm.product_area_name), ''), 'Unassigned') AS product_area_name,
        SUM(pdm.visits_count) AS visits_count,
        SUM(pdm.engaged_seconds) AS engaged_seconds,
        SUM(pdm.click_count) AS click_count,
        SUM(pdm.visits_with_click_count) AS visits_with_click_count
    FROM {measure_source} pdm
    WHERE pdm.project_id = %(project_id)s
      AND pdm.date >= %(start_date)s
      AND pdm.date <= %(end_date)s
      {measure_cohort}
    GROUP BY pdm.date, COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned')
),
companies AS (
    SELECT
        date,
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        COUNT(DISTINCT company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> '') AS companies_count_daily
    FROM pages_pagecompanydailymetric
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {company_cohort}
    GROUP BY date, COALESCE(NULLIF(product_area_key, ''), 'unassigned')
),
users AS (
    SELECT
        date,
        COALESCE(NULLIF(product_area_key, ''), 'unassigned') AS product_area_key,
        COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL AND user_id <> '') AS users_count_daily
    FROM pages_pageuserdailymetric
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {user_cohort}
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
LEFT JOIN {project_daily_source} prdm
  ON prdm.project_id = %(project_id)s
 AND prdm.date = daily.date
ORDER BY daily.date, daily.product_area_key
"""

DAILY_AREA_METRICS_SQL = DAILY_AREA_METRICS_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE,
    measure_cohort='',
    company_cohort='',
    user_cohort='',
    project_daily_source=_PROJECT_DAILY_SOURCE,
)

DAILY_AREA_METRICS_FILTERED_SQL = DAILY_AREA_METRICS_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE_BY_COMPANY,
    measure_cohort=_cohort('pdm.company_id'),
    company_cohort=_cohort(),
    user_cohort=_cohort(),
    project_daily_source=_COHORT_PROJECT_DAILY,
)


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
WHERE pdm.project_id = %(project_id)s
  AND pdm.date >= %(start_date)s
  AND pdm.date <= %(end_date)s
GROUP BY pdm.date, COALESCE(NULLIF(pdm.product_area_key, ''), 'unassigned'), pdm.page_rule_id
ORDER BY pdm.date, product_area_key, pdm.page_rule_id
"""


# Unlike its siblings this one cannot be produced by swapping a source table.
# `companies_count_daily` and `users_count_daily` are stored columns on
# `pages_pagedailymetric` that the per-company table does not carry, so the
# filtered form recomputes both by counting distinct identities.
DAILY_PAGE_METRICS_FILTERED_SQL = """
WITH daily AS (
    SELECT
        pcdm.date,
        COALESCE(NULLIF(pcdm.product_area_key, ''), 'unassigned') AS product_area_key,
        MIN(pcdm.product_area_name) AS product_area_name,
        pcdm.page_rule_id,
        SUM(pcdm.visits_count) AS visits_count,
        SUM(pcdm.engaged_seconds) AS engaged_seconds,
        SUM(pcdm.click_count) AS click_count,
        SUM(pcdm.visits_with_click_count) AS visits_with_click_count,
        COUNT(DISTINCT pcdm.company_id) AS companies_count_daily
    FROM pages_pagecompanydailymetric pcdm
    WHERE pcdm.project_id = %(project_id)s
      AND pcdm.date >= %(start_date)s
      AND pcdm.date <= %(end_date)s
      AND pcdm.company_id = ANY(%(cohort)s)
    GROUP BY pcdm.date, COALESCE(NULLIF(pcdm.product_area_key, ''), 'unassigned'), pcdm.page_rule_id
),
page_users AS (
    SELECT
        pudm.date,
        COALESCE(NULLIF(pudm.product_area_key, ''), 'unassigned') AS product_area_key,
        pudm.page_rule_id,
        COUNT(DISTINCT pudm.user_id) AS users_count_daily
    FROM pages_pageuserdailymetric pudm
    WHERE pudm.project_id = %(project_id)s
      AND pudm.date >= %(start_date)s
      AND pudm.date <= %(end_date)s
      AND pudm.company_id = ANY(%(cohort)s)
    GROUP BY pudm.date, COALESCE(NULLIF(pudm.product_area_key, ''), 'unassigned'), pudm.page_rule_id
)
SELECT
    daily.date,
    daily.product_area_key,
    daily.product_area_name,
    daily.page_rule_id,
    daily.visits_count,
    daily.engaged_seconds,
    daily.click_count,
    daily.visits_with_click_count,
    daily.companies_count_daily,
    COALESCE(page_users.users_count_daily, 0) AS users_count_daily,
    COALESCE(prdm.active_companies_count, 0) AS active_companies_count,
    COALESCE(prdm.active_users_count, 0) AS active_users_count
FROM daily
LEFT JOIN page_users
  ON page_users.date = daily.date
 AND page_users.product_area_key = daily.product_area_key
 AND page_users.page_rule_id IS NOT DISTINCT FROM daily.page_rule_id
LEFT JOIN {project_daily_source} prdm
  ON prdm.project_id = %(project_id)s
 AND prdm.date = daily.date
ORDER BY daily.date, daily.product_area_key, daily.page_rule_id
""".format(project_daily_source=_COHORT_PROJECT_DAILY)


DAILY_PAGE_DISPLAY_METRICS_TEMPLATE = """
WITH daily AS (
    SELECT
        pdm.date,
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(pdm.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(pdm.product_area_name), ''),
                    'Unassigned'
                )
            )
        ) AS page_display_key,
        SUM(pdm.visits_count) AS visits_count,
        SUM(pdm.engaged_seconds) AS engaged_seconds,
        SUM(pdm.click_count) AS click_count,
        SUM(pdm.visits_with_click_count) AS visits_with_click_count
    FROM {measure_source} pdm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pdm.page_rule_id
    WHERE pdm.project_id = %(project_id)s
      AND pdm.date >= %(start_date)s
      AND pdm.date <= %(end_date)s
      {measure_cohort}
    GROUP BY
        pdm.date,
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(pdm.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(pdm.product_area_name), ''),
                    'Unassigned'
                )
            )
        )
),
companies AS (
    SELECT
        companies.date,
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(companies.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(companies.product_area_name), ''),
                    'Unassigned'
                )
            )
        ) AS page_display_key,
        COUNT(DISTINCT companies.company_id)
            FILTER (WHERE companies.company_id IS NOT NULL AND BTRIM(companies.company_id) <> '') AS companies_count_daily
    FROM pages_pagecompanydailymetric companies
    LEFT JOIN tracker_projectpagerule pr ON pr.id = companies.page_rule_id
    WHERE companies.project_id = %(project_id)s
      AND companies.date >= %(start_date)s
      AND companies.date <= %(end_date)s
      {company_cohort}
    GROUP BY
        companies.date,
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(companies.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(companies.product_area_name), ''),
                    'Unassigned'
                )
            )
        )
),
users AS (
    SELECT
        users.date,
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(users.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(users.product_area_name), ''),
                    'Unassigned'
                )
            )
        ) AS page_display_key,
        COUNT(DISTINCT users.user_id)
            FILTER (WHERE users.user_id IS NOT NULL AND BTRIM(users.user_id) <> '') AS users_count_daily
    FROM pages_pageuserdailymetric users
    LEFT JOIN tracker_projectpagerule pr ON pr.id = users.page_rule_id
    WHERE users.project_id = %(project_id)s
      AND users.date >= %(start_date)s
      AND users.date <= %(end_date)s
      {user_cohort}
    GROUP BY
        users.date,
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(users.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(
                COALESCE(
                    NULLIF(BTRIM(pr.page_name), ''),
                    NULLIF(BTRIM(users.product_area_name), ''),
                    'Unassigned'
                )
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
LEFT JOIN {project_daily_source} prdm
  ON prdm.project_id = %(project_id)s
 AND prdm.date = daily.date
ORDER BY daily.date, daily.page_display_key
"""

DAILY_PAGE_DISPLAY_METRICS_SQL = DAILY_PAGE_DISPLAY_METRICS_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE,
    measure_cohort='',
    company_cohort='',
    user_cohort='',
    project_daily_source=_PROJECT_DAILY_SOURCE,
)

DAILY_PAGE_DISPLAY_METRICS_FILTERED_SQL = DAILY_PAGE_DISPLAY_METRICS_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE_BY_COMPANY,
    measure_cohort=_cohort('pdm.company_id'),
    company_cohort=_cohort('companies.company_id'),
    user_cohort=_cohort('users.company_id'),
    project_daily_source=_COHORT_PROJECT_DAILY,
)


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
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(metrics.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(BTRIM(COALESCE(
                NULLIF(BTRIM(rule.page_name), ''),
                NULLIF(BTRIM(metrics.page_label), ''),
                metrics.url_normalized
            )))
        ) AS page_key,
        COALESCE(NULLIF(BTRIM(metrics.product_area_key), ''), 'unassigned') AS product_area_key,
        COALESCE(NULLIF(BTRIM(rule.product_area), ''), NULLIF(BTRIM(metrics.product_area_name), ''), 'Unassigned') AS product_area_name,
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
        MIN(product_area_key) AS product_area_key,
        MIN(product_area_name) AS product_area_name,
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
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(metrics.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(BTRIM(COALESCE(
                NULLIF(BTRIM(rule.page_name), ''),
                NULLIF(BTRIM(metrics.page_label), ''),
                metrics.url_normalized
            )))
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
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(actions.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(BTRIM(COALESCE(
                NULLIF(BTRIM(rule.page_name), ''),
                actions.url_normalized
            )))
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
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(actions.product_area_key), ''), 'unassigned')),
            '::',
            LOWER(BTRIM(COALESCE(
                NULLIF(BTRIM(rule.page_name), ''),
                actions.url_normalized
            )))
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
    top_pages.product_area_key,
    top_pages.product_area_name,
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


# `pages_rawpagedailymetric` and `pages_rawpageactiondailymetric` are keyed by
# URL and carry no company identity, so a cohort cannot be expressed against
# them at all. The filtered variant therefore takes its pages from the
# per-company daily table and re-derives the click actions from the source
# events, the same way ingestion builds the raw action rollup. The partial
# `trk_anae_click_comp_ts_idx` index keeps that event scan bounded.
#
# Pages are keyed by `page_rule_id` rather than by the composed display string,
# so the current window, the previous window and the events all agree on
# identity without depending on matching text expressions.
TOP_ACTIONS_FILTERED_SQL = """
WITH current_pages AS (
    SELECT
        pcdm.page_rule_id,
        COALESCE(NULLIF(BTRIM(pcdm.product_area_key), ''), 'unassigned') AS product_area_key,
        COALESCE(
            NULLIF(BTRIM(pr.product_area), ''),
            NULLIF(BTRIM(pcdm.product_area_name), ''),
            'Unassigned'
        ) AS product_area_name,
        COALESCE(
            NULLIF(BTRIM(pr.page_name), ''),
            NULLIF(BTRIM(pcdm.product_area_name), ''),
            'Unassigned'
        ) AS page_label,
        SUM(pcdm.visits_count) AS visits_count,
        SUM(pcdm.engaged_seconds) AS engaged_seconds
    FROM pages_pagecompanydailymetric pcdm
    LEFT JOIN tracker_projectpagerule pr ON pr.id = pcdm.page_rule_id
    WHERE pcdm.project_id = %(project_id)s
      AND pcdm.date >= %(start_date)s
      AND pcdm.date <= %(end_date)s
      AND pcdm.company_id = ANY(%(cohort)s)
    GROUP BY
        pcdm.page_rule_id,
        COALESCE(NULLIF(BTRIM(pcdm.product_area_key), ''), 'unassigned'),
        COALESCE(
            NULLIF(BTRIM(pr.product_area), ''),
            NULLIF(BTRIM(pcdm.product_area_name), ''),
            'Unassigned'
        ),
        COALESCE(
            NULLIF(BTRIM(pr.page_name), ''),
            NULLIF(BTRIM(pcdm.product_area_name), ''),
            'Unassigned'
        )
),
top_pages AS (
    SELECT
        current_pages.*,
        CONCAT(LOWER(product_area_key), '::', LOWER(page_label)) AS page_key
    FROM current_pages
    ORDER BY visits_count DESC, page_label
    LIMIT 10
),
previous_pages AS (
    SELECT
        pcdm.page_rule_id,
        SUM(pcdm.visits_count) AS previous_visits_count
    FROM pages_pagecompanydailymetric pcdm
    WHERE pcdm.project_id = %(project_id)s
      AND pcdm.date >= %(previous_start_date)s
      AND pcdm.date <= %(previous_end_date)s
      AND pcdm.company_id = ANY(%(cohort)s)
    GROUP BY pcdm.page_rule_id
),
click_events AS (
    SELECT
        (e.timestamp AT TIME ZONE %(timezone)s)::date AS event_date,
        e.page_rule_id,
        e.element_key,
        NULLIF(COALESCE(NULLIF(e.user_id, ''), NULLIF(s.user_id, '')), '') AS user_id,
        NULLIF(COALESCE(NULLIF(e.company_id, ''), NULLIF(s.company_id, '')), '') AS company_id,
        pv.id AS visit_id
    FROM tracker_analyticsevent e
    JOIN tracker_analyticssession s ON s.session_id = e.session_id
    LEFT JOIN pages_pagevisit pv
      ON pv.project_id = s.project_id
     AND pv.session_id = e.session_id
     AND pv.url_normalized = COALESCE(NULLIF(e.url_normalized, ''), NULLIF(e.url, ''))
     AND pv.visit_start_ts <= e.timestamp
     AND pv.visit_end_ts >= e.timestamp
    WHERE s.project_id = %(project_id)s
      AND e.event_type = 'click'
      AND e.element_key IS NOT NULL
      AND e.element_key <> ''
      AND (e.timestamp AT TIME ZONE %(timezone)s)::date >= %(previous_start_date)s
      AND (e.timestamp AT TIME ZONE %(timezone)s)::date <= %(end_date)s
      AND COALESCE(NULLIF(e.company_id, ''), NULLIF(s.company_id, '')) = ANY(%(cohort)s)
),
actions AS (
    SELECT
        click_events.page_rule_id,
        click_events.element_key,
        COUNT(*) AS clicks_count,
        COUNT(DISTINCT click_events.visit_id)
            FILTER (WHERE click_events.visit_id IS NOT NULL) AS visits_with_action_count,
        COUNT(DISTINCT click_events.user_id)
            FILTER (WHERE click_events.user_id IS NOT NULL) AS users_count_daily,
        COUNT(DISTINCT click_events.company_id)
            FILTER (WHERE click_events.company_id IS NOT NULL) AS companies_count_daily,
        ROW_NUMBER() OVER (
            PARTITION BY click_events.page_rule_id
            ORDER BY COUNT(*) DESC, click_events.element_key
        ) AS action_rank
    FROM click_events
    JOIN top_pages ON top_pages.page_rule_id IS NOT DISTINCT FROM click_events.page_rule_id
    WHERE click_events.event_date >= %(start_date)s
    GROUP BY click_events.page_rule_id, click_events.element_key
),
previous_actions AS (
    SELECT
        click_events.page_rule_id,
        click_events.element_key,
        COUNT(*) AS previous_clicks_count,
        COUNT(DISTINCT click_events.visit_id)
            FILTER (WHERE click_events.visit_id IS NOT NULL) AS previous_visits_with_action_count
    FROM click_events
    JOIN top_pages ON top_pages.page_rule_id IS NOT DISTINCT FROM click_events.page_rule_id
    WHERE click_events.event_date <= %(previous_end_date)s
    GROUP BY click_events.page_rule_id, click_events.element_key
)
SELECT
    top_pages.page_key,
    top_pages.product_area_key,
    top_pages.product_area_name,
    '' AS url_normalized,
    top_pages.page_rule_id,
    top_pages.product_area_name AS page_group,
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
  ON actions.page_rule_id IS NOT DISTINCT FROM top_pages.page_rule_id
 AND actions.action_rank <= 5
LEFT JOIN previous_pages
  ON previous_pages.page_rule_id IS NOT DISTINCT FROM top_pages.page_rule_id
LEFT JOIN previous_actions
  ON previous_actions.page_rule_id IS NOT DISTINCT FROM actions.page_rule_id
 AND previous_actions.element_key = actions.element_key
ORDER BY top_pages.visits_count DESC, top_pages.page_label, actions.action_rank
"""


SANKEY_TEMPLATE = """
WITH normalized AS (
    SELECT
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(from_product_area_key), ''), 'unassigned')),
            '::',
            LOWER(BTRIM(COALESCE(
                NULLIF(BTRIM(from_rule.page_name), ''),
                NULLIF(BTRIM(from_url_normalized), ''),
                NULLIF(BTRIM(from_product_area_name), ''),
                'Unassigned'
            )))
        ) AS from_page_key,
        CONCAT(
            LOWER(COALESCE(NULLIF(BTRIM(to_product_area_key), ''), 'unassigned')),
            '::',
            LOWER(BTRIM(COALESCE(
                NULLIF(BTRIM(to_rule.page_name), ''),
                NULLIF(BTRIM(to_url_normalized), ''),
                NULLIF(BTRIM(to_product_area_name), ''),
                'Unassigned'
            )))
        ) AS to_page_key,
        COALESCE(NULLIF(BTRIM(from_rule.page_name), ''), NULLIF(BTRIM(from_url_normalized), ''), NULLIF(BTRIM(from_product_area_name), ''), 'Unassigned') AS from_page_name,
        COALESCE(NULLIF(BTRIM(to_rule.page_name), ''), NULLIF(BTRIM(to_url_normalized), ''), NULLIF(BTRIM(to_product_area_name), ''), 'Unassigned') AS to_page_name,
        from_product_area_key,
        from_product_area_name,
        to_product_area_key,
        to_product_area_name,
        session_id,
        company_id
    FROM pages_pagetransition transitions
    LEFT JOIN tracker_projectpagerule from_rule ON from_rule.id = transitions.from_page_rule_id
    LEFT JOIN tracker_projectpagerule to_rule ON to_rule.id = transitions.to_page_rule_id
    WHERE transitions.project_id = %(project_id)s
      AND (transition_ts AT TIME ZONE %(timezone)s)::date >= %(start_date)s
      AND (transition_ts AT TIME ZONE %(timezone)s)::date <= %(end_date)s
      {company_cohort}
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

SANKEY_SQL = SANKEY_TEMPLATE.format(company_cohort='')

SANKEY_FILTERED_SQL = SANKEY_TEMPLATE.format(
    company_cohort=_cohort('transitions.company_id'),
)


TWO_WAY_MOVEMENT_TEMPLATE = """
WITH filtered AS (
    SELECT
        transitions.from_page_rule_id,
        transitions.to_page_rule_id,
        session_id,
        company_id,
        user_id
    FROM pages_pagetransition transitions
    WHERE transitions.project_id = %(project_id)s
      AND (transition_ts AT TIME ZONE %(timezone)s)::date >= %(start_date)s
      AND (transition_ts AT TIME ZONE %(timezone)s)::date <= %(end_date)s
      {company_cohort}
      AND from_page_rule_id IS NOT NULL
      AND to_page_rule_id IS NOT NULL
      AND from_page_rule_id <> to_page_rule_id
),
pair_base AS (
    SELECT
        LEAST(from_page_rule_id, to_page_rule_id) AS page_low_id,
        GREATEST(from_page_rule_id, to_page_rule_id) AS page_high_id,
        COUNT(*) FILTER (WHERE from_page_rule_id < to_page_rule_id) AS low_to_high,
        COUNT(*) FILTER (WHERE from_page_rule_id > to_page_rule_id) AS high_to_low,
        COUNT(DISTINCT session_id) AS sessions_count,
        COUNT(DISTINCT company_id) FILTER (WHERE company_id IS NOT NULL AND company_id <> '') AS companies_count,
        COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL AND user_id <> '') AS users_count
    FROM filtered
    GROUP BY 1, 2
),
scored AS (
    SELECT
        page_low_id,
        page_high_id,
        low_to_high,
        high_to_low,
        low_to_high + high_to_low AS total_transitions,
        2 * LEAST(low_to_high, high_to_low) AS reciprocal_volume,
        100.0 * (2 * LEAST(low_to_high, high_to_low)) / NULLIF(low_to_high + high_to_low, 0) AS reciprocity_pct,
        1.0 * LEAST(low_to_high, high_to_low) / NULLIF(GREATEST(low_to_high, high_to_low), 0) AS direction_balance,
        sessions_count,
        companies_count,
        users_count
    FROM pair_base
    WHERE low_to_high > 0 AND high_to_low > 0
)
SELECT
    scored.*,
    COALESCE(NULLIF(BTRIM(low_rule.page_name), ''), 'Unnamed page') AS page_low_name,
    COALESCE(NULLIF(BTRIM(high_rule.page_name), ''), 'Unnamed page') AS page_high_name,
    COALESCE(NULLIF(BTRIM(low_rule.product_area), ''), 'Unassigned') AS page_low_product_area_name,
    COALESCE(NULLIF(BTRIM(high_rule.product_area), ''), 'Unassigned') AS page_high_product_area_name
FROM scored
JOIN tracker_projectpagerule low_rule ON low_rule.id = scored.page_low_id
JOIN tracker_projectpagerule high_rule ON high_rule.id = scored.page_high_id
ORDER BY reciprocal_volume DESC, total_transitions DESC
LIMIT 10
"""

TWO_WAY_MOVEMENT_SQL = TWO_WAY_MOVEMENT_TEMPLATE.format(company_cohort='')

TWO_WAY_MOVEMENT_FILTERED_SQL = TWO_WAY_MOVEMENT_TEMPLATE.format(
    company_cohort=_cohort('transitions.company_id'),
)


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


SCATTER_TEMPLATE = """
WITH top_areas AS (
    SELECT product_area_key, MIN(product_area_name) AS product_area_name, SUM(engaged_seconds) AS engaged_seconds
    FROM {measure_source}
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {measure_cohort}
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
    WHERE project_id = %(project_id)s
      AND date >= %(start_date)s
      AND date <= %(end_date)s
      {company_cohort}
    GROUP BY product_area_key, company_id
),
company_users AS (
    SELECT product_area_key, company_id, AVG(active_users * 1.0) AS active_users
    FROM (
        SELECT product_area_key, company_id, date, COUNT(DISTINCT user_id) AS active_users
        FROM pages_pageuserdailymetric
        WHERE project_id = %(project_id)s
          AND date >= %(start_date)s
          AND date <= %(end_date)s
          {user_cohort}
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

SCATTER_SQL = SCATTER_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE,
    measure_cohort='',
    company_cohort='',
    user_cohort='',
)

SCATTER_FILTERED_SQL = SCATTER_TEMPLATE.format(
    measure_source=_PAGE_MEASURE_SOURCE_BY_COMPANY,
    measure_cohort=_cohort(),
    company_cohort=_cohort(),
    user_cohort=_cohort(),
)


UPSERT_OVERVIEW_CACHE_SQL = """
INSERT INTO pages_pagesoverviewcache (
    project_id,
    range_key,
    start_date,
    end_date,
    filters_hash,
    payload_json,
    payload_compressed,
    source_max_event_ts,
    generated_at,
    expires_at,
    is_stale
)
VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, false)
ON CONFLICT (project_id, range_key, filters_hash)
DO UPDATE SET
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date,
    payload_json = EXCLUDED.payload_json,
    payload_compressed = EXCLUDED.payload_compressed,
    source_max_event_ts = EXCLUDED.source_max_event_ts,
    generated_at = EXCLUDED.generated_at,
    expires_at = EXCLUDED.expires_at,
    is_stale = false
"""


FETCH_OVERVIEW_CACHE_SQL = """
SELECT
    CASE
        WHEN payload_compressed IS NULL THEN payload_json
        ELSE NULL
    END AS payload_json,
    payload_compressed,
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


FETCH_OVERVIEW_CACHE_JSON_FALLBACK_SQL = """
SELECT
    payload_json
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
    payload_json::text AS payload_json_text,
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
    payload_json::text AS payload_json_text,
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


FETCH_USERS_OVERVIEW_CLIENT_CACHE_SQL = """
SELECT
    (payload_json - 'users')::text AS payload_json_text,
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


# Endpoints that render from SQL rather than from the payload still have to
# decide whether a variant may be served. These return only what that decision
# needs, so a table page or a selector lookup never transfers a payload.
OVERVIEW_VARIANT_METADATA_TEMPLATE = """
SELECT
    payload_json ->> 'schema_version' AS schema_version,
    payload_json -> 'freshness' ->> 'filtered_analytics_revision'
        AS filtered_analytics_revision,
    payload_json -> 'freshness' ->> 'analytics_facts_revision'
        AS analytics_facts_revision,
    generated_at,
    expires_at,
    is_stale,
    start_date,
    end_date
FROM {table}
WHERE project_id = %s
  AND range_key = %s
  AND filters_hash = %s
LIMIT 1
"""

FETCH_PAGES_OVERVIEW_METADATA_SQL = OVERVIEW_VARIANT_METADATA_TEMPLATE.format(
    table='pages_pagesoverviewcache',
)
FETCH_COMPANIES_OVERVIEW_METADATA_SQL = OVERVIEW_VARIANT_METADATA_TEMPLATE.format(
    table='pages_companiesoverviewcache',
)
FETCH_USERS_OVERVIEW_METADATA_SQL = OVERVIEW_VARIANT_METADATA_TEMPLATE.format(
    table='pages_usersoverviewcache',
)


# The user selector runs on every keystroke and returns at most a few dozen
# rows, so it matches and orders inside the payload rather than transferring the
# whole `users` array to filter it in Python.
FETCH_USERS_OVERVIEW_SELECTOR_SQL = """
WITH cached AS (
    SELECT payload_json
    FROM pages_usersoverviewcache
    WHERE project_id = %(project_id)s
      AND range_key = %(range_key)s
      AND filters_hash = %(filters_hash)s
    LIMIT 1
),
users AS MATERIALIZED (
    SELECT item.user_row
    FROM cached
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(cached.payload_json -> 'users') = 'array'
                THEN cached.payload_json -> 'users'
            ELSE '[]'::jsonb
        END
    ) AS item(user_row)
),
identified AS (
    SELECT
        user_row,
        COALESCE(
            NULLIF(BTRIM(user_row ->> 'id'), ''),
            NULLIF(BTRIM(user_row ->> 'userId'), '')
        ) AS user_id
    FROM users
),
matched AS (
    SELECT
        user_id,
        COALESCE(NULLIF(user_row ->> 'name', ''), user_id) AS name,
        COALESCE(user_row ->> 'email', '') AS email,
        COALESCE(user_row ->> 'companyId', '') AS company_id,
        COALESCE(NULLIF(user_row ->> 'companyName', ''), user_row ->> 'company', '') AS company_name,
        COALESCE(user_row ->> 'role', '') AS role,
        COALESCE(user_row ->> 'seatType', '') AS seat_type,
        COALESCE(user_row ->> 'status', '') AS status,
        CASE WHEN jsonb_typeof(user_row -> 'engagedSeconds') = 'number'
             THEN (user_row ->> 'engagedSeconds')::numeric ELSE 0 END AS engaged_seconds,
        CASE WHEN jsonb_typeof(user_row -> 'visitsCount') = 'number'
             THEN (user_row ->> 'visitsCount')::numeric ELSE 0 END AS visits_count,
        CASE WHEN jsonb_typeof(user_row -> 'featuresCount') = 'number'
             THEN (user_row ->> 'featuresCount')::numeric
             WHEN jsonb_typeof(user_row -> 'topFeatures') = 'array'
             THEN jsonb_array_length(user_row -> 'topFeatures')
             ELSE 0 END AS features_count,
        COALESCE(user_row ->> 'lastActive', '') AS last_active,
        CASE WHEN jsonb_typeof(user_row -> 'lastActiveSort') = 'number'
             THEN (user_row ->> 'lastActiveSort')::numeric ELSE 0 END AS last_active_sort
    FROM identified
    WHERE user_id IS NOT NULL
      AND (
          %(query)s = ''
          OR POSITION(%(query)s IN LOWER(CONCAT_WS(
              ' ',
              user_row ->> 'name',
              user_row ->> 'email',
              COALESCE(NULLIF(user_row ->> 'companyName', ''), user_row ->> 'company'),
              user_row ->> 'role',
              user_row ->> 'seatType',
              user_id
          ))) > 0
      )
),
counted AS (
    SELECT COUNT(*)::integer AS total FROM matched
),
ordered AS (
    SELECT
        matched.*,
        ROW_NUMBER() OVER (
            ORDER BY
                CASE WHEN %(alphabetical)s THEN LOWER(name) END ASC,
                CASE WHEN NOT %(alphabetical)s AND %(query)s <> '' THEN LOWER(company_name) END ASC,
                CASE WHEN NOT %(alphabetical)s AND %(query)s <> '' THEN LOWER(name) END ASC,
                CASE WHEN NOT %(alphabetical)s AND %(query)s = '' THEN last_active_sort END ASC,
                CASE WHEN NOT %(alphabetical)s AND %(query)s = '' THEN -engaged_seconds END ASC,
                CASE WHEN NOT %(alphabetical)s AND %(query)s = '' THEN LOWER(name) END ASC,
                user_id ASC
        ) AS selector_position
    FROM matched
)
SELECT
    COALESCE((
        SELECT jsonb_agg(
            to_jsonb(ordered) - 'selector_position'
            ORDER BY ordered.selector_position
        )
        FROM ordered
        WHERE ordered.selector_position <= %(limit)s
    ), '[]'::jsonb) AS rows,
    counted.total
FROM counted
"""


FETCH_USERS_OVERVIEW_TABLE_PAGE_SQL = """
WITH cached AS (
    SELECT payload_json
    FROM pages_usersoverviewcache
    WHERE project_id = %s
      AND range_key = %s
      AND filters_hash = %s
    LIMIT 1
),
users AS MATERIALIZED (
    SELECT item.user_row
    FROM cached
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(cached.payload_json -> 'users') = 'array'
                THEN cached.payload_json -> 'users'
            ELSE '[]'::jsonb
        END
    ) AS item(user_row)
),
filtered AS MATERIALIZED (
    SELECT user_row
    FROM users
    WHERE (%s = '' OR COALESCE(user_row ->> 'company', '') = %s)
      AND (%s = '' OR COALESCE(user_row ->> 'status', '') = %s)
      AND (%s = '' OR COALESCE(user_row ->> 'role', '') = %s)
      AND (
          %s = ''
          OR POSITION(%s IN LOWER(CONCAT_WS(
              ' ',
              user_row ->> 'name',
              user_row ->> 'email',
              user_row ->> 'company',
              user_row ->> 'role'
          ))) > 0
      )
      AND (
          %s = FALSE
          OR COALESCE((user_row ->> 'identified')::boolean, FALSE) = TRUE
      )
      AND (
          %s = ''
          OR COALESCE(user_row ->> 'topFeature', '') = %s
          OR EXISTS (
              SELECT 1
              FROM jsonb_array_elements(
                  CASE
                      WHEN jsonb_typeof(user_row -> 'topFeatures') = 'array'
                          THEN user_row -> 'topFeatures'
                      ELSE '[]'::jsonb
                  END
              ) AS feature_row(value)
              WHERE COALESCE(feature_row.value ->> 'feature', '') = %s
          )
          OR EXISTS (
              SELECT 1
              FROM jsonb_array_elements(
                  CASE
                      WHEN jsonb_typeof(user_row -> 'pageGroups') = 'array'
                          THEN user_row -> 'pageGroups'
                      ELSE '[]'::jsonb
                  END
              ) AS area_row(value)
              WHERE COALESCE(area_row.value ->> 'name', '') = %s
          )
      )
),
filter_options AS (
    SELECT jsonb_build_object(
        'companies', COALESCE((
            SELECT jsonb_agg(option_value ORDER BY option_value)
            FROM (
                SELECT DISTINCT BTRIM(COALESCE(user_row ->> 'company', '')) AS option_value
                FROM users
            ) AS company_options
            WHERE option_value <> ''
        ), '[]'::jsonb),
        'roles', COALESCE((
            SELECT jsonb_agg(option_value ORDER BY option_value)
            FROM (
                SELECT DISTINCT BTRIM(COALESCE(user_row ->> 'role', '')) AS option_value
                FROM users
            ) AS role_options
            WHERE option_value <> ''
        ), '[]'::jsonb),
        'statuses', COALESCE((
            SELECT jsonb_agg(
                option_value
                ORDER BY CASE option_value
                    WHEN 'Power' THEN 0
                    WHEN 'Healthy' THEN 1
                    WHEN 'Light' THEN 2
                    WHEN 'Passive' THEN 3
                    WHEN 'Dropped' THEN 4
                    ELSE 99
                END,
                option_value
            )
            FROM (
                SELECT DISTINCT BTRIM(COALESCE(user_row ->> 'status', '')) AS option_value
                FROM users
            ) AS status_options
            WHERE option_value <> ''
        ), '[]'::jsonb)
    ) AS options
),
filtered_count AS (
    SELECT COUNT(*)::integer AS total_rows
    FROM filtered
),
requested AS (
    SELECT %s::integer AS requested_page, %s::integer AS page_size
),
pagination_base AS (
    SELECT
        filtered_count.total_rows,
        requested.requested_page,
        requested.page_size,
        GREATEST(
            1,
            CEIL(filtered_count.total_rows::numeric / requested.page_size)::integer
        ) AS total_pages
    FROM filtered_count
    CROSS JOIN requested
),
pagination AS (
    SELECT
        total_rows,
        page_size,
        total_pages,
        GREATEST(1, LEAST(requested_page, total_pages)) AS page
    FROM pagination_base
),
numbered AS (
    SELECT
        user_row,
        ROW_NUMBER() OVER (
            ORDER BY
                {sort_expression} {sort_direction},
                LOWER(COALESCE(
                    user_row ->> 'id',
                    user_row ->> 'userId',
                    user_row ->> 'email',
                    user_row ->> 'name',
                    ''
                )) ASC
        ) AS sort_position
    FROM filtered
),
page_rows AS (
    SELECT numbered.user_row, numbered.sort_position
    FROM numbered
    CROSS JOIN pagination
    WHERE numbered.sort_position > (pagination.page - 1) * pagination.page_size
      AND numbered.sort_position <= pagination.page * pagination.page_size
)
SELECT
    COALESCE((
        SELECT jsonb_agg(page_rows.user_row ORDER BY page_rows.sort_position)
        FROM page_rows
    ), '[]'::jsonb) AS rows,
    pagination.page,
    pagination.page_size,
    pagination.total_rows,
    pagination.total_pages,
    filter_options.options AS filter_options
FROM cached
CROSS JOIN pagination
CROSS JOIN filter_options
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


COMPANY_DETAIL_CACHE_INSERT_PREFIX = """
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
VALUES
"""

COMPANY_DETAIL_CACHE_VALUES_TEMPLATE = '(%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, false)'

COMPANY_DETAIL_CACHE_CONFLICT_SUFFIX = """
ON CONFLICT (project_id, range_key, company_id, filters_hash)
DO UPDATE SET
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date,
    payload_json = EXCLUDED.payload_json,
    generated_at = EXCLUDED.generated_at,
    expires_at = EXCLUDED.expires_at,
    is_stale = false
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
