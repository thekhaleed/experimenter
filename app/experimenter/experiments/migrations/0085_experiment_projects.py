# Generated by Django 3.0.4 on 2020-03-18 20:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0005_project"),
        ("experiments", "0084_rolloutpreference"),
    ]

    operations = [
        migrations.AddField(
            model_name="experiment",
            name="projects",
            field=models.ManyToManyField(blank=True, to="projects.Project"),
        )
    ]