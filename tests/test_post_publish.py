"""Tests for the repairs that run after a graph is published."""

from unittest import mock

from django.test import SimpleTestCase, override_settings

from catalina import post_publish


class FakeRedis:
    def __init__(self, keys):
        self.keys = list(keys)
        self.deleted = []

    def scan_iter(self, match=None, count=None):
        return iter(self.keys)

    def delete(self, *keys):
        self.deleted.extend(keys)
        return len(keys)


class ClearTileCacheTests(SimpleTestCase):
    def _caches(self, client):
        cache = mock.Mock()
        cache._cache.get_client.return_value = client
        return {"default": cache}

    def test_deletes_every_matching_key_in_batches(self):
        client = FakeRedis([f":1:mvt_{i}" for i in range(1200)])
        with mock.patch.object(post_publish, "caches", self._caches(client)):
            self.assertEqual(post_publish.clear_tile_cache(), 1200)
        self.assertEqual(len(client.deleted), 1200)

    def test_nothing_to_delete(self):
        client = FakeRedis([])
        with mock.patch.object(post_publish, "caches", self._caches(client)):
            self.assertEqual(post_publish.clear_tile_cache(), 0)
        self.assertEqual(client.deleted, [])

    def test_non_redis_cache_is_skipped(self):
        cache = mock.Mock(spec=[])  # no _cache attribute
        with mock.patch.object(post_publish, "caches", {"default": cache}):
            self.assertIsNone(post_publish.clear_tile_cache())


class RunPostPublishTests(SimpleTestCase):
    def _patched(self, **overrides):
        names = (
            "migrate_stale_instances",
            "rebuild_geometries",
            "rebuild_relationships",
            "clear_tile_cache",
        )
        patches = {n: mock.Mock(return_value=n) for n in names}
        patches.update(overrides)
        return patches

    def _run(self, patches, **kwargs):
        calls = []
        for name, fn in patches.items():
            fn.side_effect = (
                fn.side_effect
                if isinstance(fn.side_effect, Exception)
                else (lambda *a, _n=name, **k: calls.append(_n) or _n)
            )
        with mock.patch.multiple(post_publish, **patches):
            results = post_publish.run_post_publish("g1", user_id=3, **kwargs)
        return results, calls

    def test_runs_in_dependency_order_with_migration(self):
        _, calls = self._run(self._patched(), migrate=True)
        self.assertEqual(
            calls,
            [
                "migrate_stale_instances",
                "rebuild_geometries",
                "rebuild_relationships",
                "clear_tile_cache",
            ],
        )

    def test_migration_is_skipped_when_not_requested(self):
        _, calls = self._run(self._patched(), migrate=False)
        self.assertNotIn("migrate_stale_instances", calls)
        self.assertEqual(calls[-1], "clear_tile_cache")

    @override_settings(AUTO_MIGRATE_STALE_INSTANCES=True)
    def test_migration_follows_the_setting_by_default(self):
        _, calls = self._run(self._patched())
        self.assertIn("migrate_stale_instances", calls)

    @override_settings(AUTO_MIGRATE_STALE_INSTANCES=False)
    def test_setting_off_by_default_skips_migration(self):
        _, calls = self._run(self._patched())
        self.assertNotIn("migrate_stale_instances", calls)

    def test_a_failing_step_does_not_stop_the_rest(self):
        failing = mock.Mock(side_effect=RuntimeError("boom"))
        patches = self._patched(rebuild_geometries=failing)
        results, calls = self._run(patches, migrate=False)
        self.assertIsInstance(results["rebuild_geometries"], RuntimeError)
        self.assertEqual(calls, ["rebuild_relationships", "clear_tile_cache"])


class MigrateStaleInstancesStepTests(SimpleTestCase):
    def test_skipped_while_the_arches_data_update_is_running(self):
        with (
            mock.patch.object(post_publish, "data_update_running", return_value=True),
            mock.patch.object(post_publish, "call_command") as call_command,
        ):
            self.assertIsNone(post_publish.migrate_stale_instances("g1"))
        call_command.assert_not_called()

    def test_scoped_to_the_graph_by_exact_id(self):
        with (
            mock.patch.object(post_publish, "data_update_running", return_value=False),
            mock.patch.object(post_publish, "call_command") as call_command,
        ):
            post_publish.migrate_stale_instances("g1")
        args = call_command.call_args.args
        self.assertEqual(args[0], "migrate_stale_instances")
        self.assertIn("--apply", args)
        self.assertEqual(args[args.index("--graph-id") + 1], "g1")


class DataUpdateRunningTests(SimpleTestCase):
    def _inspector(self, active, reserved):
        inspector = mock.Mock()
        inspector.active.return_value = active
        inspector.reserved.return_value = reserved
        app = mock.Mock()
        app.control.inspect.return_value = inspector
        return app

    def _check(self, app):
        with mock.patch("catalina.celery.app", app):
            return post_publish.data_update_running()

    def test_active_task_is_seen(self):
        app = self._inspector({"w1": [{"name": post_publish.DATA_UPDATE_TASK}]}, {})
        self.assertTrue(self._check(app))

    def test_reserved_task_is_seen(self):
        app = self._inspector({}, {"w1": [{"name": post_publish.DATA_UPDATE_TASK}]})
        self.assertTrue(self._check(app))

    def test_other_tasks_are_ignored(self):
        app = self._inspector(
            {"w1": [{"name": "catalina.tasks.after_graph_publish"}]}, {}
        )
        self.assertFalse(self._check(app))

    def test_no_worker_answering_does_not_block(self):
        self.assertFalse(self._check(self._inspector(None, None)))


class SignalReceiverTests(SimpleTestCase):
    def _publication(self):
        return mock.Mock(graph_id="g1", user_id=7)

    def test_queues_on_commit_for_a_new_publication(self):
        with (
            mock.patch.object(
                post_publish.transaction, "on_commit", side_effect=lambda f: f()
            ),
            mock.patch.object(post_publish, "_queue") as queue,
            override_settings(AUTO_MIGRATE_STALE_INSTANCES=True),
        ):
            post_publish.schedule_after_publish(None, self._publication(), created=True)
        queue.assert_called_once_with(
            "g1",
            7,
            migrate=True,
            countdown=post_publish.MIGRATE_DELAY_SECONDS,
        )

    def test_ignores_updates_and_fixture_loads(self):
        with mock.patch.object(post_publish.transaction, "on_commit") as on_commit:
            post_publish.schedule_after_publish(
                None, self._publication(), created=False
            )
            post_publish.schedule_after_publish(
                None, self._publication(), created=True, raw=True
            )
        on_commit.assert_not_called()

    def test_data_update_finishing_queues_a_repair_without_migrating(self):
        sender = mock.Mock()
        sender.name = post_publish.DATA_UPDATE_TASK
        args = ({"graphid": "old"}, {"graphid": "g1"}, 7)
        with mock.patch.object(post_publish, "_queue") as queue:
            post_publish.queue_after_data_update(sender=sender, args=args)
        queue.assert_called_once_with("g1", user_id=None, migrate=False)

    def test_other_tasks_finishing_are_ignored(self):
        sender = mock.Mock()
        sender.name = "arches.app.tasks.something_else"
        with mock.patch.object(post_publish, "_queue") as queue:
            post_publish.queue_after_data_update(sender=sender, args=({}, {}, 1))
        queue.assert_not_called()

    def test_unreadable_arguments_are_ignored(self):
        sender = mock.Mock()
        sender.name = post_publish.DATA_UPDATE_TASK
        with mock.patch.object(post_publish, "_queue") as queue:
            post_publish.queue_after_data_update(sender=sender, args=None)
        queue.assert_not_called()
