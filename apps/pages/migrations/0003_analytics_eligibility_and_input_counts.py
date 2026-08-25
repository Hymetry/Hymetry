from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pages', '0002_pagesoverviewcache_payload_compressed_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='pagevisit',
            name='is_analytics_eligible',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='pagevisit',
            name='key_press_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='pagevisit',
            name='touch_move_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='pagevisit',
            name='had_key_press',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='pagevisit',
            name='had_touch_move',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='pagedailymetric',
            name='key_press_count',
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='pagedailymetric',
            name='touch_move_count',
            field=models.PositiveBigIntegerField(default=0),
        ),
    ]
