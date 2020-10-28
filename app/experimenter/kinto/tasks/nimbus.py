import markus
from celery.utils.log import get_task_logger
from django.conf import settings
from django.contrib.auth import get_user_model

from experimenter.celery import app
from experimenter.experiments.api.v6.serializers import NimbusExperimentSerializer
from experimenter.experiments.changelog_utils import generate_nimbus_changelog
from experimenter.experiments.models import (
    NimbusBucketRange,
    NimbusExperiment,
    NimbusIsolationGroup,
)
from experimenter.kinto.client import KintoClient

logger = get_task_logger(__name__)
metrics = markus.get_metrics("kinto.nimbus_tasks")


def get_kinto_user():
    user, _ = get_user_model().objects.get_or_create(
        email=settings.KINTO_DEFAULT_CHANGELOG_USER,
        username=settings.KINTO_DEFAULT_CHANGELOG_USER,
    )
    return user


@app.task
@metrics.timer_decorator("push_experiment_to_kinto.timing")
def nimbus_push_experiment_to_kinto(experiment_id):
    """
    An invoked task that given a single experiment id, query it in the db, serialize it,
    and push its data to the configured collection. If it fails for any reason, log the
    error and reraise it so it will be forwarded to sentry.
    """
    kinto_client = KintoClient(settings.KINTO_COLLECTION_NIMBUS)

    metrics.incr("push_experiment_to_kinto.started")

    try:
        experiment = NimbusExperiment.objects.get(id=experiment_id)
        logger.info(f"Pushing {experiment} to Kinto")

        if not NimbusBucketRange.objects.filter(experiment=experiment).exists():
            NimbusIsolationGroup.request_isolation_group_buckets(
                experiment.slug,
                experiment,
                NimbusExperiment.BUCKET_COUNT,
            )

        data = NimbusExperimentSerializer(experiment).data

        kinto_client.push_to_kinto(data)

        experiment.status = NimbusExperiment.Status.ACCEPTED
        experiment.save()

        generate_nimbus_changelog(experiment, get_kinto_user())

        logger.info(f"{experiment} pushed to Kinto")
        metrics.incr("push_experiment_to_kinto.completed")
    except Exception as e:
        metrics.incr("push_experiment_to_kinto.failed")
        logger.info(f"Pushing experiment id {experiment_id} to Kinto failed: {e}")
        raise e


@app.task
@metrics.timer_decorator("check_kinto_push_queue")
def nimbus_check_kinto_push_queue():
    """
    Because kinto has a restriction that it can only have a single pending review, this
    task brokers the queue of all experiments ready to be pushed to kinto and ensures
    that only a single experiment is ever in review.

    A scheduled task that
    - Checks the kinto collection for a single rejected experiment from a previous push
      - If one exists, pull it out of the collection and mark it as rejected
    - Checks if there is still a pending review and if so, aborts
    - Gets the list of all experiments ready to be pushed to kinto and pushes the first
      one
    """
    kinto_client = KintoClient(settings.KINTO_COLLECTION_NIMBUS)

    metrics.incr("check_kinto_push_queue.started")

    rejected_collection_data = kinto_client.get_rejected_collection_data()
    if rejected_collection_data:
        rejected_slug = kinto_client.get_rejected_record()
        experiment = NimbusExperiment.objects.get(slug=rejected_slug)
        experiment.status = NimbusExperiment.Status.DRAFT
        experiment.save()

        generate_nimbus_changelog(
            experiment,
            get_kinto_user(),
            message=f'Rejected: {rejected_collection_data["last_reviewer_comment"]}',
        )

        kinto_client.delete_rejected_record(rejected_slug)

    if kinto_client.has_pending_review():
        metrics.incr("check_kinto_push_queue.pending_review")
        return

    queued_experiments = NimbusExperiment.objects.filter(
        status=NimbusExperiment.Status.REVIEW
    )
    if queued_experiments.exists():
        nimbus_push_experiment_to_kinto.delay(queued_experiments.first().id)
        metrics.incr("check_kinto_push_queue.queued_experiment_selected")
    else:
        metrics.incr("check_kinto_push_queue.no_experiments_queued")

    metrics.incr("check_kinto_push_queue.completed")


@app.task
@metrics.timer_decorator("check_experiments_are_live")
def nimbus_check_experiments_are_live():
    """
    A scheduled task that checks the kinto collection for any experiment slugs that are
    present in the collection but are not yet marked as live in the database and marks
    them as live.
    """
    kinto_client = KintoClient(settings.KINTO_COLLECTION_NIMBUS)

    metrics.incr("check_experiments_are_live.started")

    accepted_experiments = NimbusExperiment.objects.filter(
        status=NimbusExperiment.Status.ACCEPTED
    )

    records = kinto_client.get_main_records()
    record_ids = [r.get("id") for r in records]

    for experiment in accepted_experiments:
        if experiment.slug in record_ids:
            logger.info(
                "{experiment} status is being updated to live".format(
                    experiment=experiment
                )
            )

            experiment.status = NimbusExperiment.Status.LIVE
            experiment.save()

            generate_nimbus_changelog(experiment, get_kinto_user())

            logger.info("{experiment} status is set to Live")

    metrics.incr("check_experiments_are_live.completed")


@app.task
@metrics.timer_decorator("check_experiments_are_complete")
def nimbus_check_experiments_are_complete():
    """
    A scheduled task that checks the kinto collection for any experiment slugs that are
    marked as live in the database but missing from the collection, indicating that they
    are no longer live and can be marked as complete.
    """
    kinto_client = KintoClient(settings.KINTO_COLLECTION_NIMBUS)

    metrics.incr("check_experiments_are_complete.started")

    live_experiments = NimbusExperiment.objects.filter(
        status=NimbusExperiment.Status.LIVE
    )

    records = kinto_client.get_main_records()
    record_ids = [r.get("id") for r in records]

    for experiment in live_experiments:
        if experiment.slug not in record_ids:
            logger.info(
                "{experiment} status is being updated to complete".format(
                    experiment=experiment
                )
            )

            experiment.status = NimbusExperiment.Status.COMPLETE
            experiment.save()

            generate_nimbus_changelog(experiment, get_kinto_user())

            logger.info("{experiment} status is set to Complete")

    metrics.incr("check_experiments_are_complete.completed")