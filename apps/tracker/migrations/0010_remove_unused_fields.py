# Generated migration to remove unused fields

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0009_add_secure_masking_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='safeinputregextemplate',
            name='keep_suffix_chars',
        ),
        migrations.RemoveField(
            model_name='safeinputregextemplate',
            name='replacing_code',
        ),
    ]
