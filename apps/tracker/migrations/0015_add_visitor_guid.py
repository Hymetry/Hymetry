from django.db import migrations, models
import uuid


def copy_visitor_id_to_guid(apps, schema_editor):
    """Copy existing visitor_id values to visitor_guid field"""
    Visitor = apps.get_model('tracker', 'Visitor')
    for visitor in Visitor.objects.all():
        visitor.visitor_guid = visitor.visitor_id
        visitor.save(update_fields=['visitor_guid'])


def reverse_copy_visitor_id_to_guid(apps, schema_editor):
    """Reverse operation - clear visitor_guid"""
    Visitor = apps.get_model('tracker', 'Visitor')
    Visitor.objects.all().update(visitor_guid=None)


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0013_add_bubble_cache_indexes'),
    ]

    operations = [
        # Add visitor_guid field
        migrations.AddField(
            model_name='visitor',
            name='visitor_guid',
            field=models.UUIDField(blank=True, help_text='Visitor ID from browser', null=True),
        ),
        
        # Copy existing visitor_id to visitor_guid
        migrations.RunPython(
            copy_visitor_id_to_guid,
            reverse_copy_visitor_id_to_guid,
        ),
        
        # Add unique_together constraint
        migrations.AlterUniqueTogether(
            name='visitor',
            unique_together={('visitor_guid', 'project')},
        ),
    ]
