# Generated by Django 3.1.5 on 2021-01-27 23:33

from django.db import migrations, models


def update_channels(apps, schema_editor):
    NimbusExperiment = apps.get_model("experiments", "NimbusExperiment")
    db_alias = schema_editor.connection.alias
    NimbusExperiment.objects.using(db_alias).filter(channel="org.mozilla.fenix").update(
        channel="nightly"
    )
    NimbusExperiment.objects.using(db_alias).filter(
        channel="org.mozilla.firefox.beta"
    ).update(channel="beta")
    NimbusExperiment.objects.using(db_alias).filter(channel="org.mozilla.firefox").update(
        channel="release"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("experiments", "0153_auto_20210127_1855"),
    ]

    operations = [
        migrations.RunPython(update_channels),
        migrations.AlterField(
            model_name="nimbusexperiment",
            name="channel",
            field=models.CharField(
                choices=[
                    ("", "No Channel"),
                    ("default", "Unbranded"),
                    ("nightly", "Nightly"),
                    ("beta", "Beta"),
                    ("release", "Release"),
                ],
                default="",
                max_length=255,
            ),
        ),
    ]