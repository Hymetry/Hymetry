# Generated manually for field rename and type change

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0011_safeinputregextemplate_keep_suffix_chars_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='safeinputregextemplate',
            name='keep_suffix_chars',
        ),
        migrations.AddField(
            model_name='safeinputregextemplate',
            name='hide_after_delimiter',
            field=models.CharField(blank=True, help_text="Delimiter to hide everything after (e.g., '@' for emails)", max_length=10, null=True),
        ),
    ]
