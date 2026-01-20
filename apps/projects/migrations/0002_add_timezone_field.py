# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='timezone',
            field=models.CharField(default='UTC', help_text='Project timezone for session date filtering', max_length=50),
        ),
    ]
