"""Tests for the migrate_stale_instances management command."""

from django.test import SimpleTestCase

from catalina.management.commands.migrate_stale_instances import diff_graphs


def _graph(nodegroups, nodes):
    return {
        "nodegroups": [{"nodegroupid": n} for n in nodegroups],
        "nodes": [{"nodeid": n} for n in nodes],
    }


class DiffGraphsTests(SimpleTestCase):
    def test_identical_graphs_have_no_diff(self):
        g = _graph(["a"], ["n1", "n2"])
        self.assertEqual(diff_graphs(g, g), (set(), set(), set()))

    def test_removed_and_added(self):
        initial = _graph(["a", "b"], ["n1", "n2"])
        updated = _graph(["a"], ["n2", "n3"])
        self.assertEqual(diff_graphs(initial, updated), ({"b"}, {"n1"}, {"n3"}))

    def test_recreated_nodes_show_as_removed_and_added(self):
        initial = _graph(["a"], ["old"])
        updated = _graph(["a"], ["new"])
        self.assertEqual(diff_graphs(initial, updated), (set(), {"old"}, {"new"}))
