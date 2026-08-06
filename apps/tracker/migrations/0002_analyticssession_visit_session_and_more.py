import django.db.models.deletion
from django.db import migrations, models


ORDER_INDEX_NAME = 'trk_event_sess_ts_id_idx'
META_INDEX_NAME = 'trk_event_meta_ctx_idx'
SNAPSHOT_INDEX_NAME = 'trk_event_snapshot_idx'
CLICK_COMPANY_INDEX_NAME = 'trk_anae_click_comp_ts_idx'
LEGACY_PERIODIC_TASK_NAMES = (
    'Bubble cache refresh',
    'Calculate normalization factors daily',
    'Normalization',
)
LEGACY_PERIODIC_TASK_PATHS = (
    'apps.tracker.tasks.run_calculate_bubble_cache',
    'apps.tracker.tasks.calculate_bubble_cache',
    'apps.tracker.tasks.calculate_project_normalization_factors',
)


def close_duplicate_open_sessions(apps, schema_editor):
    session = apps.get_model('tracker', 'Session')
    duplicate_visitors = (
        session.objects
        .filter(visitor_id__isnull=False, ended_at__isnull=True)
        .values('visitor_id')
        .annotate(open_count=models.Count('session_id'))
        .filter(open_count__gt=1)
    )
    for row in duplicate_visitors.iterator():
        open_sessions = list(
            session.objects
            .filter(visitor_id=row['visitor_id'], ended_at__isnull=True)
            .order_by('-last_activity', '-start_time', 'session_id')
        )
        for duplicate in open_sessions[1:]:
            duplicate.ended_at = max(
                duplicate.start_time,
                duplicate.last_activity or duplicate.start_time,
            )
            duplicate.save(update_fields=['ended_at'])


def disable_legacy_periodic_tasks(apps, schema_editor):
    connection = schema_editor.connection
    table_name = 'django_celery_beat_periodictask'
    if table_name not in connection.introspection.table_names():
        return

    quote_name = connection.ops.quote_name
    name_placeholders = ', '.join(['%s'] * len(LEGACY_PERIODIC_TASK_NAMES))
    task_placeholders = ', '.join(['%s'] * len(LEGACY_PERIODIC_TASK_PATHS))
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE {quote_name(table_name)} SET {quote_name("enabled")} = %s '
            f'WHERE {quote_name("name")} IN ({name_placeholders}) '
            f'OR {quote_name("task")} IN ({task_placeholders})',
            [False, *LEGACY_PERIODIC_TASK_NAMES, *LEGACY_PERIODIC_TASK_PATHS],
        )


def _stream_indexes():
    return (
        models.Index(fields=['session', 'timestamp', 'id'], name=ORDER_INDEX_NAME),
        models.Index(
            fields=['session', 'tab_id', 'timestamp', 'id'],
            condition=models.Q(event_type=4),
            name=META_INDEX_NAME,
        ),
        models.Index(
            fields=['session', 'timestamp', 'id'],
            condition=models.Q(event_type=2),
            name=SNAPSHOT_INDEX_NAME,
        ),
    )


def _click_company_index():
    return models.Index(
        fields=['company_id', 'timestamp'],
        condition=models.Q(event_type__iexact='click'),
        name=CLICK_COMPANY_INDEX_NAME,
    )


def _postgres_index_state(schema_editor, name):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            '''
            SELECT index_state.indisvalid, pg_get_indexdef(index_state.indexrelid)
            FROM pg_index AS index_state
            JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid
            JOIN pg_namespace AS index_namespace ON index_namespace.oid = index_class.relnamespace
            WHERE index_namespace.nspname = current_schema()
              AND index_class.relname = %s
            ''',
            [name],
        )
        return cursor.fetchone()


def _ensure_postgres_index(schema_editor, *, name, create_sql, definition_fragments):
    state = _postgres_index_state(schema_editor, name)
    quote = schema_editor.quote_name
    if state is not None:
        is_valid, definition = state
        normalized_definition = str(definition).lower().replace('"', '')
        if is_valid:
            if not all(fragment in normalized_definition for fragment in definition_fragments):
                raise RuntimeError(f'Existing index {name} does not match the expected definition.')
            return
        schema_editor.execute(f'DROP INDEX CONCURRENTLY {quote(name)}')
    schema_editor.execute(create_sql)


def add_replay_indexes(apps, schema_editor):
    event = apps.get_model('tracker', 'Event')
    analytics_event = apps.get_model('tracker', 'AnalyticsEvent')
    if schema_editor.connection.vendor != 'postgresql':
        for index in _stream_indexes():
            schema_editor.add_index(event, index)
        schema_editor.add_index(analytics_event, _click_company_index())
        return

    quote = schema_editor.quote_name
    event_table = quote(event._meta.db_table)
    analytics_table = quote(analytics_event._meta.db_table)
    _ensure_postgres_index(
        schema_editor,
        name=ORDER_INDEX_NAME,
        create_sql=(
            f'CREATE INDEX CONCURRENTLY {quote(ORDER_INDEX_NAME)} ON {event_table} '
            f'({quote("session_id")}, {quote("timestamp")}, {quote("id")})'
        ),
        definition_fragments=('tracker_event', '(session_id, timestamp, id)'),
    )
    _ensure_postgres_index(
        schema_editor,
        name=META_INDEX_NAME,
        create_sql=(
            f'CREATE INDEX CONCURRENTLY {quote(META_INDEX_NAME)} ON {event_table} '
            f'({quote("session_id")}, {quote("tab_id")}, {quote("timestamp")}, {quote("id")}) '
            f'WHERE {quote("event_type")} = 4'
        ),
        definition_fragments=('tracker_event', '(session_id, tab_id, timestamp, id)', 'event_type = 4'),
    )
    _ensure_postgres_index(
        schema_editor,
        name=SNAPSHOT_INDEX_NAME,
        create_sql=(
            f'CREATE INDEX CONCURRENTLY {quote(SNAPSHOT_INDEX_NAME)} ON {event_table} '
            f'({quote("session_id")}, {quote("timestamp")}, {quote("id")}) '
            f'WHERE {quote("event_type")} = 2'
        ),
        definition_fragments=('tracker_event', '(session_id, timestamp, id)', 'event_type = 2'),
    )
    _ensure_postgres_index(
        schema_editor,
        name=CLICK_COMPANY_INDEX_NAME,
        create_sql=(
            f'CREATE INDEX CONCURRENTLY {quote(CLICK_COMPANY_INDEX_NAME)} ON {analytics_table} '
            f'({quote("company_id")}, {quote("timestamp")}) '
            f'WHERE UPPER({quote("event_type")}::text) = \'CLICK\''
        ),
        definition_fragments=(
            analytics_event._meta.db_table,
            '(company_id, timestamp)',
            "upper((event_type)::text) = 'click'::text",
        ),
    )


def remove_replay_indexes(apps, schema_editor):
    event = apps.get_model('tracker', 'Event')
    analytics_event = apps.get_model('tracker', 'AnalyticsEvent')
    if schema_editor.connection.vendor == 'postgresql':
        quote = schema_editor.quote_name
        for name in (
            CLICK_COMPANY_INDEX_NAME,
            SNAPSHOT_INDEX_NAME,
            META_INDEX_NAME,
            ORDER_INDEX_NAME,
        ):
            schema_editor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {quote(name)}')
        return
    schema_editor.remove_index(analytics_event, _click_company_index())
    for index in reversed(_stream_indexes()):
        schema_editor.remove_index(event, index)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('projects', '0002_project_analytics_facts_revision_and_more'),
        ('tracker', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='analyticssession',
            name='visit_session',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='analytics_fragments',
                to='tracker.session',
            ),
        ),
        migrations.AddField(
            model_name='session',
            name='identity_linkage_ready',
            field=models.BooleanField(
                default=False,
                help_text='Whether analytics identity fragments use the canonical session link.',
            ),
        ),
        migrations.AddIndex(
            model_name='analyticssession',
            index=models.Index(
                fields=['visit_session', 'start_time'],
                name='trk_anas_visit_start_idx',
            ),
        ),
        migrations.RunPython(close_duplicate_open_sessions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='session',
            constraint=models.UniqueConstraint(
                condition=models.Q(ended_at__isnull=True),
                fields=('visitor',),
                name='trk_session_one_open_per_visitor',
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_replay_indexes, remove_replay_indexes),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name='analyticsevent',
                    index=_click_company_index(),
                ),
                migrations.AddIndex(
                    model_name='event',
                    index=_stream_indexes()[0],
                ),
                migrations.AddIndex(
                    model_name='event',
                    index=_stream_indexes()[1],
                ),
                migrations.AddIndex(
                    model_name='event',
                    index=_stream_indexes()[2],
                ),
            ],
        ),
        migrations.RunPython(disable_legacy_periodic_tasks, migrations.RunPython.noop),
    ]
