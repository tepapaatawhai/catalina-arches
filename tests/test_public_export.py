"""Tests for catalina/utils/public_export.py (the prebuild export)."""

import json
import os
import sys
import tarfile
import tempfile
import uuid
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from catalina.utils import public_export as pe


def _tile(nodegroup_id, actors):
    return {"nodegroup_id": nodegroup_id, "data": {pe.ACTOR_NODE_ID: actors}}


class NamingTests(SimpleTestCase):
    def test_business_data_filename_has_t_prefix_and_slug(self):
        self.assertEqual(
            pe.business_data_filename("Heritage Place"), "t_heritage_place.json"
        )
        self.assertEqual(
            pe.business_data_filename("Digital Object"), "t_digital_object.json"
        )

    def test_business_data_filename_collapses_punctuation(self):
        self.assertEqual(pe.business_data_filename(" A/B  c! "), "t_a_b_c.json")

    def test_resolve_i18n_name(self):
        self.assertEqual(
            pe._resolve_i18n_name({"en": "Person", "mi": "Tangata"}), "Person"
        )
        self.assertEqual(pe._resolve_i18n_name({"mi": "Tangata"}), "Tangata")
        self.assertEqual(pe._resolve_i18n_name({}), "Unknown")
        self.assertEqual(pe._resolve_i18n_name("Plain"), "Plain")


class ActorTileTests(SimpleTestCase):
    def test_keeps_tiles_outside_the_actors_nodegroup(self):
        other = {"nodegroup_id": "other", "data": {}}
        resource = {"tiles": [other]}
        self.assertEqual(pe.strip_unresolvable_actor_tiles(resource, set()), 0)
        self.assertEqual(resource["tiles"], [other])

    def test_keeps_actor_tile_for_an_exported_person(self):
        tile = _tile(pe.ASSOCIATED_ACTORS_NODEGROUP_ID, [{"resourceId": "p1"}])
        resource = {"tiles": [tile]}
        self.assertEqual(pe.strip_unresolvable_actor_tiles(resource, {"p1"}), 0)
        self.assertEqual(resource["tiles"], [tile])

    def test_removes_actor_tile_for_a_person_not_exported(self):
        tile = _tile(pe.ASSOCIATED_ACTORS_NODEGROUP_ID, [{"resourceId": "p2"}])
        resource = {"tiles": [tile]}
        self.assertEqual(pe.strip_unresolvable_actor_tiles(resource, {"p1"}), 1)
        self.assertEqual(resource["tiles"], [])

    def test_keeps_tile_when_any_referenced_person_is_exported(self):
        tile = _tile(
            pe.ASSOCIATED_ACTORS_NODEGROUP_ID,
            [{"resourceId": "p2"}, {"resourceId": "p1"}],
        )
        resource = {"tiles": [tile]}
        self.assertEqual(pe.strip_unresolvable_actor_tiles(resource, {"p1"}), 0)

    def test_wraps_a_non_list_value_and_removes_empty_actor_tiles(self):
        single = _tile(pe.ASSOCIATED_ACTORS_NODEGROUP_ID, {"resourceId": "p1"})
        empty = {"nodegroup_id": pe.ASSOCIATED_ACTORS_NODEGROUP_ID, "data": None}
        resource = {"tiles": [single, empty]}
        self.assertEqual(pe.strip_unresolvable_actor_tiles(resource, {"p1"}), 1)
        self.assertEqual(resource["tiles"], [single])


class FileReferenceTests(SimpleTestCase):
    def test_collects_deduplicates_and_sorts_file_references(self):
        resources = [
            {
                "resourceinstance": {"resourceinstanceid": "r1"},
                "tiles": [
                    {
                        "data": {
                            "n1": [
                                {"file_id": "f2", "name": "b.jpg", "url": "/b"},
                                {"file_id": "f1", "name": "a.jpg"},
                                "junk",
                            ],
                            "not_a_file_node": [{"file_id": "x", "name": "x.jpg"}],
                        }
                    }
                ],
            },
            {
                "resourceinstance": {"resourceinstanceid": "r2"},
                "tiles": [
                    {
                        "data": {
                            "n1": [
                                {"file_id": "f1", "name": "a.jpg"},
                                {"name": "c.jpg"},
                                {},
                            ],
                            "n2": "not a list",
                        }
                    },
                    {"data": None},
                ],
            },
        ]
        files = pe.extract_file_references(resources, file_node_ids={"n1", "n2"})
        self.assertEqual([f["name"] for f in files], ["a.jpg", "b.jpg", "c.jpg"])
        # The first occurrence wins when a file is referenced twice.
        self.assertEqual(files[0]["resourceinstanceid"], "r1")
        self.assertEqual(files[1]["url"], "/b")
        self.assertEqual(files[2]["file_id"], None)

    def test_looks_up_file_nodes_when_not_given(self):
        with mock.patch.object(pe, "get_file_node_ids", return_value={"n1"}) as lookup:
            files = pe.extract_file_references(
                [{"tiles": [{"data": {"n1": [{"file_id": "f", "name": "f.jpg"}]}}]}]
            )
        lookup.assert_called_once_with()
        self.assertEqual(len(files), 1)


class LookupTests(SimpleTestCase):
    """Selection helpers, with the ORM replaced by mocks."""

    def test_get_file_node_ids(self):
        node_id = uuid.UUID(int=1)
        with mock.patch.object(pe, "Node") as node:
            qs = node.objects.filter.return_value
            qs.values_list.return_value = [node_id]
            self.assertEqual(pe.get_file_node_ids(), {str(node_id)})
            qs.filter.assert_not_called()

    def test_get_file_node_ids_restricted_to_graphs(self):
        node_id = uuid.UUID(int=2)
        graph_id = uuid.UUID(int=3)
        with mock.patch.object(pe, "Node") as node:
            restricted = node.objects.filter.return_value.filter.return_value
            restricted.values_list.return_value = [node_id]
            self.assertEqual(pe.get_file_node_ids([graph_id]), {str(node_id)})
            node.objects.filter.return_value.filter.assert_called_once_with(
                graph_id__in=[str(graph_id)]
            )

    def test_get_controlled_list_ids_for_graphs(self):
        nodes = [
            SimpleNamespace(config={"controlledList": "a"}),
            SimpleNamespace(config={}),
            SimpleNamespace(config={"controlledList": "a"}),
            SimpleNamespace(config={"controlledList": "b"}),
        ]
        with mock.patch.object(pe, "Node") as node:
            node.objects.filter.return_value = nodes
            self.assertEqual(pe.get_controlled_list_ids_for_graphs(["g"]), {"a", "b"})

    def test_get_exportable_resource_ids_defaults_to_every_state(self):
        with mock.patch("arches.app.models.models.ResourceInstance") as instance:
            qs = instance.objects.exclude.return_value
            qs.values_list.return_value = ["a", "b"]
            self.assertEqual(pe.get_exportable_resource_ids(), ["a", "b"])
            qs.filter.assert_not_called()
            instance.objects.exclude.assert_called_once_with(
                graph_id__in={pe.PERIOD_GRAPH_ID, pe.SYSTEM_SETTINGS_GRAPH_ID}
            )

    def test_get_exportable_resource_ids_filters_by_state(self):
        with mock.patch("arches.app.models.models.ResourceInstance") as instance:
            qs = instance.objects.exclude.return_value
            qs.filter.return_value.values_list.return_value = ["a"]
            self.assertEqual(pe.get_exportable_resource_ids(["Active"]), ["a"])
            qs.filter.assert_called_once_with(
                resource_instance_lifecycle_state__name__in=["Active"]
            )

    def test_get_exportable_graph_ids(self):
        with mock.patch("arches.app.models.models.GraphModel") as graph_model:
            chain = graph_model.objects.filter.return_value.exclude.return_value
            chain.values_list.return_value = [uuid.UUID(int=1), uuid.UUID(int=2)]
            self.assertEqual(
                pe.get_exportable_graph_ids(),
                {str(uuid.UUID(int=1)), str(uuid.UUID(int=2))},
            )
            graph_model.objects.filter.return_value.exclude.assert_called_once_with(
                graphid=pe.SYSTEM_SETTINGS_GRAPH_ID
            )

    def test_get_referenced_person_ids_returns_every_person(self):
        with mock.patch("arches.app.models.models.ResourceInstance") as instance:
            instance.objects.filter.return_value.values_list.return_value = ["p1", "p2"]
            self.assertEqual(pe.get_referenced_person_ids(), {"p1", "p2"})
            instance.objects.filter.assert_called_once_with(graph_id=pe.PERSON_GRAPH_ID)

    def test_get_all_period_ids(self):
        with mock.patch("arches.app.models.models.ResourceInstance") as instance:
            instance.objects.filter.return_value.values_list.return_value = ["x"]
            self.assertEqual(pe.get_all_period_ids(), {"x"})
            instance.objects.filter.assert_called_once_with(graph_id=pe.PERIOD_GRAPH_ID)

    def test_user_filtered_nodegroups_is_empty_without_a_user(self):
        self.assertEqual(pe.get_user_filtered_nodegroups(["r"], None), [])


class OutboundRelationTests(SimpleTestCase):
    def _relation(self, **overrides):
        values = {
            "resourcexid": "x1",
            "from_resource_id": "f",
            "from_resource_graph_id": "fg",
            "to_resource_id": "t",
            "to_resource_graph_id": "tg",
            "relationshiptype": "rt",
            "inverserelationshiptype": "irt",
            "node_id": "n",
            "tile_id": None,
            "notes": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_serialises_relations_and_collects_targets(self):
        with mock.patch.object(pe, "ResourceXResource") as relation_model:
            relation_model.objects.filter.return_value.only.return_value.iterator.return_value = iter(
                [self._relation(), self._relation(to_resource_id="t2", tile_id="tile")]
            )
            relations, diagnostics, targets = pe.get_outbound_relations(["f"])
        relation_model.objects.filter.assert_called_once_with(
            from_resource_id__in=["f"], tile__isnull=False
        )
        self.assertEqual(targets, {"t", "t2"})
        self.assertEqual(diagnostics["candidate_relations"], 2)
        self.assertEqual(diagnostics["target_resources_total"], 2)
        self.assertIsNone(relations[0]["tileid"])
        self.assertEqual(relations[0]["notes"], "")
        self.assertEqual(relations[0]["nodeid"], "n")
        self.assertEqual(relations[1]["tileid"], "tile")

    def test_restricts_to_permitted_nodegroups(self):
        with mock.patch.object(pe, "ResourceXResource") as relation_model:
            relation_model.objects.filter.return_value.only.return_value.iterator.return_value = iter(
                []
            )
            pe.get_outbound_relations(["f"], permitted_nodegroups={"ng"})
        relation_model.objects.filter.assert_called_once_with(
            from_resource_id__in=["f"],
            tile__isnull=False,
            tile__nodegroup_id__in={"ng"},
        )


class BusinessDataFilesTests(SimpleTestCase):
    def test_writes_one_file_per_model_with_its_own_relations(self):
        with (
            tempfile.TemporaryDirectory() as bd_dir,
            mock.patch("arches.app.models.models.GraphModel") as graph_model,
        ):
            graph_model.objects.values_list.return_value = [
                ("g1", {"en": "Heritage Place"}),
                ("g2", "Person"),
            ]
            with pe._BusinessDataFiles(bd_dir, indent=None) as files:
                files.write("g1", {"id": 1})
                files.write("g1", {"id": 2})
                files.write("g2", {"id": 3})
                files.write("g3", {"id": 4})
                files.relations = [
                    {"from_resource_graph": "g1", "n": 1},
                    {"from_resource_graph": "g2", "n": 2},
                ]
            self.assertEqual(
                files.filenames,
                {
                    "g1": "t_heritage_place.json",
                    "g2": "t_person.json",
                    "g3": "t_g3.json",
                },
            )

            def read(name):
                with open(os.path.join(bd_dir, name)) as handle:
                    return json.load(handle)["business_data"]

            place = read("t_heritage_place.json")
            self.assertEqual(place["resources"], [{"id": 1}, {"id": 2}])
            self.assertEqual(
                place["relations"], [{"from_resource_graph": "g1", "n": 1}]
            )
            self.assertEqual(read("t_person.json")["relations"][0]["n"], 2)
            self.assertEqual(read("t_g3.json")["relations"], [])


class PackageTests(SimpleTestCase):
    def _export_dir(self, root):
        out = os.path.join(root, "out")
        os.makedirs(os.path.join(out, "business_data"))
        with open(os.path.join(out, "business_data", "t_x.json"), "w") as handle:
            handle.write("{}")
        return out

    def test_package_export_nests_everything_under_prebuild(self):
        with tempfile.TemporaryDirectory() as root:
            out = self._export_dir(root)
            with mock.patch("tempfile.gettempdir", return_value=root):
                path = pe.package_export(
                    out, archive_name="starches/prebuild/prebuild_test.tar"
                )
            self.assertEqual(path, os.path.join(root, "prebuild_test.tar"))
            with tarfile.open(path) as archive:
                names = archive.getnames()
            self.assertIn("prebuild", names)
            self.assertIn("prebuild/business_data/t_x.json", names)

    def test_package_export_gzips_tgz_names(self):
        with tempfile.TemporaryDirectory() as root:
            out = self._export_dir(root)
            with mock.patch("tempfile.gettempdir", return_value=root):
                path = pe.package_export(out, archive_name="prebuild.tgz")
            with tarfile.open(path, "r:gz") as archive:
                self.assertIn("prebuild/business_data/t_x.json", archive.getnames())


class UploadTests(SimpleTestCase):
    """boto3 is replaced in sys.modules so the tests never need it or the network."""

    def _boto3(self):
        fake = mock.MagicMock()
        patcher = mock.patch.dict(sys.modules, {"boto3": fake})
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_requires_a_bucket_and_key(self):
        self._boto3()
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                pe.upload_artifact("/tmp/a.tar")
            with self.assertRaises(RuntimeError):
                pe.upload_artifact("/tmp/a.tar", bucket="b")

    def test_uploads_with_explicit_bucket_and_key(self):
        boto3 = self._boto3()
        with mock.patch.dict(os.environ, {"AWS_REGION": "ap-southeast-6"}, clear=True):
            url = pe.upload_artifact("/tmp/a.tar", bucket="b", key="k/a.tar")
        boto3.client.assert_called_once_with("s3", region_name="ap-southeast-6")
        boto3.client.return_value.upload_file.assert_called_once_with(
            "/tmp/a.tar", "b", "k/a.tar"
        )
        self.assertEqual(url, "s3://b/k/a.tar")

    def test_falls_back_to_environment_settings(self):
        boto3 = self._boto3()
        env = {"PREBUILD_S3_BUCKET": "env-bucket", "PREBUILD_S3_KEY": "env-key"}
        with mock.patch.dict(os.environ, env, clear=True):
            url = pe.upload_artifact("/tmp/a.tar")
        boto3.client.return_value.upload_file.assert_called_once_with(
            "/tmp/a.tar", "env-bucket", "env-key"
        )
        self.assertEqual(url, "s3://env-bucket/env-key")


def _user_model(users):
    class DoesNotExist(Exception):
        pass

    def get(username):
        try:
            return users[username]
        except KeyError:
            raise DoesNotExist

    model = mock.MagicMock()
    model.DoesNotExist = DoesNotExist
    model.objects.get.side_effect = get
    return model


def _user(groups=(), superuser=False):
    return SimpleNamespace(
        is_superuser=superuser,
        groups=SimpleNamespace(values_list=lambda *args, **kwargs: list(groups)),
    )


class ResolveExportUserTests(SimpleTestCase):
    def _resolve(self, users, *args, **kwargs):
        with mock.patch(
            "django.contrib.auth.get_user_model", return_value=_user_model(users)
        ):
            return pe.resolve_export_user(*args, **kwargs)

    def test_defaults_to_the_anonymous_user(self):
        anonymous = _user()
        user, messages = self._resolve({"anonymous": anonymous})
        self.assertIs(user, anonymous)
        self.assertEqual([level for level, _ in messages], ["info"])

    def test_warns_when_there_is_no_anonymous_user(self):
        user, messages = self._resolve({})
        self.assertIsNone(user)
        self.assertEqual([level for level, _ in messages], ["warning"])

    def test_unknown_user_is_an_error(self):
        with self.assertRaises(ValueError):
            self._resolve({}, "missing")

    def test_superuser_is_an_error(self):
        with self.assertRaises(ValueError):
            self._resolve({"root": _user(superuser=True)}, "root")

    def test_user_in_only_the_expected_group_has_no_warnings(self):
        user = _user(groups=["Public Export"])
        result, messages = self._resolve({"svc": user}, "svc")
        self.assertIs(result, user)
        self.assertEqual(messages, [])

    def test_warns_when_not_in_group_and_when_in_extra_groups(self):
        _, messages = self._resolve({"svc": _user(groups=["Staff"])}, "svc")
        self.assertEqual([level for level, _ in messages], ["warning", "warning"])

        _, messages = self._resolve(
            {"svc": _user(groups=["Public Export", "Staff"])}, "svc"
        )
        self.assertEqual([level for level, _ in messages], ["warning"])
        self.assertIn("Staff", messages[0][1])


class GraphExportTests(SimpleTestCase):
    def test_export_graphs_to_dir_writes_models_branches_and_manifest(self):
        graphs = {
            "graph": [
                {"graphid": "g1", "name": {"en": "Heritage/Place"}, "isresource": True},
                {"graphid": "g2", "name": "Branch", "isresource": False},
            ]
        }
        with (
            tempfile.TemporaryDirectory() as dest,
            mock.patch.object(pe, "get_graphs_for_export", return_value=graphs),
        ):
            names = pe.export_graphs_to_dir(
                ["g1", "g2"], dest, resource_files={"g1": ["t_b.json", "t_a.json"]}
            )
            self.assertEqual(names, ["Heritage/Place", "Branch"])
            self.assertTrue(
                os.path.exists(
                    os.path.join(dest, "graphs/resource_models/Heritage-Place.json")
                )
            )
            self.assertTrue(
                os.path.exists(os.path.join(dest, "graphs/branches/Branch.json"))
            )
            with open(os.path.join(dest, "graphs.json")) as handle:
                manifest = json.load(handle)
        self.assertEqual(
            manifest,
            {
                "models": {
                    "g1": {
                        "name": "Heritage/Place",
                        "resources": ["t_a.json", "t_b.json"],
                    }
                }
            },
        )

    def test_copy_static_package_files_skips_dotfiles_and_missing_entries(self):
        with tempfile.TemporaryDirectory() as root:
            src = os.path.join(root, "pkg")
            dest = os.path.join(root, "dest")
            os.makedirs(os.path.join(src, "indexTemplates"))
            os.makedirs(dest)
            for name in (
                "indexTemplates/a.md",
                "indexTemplates/.gitkeep",
                "prebuild.json",
            ):
                with open(os.path.join(src, name), "w") as handle:
                    handle.write("x")
            with mock.patch.object(pe, "PKG_DIR", src):
                copied = pe.copy_static_package_files(dest)
            self.assertEqual(copied, ["indexTemplates", "prebuild.json"])
            self.assertTrue(
                os.path.exists(os.path.join(dest, "indexTemplates", "a.md"))
            )
            self.assertFalse(
                os.path.exists(os.path.join(dest, "indexTemplates", ".gitkeep"))
            )


class RunPipelineTests(SimpleTestCase):
    def _run(self, ids, export_result, **kwargs):
        with (
            mock.patch.object(
                pe, "get_exportable_resource_ids", return_value=ids
            ) as select,
            mock.patch.object(
                pe, "export_resources", return_value=export_result
            ) as export,
        ):
            result = pe.run_export_pipeline(output_dir="/out", **kwargs)
        return result, select, export

    def test_exports_the_selected_resources(self):
        rid = uuid.UUID(int=7)
        result, select, export = self._run([rid], ("/out", {"k": 1}), states=["Active"])
        select.assert_called_once_with(["Active"])
        export.assert_called_once_with([rid], output_dir="/out", user=None, indent=2)
        self.assertEqual(result["result"], "/out")
        self.assertEqual(result["export_ids"], [str(rid)])
        self.assertEqual(result["diagnostics"], {"k": 1})
        self.assertEqual(result["messages"], [])

    def test_warns_but_still_exports_structure_when_nothing_matches(self):
        result, _, export = self._run([], ("/out", {}))
        export.assert_called_once()
        self.assertEqual(result["result"], "/out")
        self.assertEqual([level for level, _ in result["messages"]], ["warning"])

    def test_reports_an_error_when_the_export_writes_nothing(self):
        result, _, _ = self._run([uuid.UUID(int=1)], (None, None))
        self.assertIsNone(result["result"])
        self.assertEqual([level for level, _ in result["messages"]], ["error"])
