# Generated manually for OSS - users who left their last project by themselves

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('projects', '0005_chatgptkey_is_checked_check_result'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserLeftLastProject',
            fields=[
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True,
                    related_name='left_last_project_oss',
                    serialize=False,
                    to=settings.AUTH_USER_MODEL,
                )),
                ('project', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='users_who_left_oss',
                    to='projects.project',
                )),
            ],
            options={
                'db_table': 'projects_userleftlastproject',
            },
        ),
    ]
