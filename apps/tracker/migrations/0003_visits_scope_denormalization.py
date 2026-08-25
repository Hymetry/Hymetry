from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0002_analyticssession_visit_session_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='session',
            name='analytics_event_end',
            field=models.DateTimeField(blank=True, help_text='Last linked analytics event timestamp; null when unlinked.', null=True),
        ),
        migrations.AddField(
            model_name='session',
            name='analytics_event_start',
            field=models.DateTimeField(blank=True, help_text='First linked analytics event timestamp; null when unlinked.', null=True),
        ),
        migrations.AddField(
            model_name='session',
            name='has_replay_snapshot',
            field=models.BooleanField(default=False, help_text='Whether a stored rrweb full snapshot makes this session replayable.'),
        ),
        migrations.AddField(
            model_name='session',
            name='has_meaningful_analytics',
            field=models.BooleanField(default=False, help_text='Whether linked analytics show an identity, more than one page visit, a click or scroll, or a span of at least ten seconds.'),
        ),
        migrations.AddIndex(
            model_name='session',
            index=models.Index(condition=models.Q(('has_replay_snapshot', True)), fields=['analytics_event_start', 'session_id'], name='trk_sess_visits_scope_idx'),
        ),
    ]
