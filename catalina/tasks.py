from celery import shared_task


@shared_task
def after_graph_publish(graph_id, user_id=None, migrate=None):
    """Repair a graph's geometries, relationships and stale instances after a
    publish. See catalina.post_publish."""
    from catalina.post_publish import run_post_publish

    run_post_publish(graph_id, user_id=user_id, migrate=migrate)
