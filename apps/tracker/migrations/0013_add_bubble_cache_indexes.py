# Generated migration for BubbleCache performance optimization

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0012_rename_keep_suffix_chars_to_hide_after_delimiter'),
    ]

    operations = [
        # Composite index for the main query in _build_day_navigator
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_bubblecache_session_timestamp ON tracker_bubblecache (session_id, timestamp);",
            reverse_sql="DROP INDEX IF EXISTS idx_bubblecache_session_timestamp;"
        ),
        
        # Index for session start_time filtering (without DATE function)
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_session_start_time ON tracker_session (start_time);",
            reverse_sql="DROP INDEX IF EXISTS idx_session_start_time;"
        ),
        
        # Composite index for session filtering by visitor and start_time
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_session_visitor_start_time ON tracker_session (visitor_id, start_time);",
            reverse_sql="DROP INDEX IF EXISTS idx_session_visitor_start_time;"
        ),
        
        # Index for visitor project filtering
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_visitor_project ON tracker_visitor (project_id);",
            reverse_sql="DROP INDEX IF EXISTS idx_visitor_project;"
        ),
    ]
