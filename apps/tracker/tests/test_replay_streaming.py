import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.projects.models import Project
from apps.projects.tests.helpers import create_workspace_with_owner
from apps.tracker.models import Event, Session, Visitor
from apps.tracker.replay_streaming import (
    REPLAY_STREAM_CURSOR_SALT,
    REPLAY_STREAM_SEEK_CURSOR_SALT,
)
from apps.tracker.tools import is_valid_rrweb_event


@override_settings(
    REPLAY_STREAM_BOOTSTRAP_WINDOW_SECONDS=5,
    REPLAY_STREAM_BOOTSTRAP_EVENT_LIMIT=100,
    REPLAY_STREAM_BOOTSTRAP_MAX_BYTES=100_000,
    REPLAY_STREAM_CHUNK_WINDOW_SECONDS=60,
    REPLAY_STREAM_CHUNK_EVENT_LIMIT=100,
    REPLAY_STREAM_CHUNK_MAX_BYTES=100_000,
    REPLAY_STREAM_PREFETCH_THRESHOLD_SECONDS=30,
    REPLAY_STREAM_APPEND_BATCH_SIZE=250,
)
class ReplayStreamingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="replay-stream-owner",
            email="replay-stream-owner@example.com",
            password="testpass123",
        )
        self.workspace = create_workspace_with_owner(
            self.user,
            name="Replay stream workspace",
        )
        self.project = Project.objects.create(
            workspace=self.workspace,
            name="Replay stream project",
            created_by=self.user,
            api_key="REPLAY_STREAM_TEST",
            tracking_capture="analytics,recording",
        )
        visitor = Visitor.objects.create(
            project=self.project,
            visitor_guid=uuid.uuid4(),
        )
        self.started_at = timezone.now() - timedelta(hours=1)
        self.session = Session.objects.create(
            visitor=visitor,
            start_time=self.started_at,
            last_activity=self.started_at + timedelta(seconds=131),
            ended_at=self.started_at + timedelta(seconds=131),
        )
        self.client.force_login(self.user)

    def _url(self, route_name="replay_stream", *, session=None):
        return reverse(
            f"w:{route_name}",
            kwargs={
                "workspace_slug": self.workspace.slug,
                "project_id": self.project.id,
                "session_id": (session or self.session).session_id,
            },
        )

    def _event(
        self,
        offset_seconds,
        event_type,
        *,
        tab_id="tab-a",
        data=None,
        marker=None,
        url="https://example.com/dashboard",
        extra=None,
    ):
        timestamp = self.started_at + timedelta(seconds=offset_seconds)
        nested = data
        if nested is None:
            if event_type == 2:
                nested = {
                    "node": {"id": 1, "type": 0, "childNodes": []},
                    "initialOffset": {"left": 0, "top": 0},
                }
            elif event_type == 4:
                nested = {
                    "href": "https://example.com/dashboard",
                    "width": 1440,
                    "height": 900,
                }
            else:
                nested = {"source": 2}
        if marker is not None:
            nested = {**nested, "marker": marker}
        payload = {
            "type": event_type,
            "timestamp": int(timestamp.timestamp() * 1000),
            "data": nested,
        }
        payload.update(extra or {})
        return Event.objects.create(
            session=self.session,
            url=url,
            tab_id=tab_id,
            event_type=event_type,
            timestamp=timestamp,
            data=payload,
        )

    def _proxied_target(self, value):
        return parse_qs(urlparse(value).query)["url"][0]

    def _seed_long_recording(self):
        self._event(0, 4, marker="meta")
        self._event(1, 2, marker="snapshot")
        self._event(4, 3, marker="four")
        self._event(6, 3, marker="six")
        self._event(70, 3, marker="seventy")
        self._event(131, 3, marker="one-thirty-one")

    def _get_data(self, *, cursor=None):
        params = {"cursor": cursor} if cursor else {}
        response = self.client.get(self._url(), params)
        return response, response.json().get("data")

    def _get_seek(self, *, seek_cursor, target_ms):
        response = self.client.get(
            self._url(),
            {"seek_cursor": seek_cursor, "seek_ms": target_ms},
        )
        return response, response.json().get("data")

    def _deferred_event_session_queries(self, captured_queries):
        matches = []
        for query in captured_queries:
            normalized = " ".join(query["sql"].lower().replace('"', "").split())
            if (
                "select tracker_event.id, tracker_event.session_id "
                "from tracker_event where tracker_event.id =" in normalized
            ):
                matches.append(query["sql"])
        return matches

    def test_bootstrap_is_bounded_but_exposes_full_recording_metadata(self):
        self._seed_long_recording()

        response, data = self._get_data()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["protocol_version"], 1)
        self.assertEqual(
            [event["data"].get("marker") for event in data["events"]],
            ["meta", "snapshot", "four", "six"],
        )
        self.assertEqual(data["rrweb_duration"], 131_000)
        self.assertEqual(data["recording_metadata"]["event_count"], 6)
        self.assertEqual(
            data["recording_metadata"]["viewport"],
            {"width": 1440, "height": 900},
        )
        self.assertTrue(data["replay_available"])
        self.assertTrue(data["has_more"])
        self.assertTrue(data["next_cursor"])
        self.assertTrue(data["seek_cursor"])
        self.assertEqual(data["response_kind"], "bootstrap")
        self.assertEqual(data["segment_start_ms"], 0)
        self.assertEqual(data["seekable_from_ms"], 0)
        self.assertNotIn(str(self.session.session_id), data["next_cursor"])
        self.assertEqual(data["loaded_through_ms"], 6_000)
        self.assertEqual(data["stream_config"]["prefetch_threshold_ms"], 30_000)
        self.assertEqual(data["stream_config"]["append_batch_size"], 250)
        self.assertLessEqual(data["chunk"]["event_bytes"], 100_000)

    def test_stream_never_deferred_loads_session_fk_per_event(self):
        self._seed_long_recording()

        with CaptureQueriesContext(connection) as bootstrap_queries:
            bootstrap_response, bootstrap = self._get_data()
        self.assertEqual(bootstrap_response.status_code, 200)
        self.assertEqual(
            self._deferred_event_session_queries(bootstrap_queries),
            [],
        )

        with CaptureQueriesContext(connection) as chunk_queries:
            chunk_response, _ = self._get_data(cursor=bootstrap["next_cursor"])
        self.assertEqual(chunk_response.status_code, 200)
        self.assertEqual(
            self._deferred_event_session_queries(chunk_queries),
            [],
        )

        with CaptureQueriesContext(connection) as seek_queries:
            seek_response, _ = self._get_seek(
                seek_cursor=bootstrap["seek_cursor"],
                target_ms=70_000,
            )
        self.assertEqual(seek_response.status_code, 200)
        self.assertEqual(
            self._deferred_event_session_queries(seek_queries),
            [],
        )

    def test_seek_starts_at_nearest_prior_snapshot_and_prefetches_from_there(self):
        self._event(0, 4, marker="initial-meta")
        self._event(1, 2, marker="initial-snapshot")
        self._event(4, 3, marker="old-activity")
        self._event(60, 4, marker="seek-meta")
        self._event(65, 2, marker="seek-snapshot")
        self._event(66, 3, marker="after-snapshot")
        self._event(70, 3, tab_id="tab-b", marker="target")
        self._event(90, 3, tab_id="tab-b", marker="prefetched")
        self._event(110, 2, tab_id="tab-b", marker="later-snapshot")
        self._event(111, 3, tab_id="tab-b", marker="later-event")
        _, bootstrap = self._get_data()

        response, seek = self._get_seek(
            seek_cursor=bootstrap["seek_cursor"],
            target_ms=70_000,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seek["response_kind"], "seek")
        self.assertEqual(
            [event["data"].get("marker") for event in seek["events"][:2]],
            ["seek-meta", "seek-snapshot"],
        )
        self.assertNotIn(
            "old-activity",
            [event["data"].get("marker") for event in seek["events"]],
        )
        self.assertEqual(seek["segment_start_ms"], 60_000)
        self.assertEqual(seek["seekable_from_ms"], 65_000)
        self.assertEqual(seek["seek_target_ms"], 70_000)
        self.assertEqual(seek["seek_offset_ms"], 10_000)
        self.assertTrue(seek["target_ready"])
        self.assertTrue(seek["chunk"]["initializer_meta_fallback"])
        self.assertEqual(seek["initial_tab_id"], "tab-a")
        self.assertEqual(seek["tab_switches"][0]["from_tab"], "tab-a")
        self.assertEqual(seek["tab_switches"][0]["to_tab"], "tab-b")
        self.assertEqual(seek["seek_cursor"], bootstrap["seek_cursor"])
        if seek["next_cursor"]:
            _, next_chunk = self._get_data(cursor=seek["next_cursor"])
            self.assertEqual(next_chunk["seek_cursor"], bootstrap["seek_cursor"])

    def test_seek_uses_bounded_chunks_when_snapshot_is_far_before_target(self):
        self._event(0, 4)
        self._event(1, 2, marker="only-snapshot")
        for offset in range(10, 301, 10):
            self._event(offset, 3, marker=f"event-{offset}")
        _, bootstrap = self._get_data()

        response, seek = self._get_seek(
            seek_cursor=bootstrap["seek_cursor"],
            target_ms=300_000,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seek["events"][0]["type"], 4)
        self.assertEqual(seek["events"][1]["data"]["marker"], "only-snapshot")
        self.assertLess(seek["loaded_through_ms"], 300_000)
        self.assertFalse(seek["target_ready"])
        self.assertTrue(seek["has_more"])
        self.assertTrue(seek["next_cursor"])

    def test_seek_waits_for_all_events_at_the_target_timestamp(self):
        self._event(0, 4, marker="meta")
        self._event(1, 2, marker="snapshot")
        self._event(70, 3, marker="target-first")
        self._event(70, 3, marker="target-second")
        self._event(100, 3, marker="after-target")
        _, bootstrap = self._get_data()

        response, seek = self._get_seek(
            seek_cursor=bootstrap["seek_cursor"],
            target_ms=70_000,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [event["data"].get("marker") for event in seek["events"]],
            ["meta", "snapshot", "target-first"],
        )
        self.assertEqual(seek["loaded_through_ms"], 70_000)
        self.assertTrue(seek["has_more"])
        self.assertFalse(seek["target_ready"])

        with self.settings(REPLAY_STREAM_CHUNK_EVENT_LIMIT=1):
            _, next_chunk = self._get_data(cursor=seek["next_cursor"])
        self.assertEqual(
            [event["data"].get("marker") for event in next_chunk["events"]],
            ["target-second"],
        )
        self.assertEqual(next_chunk["loaded_through_ms"], 70_000)
        self.assertTrue(next_chunk["has_more"])
        self.assertTrue(next_chunk["target_ready"])

    def test_seek_is_ready_when_only_later_timestamps_remain(self):
        self._event(0, 4, marker="meta")
        self._event(1, 2, marker="snapshot")
        self._event(70, 3, marker="target")
        self._event(100, 3, marker="after-target")
        _, bootstrap = self._get_data()

        response, seek = self._get_seek(
            seek_cursor=bootstrap["seek_cursor"],
            target_ms=70_000,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seek["loaded_through_ms"], 70_000)
        self.assertTrue(seek["has_more"])
        self.assertTrue(seek["target_ready"])

    def test_seek_cursor_preserves_fractional_snapshot_boundary(self):
        self._event(0, 4, marker="meta")
        self._event(5.0005, 2, marker="snapshot")
        self._event(5.0005, 3, marker="target-first")
        self._event(5.0005, 3, marker="target-second")
        self._event(10, 3, marker="after-target")
        _, bootstrap = self._get_data()

        with self.settings(REPLAY_STREAM_CHUNK_EVENT_LIMIT=2):
            response, seek = self._get_seek(
                seek_cursor=bootstrap["seek_cursor"],
                target_ms=0,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seek["seek_target_ms"], 5_000.5)
        self.assertFalse(seek["target_ready"])
        cursor_state = signing.loads(
            seek["next_cursor"],
            salt=REPLAY_STREAM_CURSOR_SALT,
        )
        self.assertEqual(cursor_state["seek_target_ms"], "5000.5")

        with self.settings(REPLAY_STREAM_CHUNK_EVENT_LIMIT=1):
            _, first_chunk = self._get_data(cursor=seek["next_cursor"])
            _, second_chunk = self._get_data(cursor=first_chunk["next_cursor"])

        self.assertEqual(first_chunk["events"][0]["data"]["marker"], "target-first")
        self.assertFalse(first_chunk["target_ready"])
        self.assertEqual(second_chunk["events"][0]["data"]["marker"], "target-second")
        self.assertTrue(second_chunk["target_ready"])

    def test_seek_final_snapshot_includes_real_meta_initializer(self):
        self._event(0, 4, marker="real-meta")
        self._event(1, 2, marker="initial-snapshot")
        self._event(50, 3, marker="discarded-middle")
        self._event(100, 2, marker="final-snapshot")
        _, bootstrap = self._get_data()

        response, seek = self._get_seek(
            seek_cursor=bootstrap["seek_cursor"],
            target_ms=100_000,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [event["data"].get("marker") for event in seek["events"]],
            ["real-meta", "final-snapshot"],
        )
        self.assertEqual(seek["segment_start_ms"], 0)
        self.assertEqual(seek["seekable_from_ms"], 100_000)
        self.assertEqual(seek["seek_offset_ms"], 100_000)
        self.assertTrue(seek["chunk"]["initializer_meta_fallback"])

    def test_seek_final_snapshot_without_meta_has_no_safe_initializer(self):
        self._event(0, 2, marker="prior-snapshot")
        self._event(100, 2, marker="selected-snapshot")
        _, bootstrap = self._get_data()

        response, seek = self._get_seek(
            seek_cursor=bootstrap["seek_cursor"],
            target_ms=100_000,
        )

        self.assertEqual(response.status_code, 422)
        self.assertIsNone(seek)
        self.assertEqual(response.json()["code"], "insufficient_initializer")

    @override_settings(REPLAY_STREAM_CHUNK_MAX_BYTES=4_000)
    def test_seek_retries_with_meta_when_later_event_exceeds_initializer_budget(self):
        self._event(0, 4, marker="initializer-meta")
        self._event(1, 2, marker="selected-snapshot")
        self._event(
            2,
            3,
            data={"source": 0, "large": "x" * 5_000},
            marker="oversized-later-event",
        )
        _, bootstrap = self._get_data()

        response, seek = self._get_seek(
            seek_cursor=bootstrap["seek_cursor"],
            target_ms=1_000,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [event["data"].get("marker") for event in seek["events"]],
            ["initializer-meta", "selected-snapshot"],
        )
        self.assertEqual(seek["chunk"]["initializer_fallback"], "meta")
        self.assertTrue(seek["has_more"])
        self.assertLessEqual(len(response.content), 4_000)

    def test_seek_ignores_a_malformed_nearer_full_snapshot(self):
        self._event(0, 4, marker="valid-meta")
        self._event(0, 2, marker="valid-snapshot")
        self._event(10, 3, marker="valid-event")
        self._event(
            90,
            2,
            data={
                "node": {"id": "bad", "type": "bad", "childNodes": []},
                "initialOffset": {"left": 0, "top": 0},
            },
            marker="malformed-snapshot",
        )
        self._event(100, 3, marker="recording-end")
        _, bootstrap = self._get_data()

        response, seek = self._get_seek(
            seek_cursor=bootstrap["seek_cursor"],
            target_ms=95_000,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [event["data"].get("marker") for event in seek["events"][:2]],
            ["valid-meta", "valid-snapshot"],
        )
        self.assertNotIn(
            "malformed-snapshot",
            [event["data"].get("marker") for event in seek["events"]],
        )

    def test_seek_returns_the_prior_meta_used_for_url_context(self):
        self._event(0, 4)
        self._event(1, 2)
        self._event(
            60,
            4,
            data={
                "href": "https://seek.example/app/page",
                "width": 1280,
                "height": 720,
            },
            url="https://old.example/original",
        )
        self._event(
            65,
            2,
            data={
                "node": {
                    "id": 10,
                    "type": 2,
                    "tagName": "img",
                    "attributes": {"src": "./seek.png"},
                    "childNodes": [],
                },
                "initialOffset": {"left": 0, "top": 0},
            },
            marker="seek-snapshot",
            url="https://old.example/original",
        )
        self._event(70, 3)
        _, bootstrap = self._get_data()

        _, seek = self._get_seek(
            seek_cursor=bootstrap["seek_cursor"],
            target_ms=65_000,
        )

        self.assertEqual([event["type"] for event in seek["events"][:2]], [4, 2])
        snapshot_src = seek["events"][1]["data"]["node"]["attributes"]["src"]
        self.assertEqual(
            self._proxied_target(snapshot_src),
            "https://seek.example/app/seek.png",
        )

    def test_seek_cursor_freezes_high_water_and_is_bound_to_recording(self):
        self._event(0, 4)
        self._event(1, 2, marker="frozen-snapshot")
        self._event(100, 3, marker="frozen-end")
        _, bootstrap = self._get_data()
        self._event(90, 2, marker="late-snapshot")
        self._event(91, 3, marker="late-event")

        _, seek = self._get_seek(
            seek_cursor=bootstrap["seek_cursor"],
            target_ms=95_000,
        )

        markers = [event["data"].get("marker") for event in seek["events"]]
        self.assertEqual(markers[1], "frozen-snapshot")
        self.assertNotIn("late-snapshot", markers)
        seek_state = signing.loads(
            bootstrap["seek_cursor"],
            salt=REPLAY_STREAM_SEEK_CURSOR_SALT,
        )
        self.assertNotIn("http", str(seek_state).lower())

        replacement = "x" if bootstrap["seek_cursor"][-1] != "x" else "y"
        response, _ = self._get_seek(
            seek_cursor=f"{bootstrap['seek_cursor'][:-1]}{replacement}",
            target_ms=95_000,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_seek_cursor")

        other_session = Session.objects.create(
            visitor=self.session.visitor,
            start_time=self.started_at - timedelta(days=1),
            last_activity=self.started_at - timedelta(days=1),
            ended_at=self.started_at - timedelta(days=1) + timedelta(minutes=1),
        )
        mismatched = self.client.get(
            self._url(session=other_session),
            {"seek_cursor": bootstrap["seek_cursor"], "seek_ms": 95_000},
        )
        self.assertEqual(mismatched.status_code, 400)
        self.assertEqual(mismatched.json()["code"], "invalid_seek_cursor")

    def test_seek_before_first_snapshot_clamps_to_first_reconstruction_point(self):
        self._event(0, 4)
        self._event(5, 2, marker="first-snapshot")
        self._event(6, 3, marker="after-first")
        _, bootstrap = self._get_data()

        _, seek = self._get_seek(
            seek_cursor=bootstrap["seek_cursor"],
            target_ms=0,
        )

        self.assertEqual(seek["events"][0]["type"], 4)
        self.assertEqual(seek["events"][1]["data"]["marker"], "first-snapshot")
        self.assertEqual(seek["seek_target_ms"], 5_000)
        self.assertEqual(seek["segment_start_ms"], 0)
        self.assertEqual(seek["seek_offset_ms"], 5_000)

    def test_seek_rejects_missing_token_invalid_target_and_mixed_cursors(self):
        self._seed_long_recording()
        _, bootstrap = self._get_data()

        missing_token = self.client.get(self._url(), {"seek_ms": 70_000})
        self.assertEqual(missing_token.status_code, 400)
        self.assertEqual(missing_token.json()["code"], "invalid_seek_cursor")

        for invalid_target in ("-1", "nan", "1e1000000000"):
            response, _ = self._get_seek(
                seek_cursor=bootstrap["seek_cursor"],
                target_ms=invalid_target,
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["code"], "invalid_seek_target")

        mixed = self.client.get(
            self._url(),
            {
                "cursor": bootstrap["next_cursor"],
                "seek_cursor": bootstrap["seek_cursor"],
                "seek_ms": 70_000,
            },
        )
        self.assertEqual(mixed.status_code, 400)
        self.assertEqual(mixed.json()["code"], "invalid_seek_request")

    def test_chunks_use_one_global_clock_and_include_sparse_window_boundary(self):
        self._seed_long_recording()
        _, bootstrap = self._get_data()

        response, chunk = self._get_data(cursor=bootstrap["next_cursor"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [event["timestamp"] for event in chunk["events"]],
            [70_000, 131_000],
        )
        self.assertEqual(
            [event["data"]["marker"] for event in chunk["events"]],
            ["seventy", "one-thirty-one"],
        )
        self.assertFalse(chunk["has_more"])
        self.assertIsNone(chunk["next_cursor"])
        self.assertEqual(chunk["loaded_through_ms"], 131_000)

    @override_settings(
        REPLAY_STREAM_BOOTSTRAP_EVENT_LIMIT=2,
        REPLAY_STREAM_CHUNK_EVENT_LIMIT=1,
        REPLAY_STREAM_BOOTSTRAP_WINDOW_SECONDS=500,
        REPLAY_STREAM_CHUNK_WINDOW_SECONDS=500,
    )
    def test_same_timestamp_events_cross_count_boundaries_in_id_order(self):
        self._event(0, 4, marker="meta")
        self._event(0, 2, marker="snapshot")
        self._event(1, 3, marker="first")
        self._event(1, 3, marker="second")
        self._event(1, 3, marker="third")

        _, payload = self._get_data()
        markers = [event["data"].get("marker") for event in payload["events"]]
        cursor = payload["next_cursor"]
        while cursor:
            response, payload = self._get_data(cursor=cursor)
            self.assertEqual(response.status_code, 200)
            markers.extend(event["data"].get("marker") for event in payload["events"])
            cursor = payload["next_cursor"]

        self.assertEqual(markers, ["meta", "snapshot", "first", "second", "third"])

    def test_cursor_high_watermark_excludes_events_inserted_after_bootstrap(self):
        self._seed_long_recording()
        _, bootstrap = self._get_data()
        self._event(200, 3, marker="late-after-bootstrap")

        _, chunk = self._get_data(cursor=bootstrap["next_cursor"])

        self.assertNotIn(
            "late-after-bootstrap",
            [event["data"].get("marker") for event in chunk["events"]],
        )
        self.assertFalse(chunk["has_more"])

    def test_tab_switch_state_continues_across_chunk_boundaries(self):
        self._event(0, 4)
        self._event(1, 2)
        self._event(4, 3, tab_id="tab-a")
        self._event(6, 3, tab_id="tab-b")
        self._event(70, 3, tab_id="tab-a")
        _, bootstrap = self._get_data()

        self.assertEqual(
            bootstrap["tab_switches"],
            [{
                "from_tab": "tab-a",
                "to_tab": "tab-b",
                "timestamp": 6_000,
                "absolute_timestamp": bootstrap["session_start_time"] + 6_000,
            }],
        )
        _, chunk = self._get_data(cursor=bootstrap["next_cursor"])
        self.assertEqual(chunk["tab_switches"][0]["from_tab"], "tab-b")
        self.assertEqual(chunk["tab_switches"][0]["to_tab"], "tab-a")

    def test_historical_meta_href_resolves_relative_assets_in_bootstrap(self):
        self._event(
            0,
            4,
            tab_id="",
            data={
                "href": "https://new.example/app/page",
                "width": 1440,
                "height": 900,
            },
            url="https://old.example/original",
        )
        self._event(
            1,
            2,
            tab_id="",
            data={
                "node": {
                    "id": 1,
                    "type": 2,
                    "tagName": "img",
                    "attributes": {"src": "./image.png"},
                    "childNodes": [],
                },
                "initialOffset": {"left": 0, "top": 0},
            },
            url="https://old.example/original",
        )

        _, bootstrap = self._get_data()

        snapshot_src = bootstrap["events"][1]["data"]["node"]["attributes"]["src"]
        self.assertEqual(
            self._proxied_target(snapshot_src),
            "https://new.example/app/image.png",
        )

    @override_settings(
        REPLAY_STREAM_BOOTSTRAP_EVENT_LIMIT=2,
        REPLAY_STREAM_BOOTSTRAP_WINDOW_SECONDS=500,
        REPLAY_STREAM_CHUNK_EVENT_LIMIT=1,
        REPLAY_STREAM_CHUNK_WINDOW_SECONDS=500,
    )
    def test_historical_meta_href_continues_across_chunk_boundaries(self):
        self._event(
            0,
            4,
            tab_id="",
            data={
                "href": "https://new.example/app/page",
                "width": 1440,
                "height": 900,
            },
            url="https://old.example/original",
        )
        self._event(1, 2, tab_id="", url="https://old.example/original")
        self._event(
            2,
            3,
            tab_id="",
            data={
                "source": 0,
                "adds": [{
                    "parentId": 1,
                    "nextId": None,
                    "node": {
                        "id": 2,
                        "type": 2,
                        "tagName": "img",
                        "attributes": {"src": "./later.png"},
                        "childNodes": [],
                    },
                }],
                "removes": [],
                "texts": [],
                "attributes": [],
            },
            url="https://old.example/original",
        )

        _, bootstrap = self._get_data()
        _, chunk = self._get_data(cursor=bootstrap["next_cursor"])

        mutation_src = chunk["events"][0]["data"]["adds"][0]["node"]["attributes"]["src"]
        self.assertEqual(
            self._proxied_target(mutation_src),
            "https://new.example/app/later.png",
        )

    @override_settings(
        REPLAY_STREAM_BOOTSTRAP_EVENT_LIMIT=19,
        REPLAY_STREAM_BOOTSTRAP_WINDOW_SECONDS=500,
        REPLAY_STREAM_CHUNK_EVENT_LIMIT=1,
        REPLAY_STREAM_CHUNK_WINDOW_SECONDS=500,
    )
    def test_invalid_later_meta_does_not_hide_prior_cross_chunk_context(self):
        self._event(
            0,
            4,
            data={
                "href": "https://valid.example/app/page",
                "width": 1440,
                "height": 900,
            },
        )
        for offset in range(1, 18):
            self._event(
                offset,
                4,
                data={"href": "https://[", "width": 1440, "height": 900},
            )
        self._event(18, 2)
        self._event(
            19,
            3,
            data={
                "source": 0,
                "adds": [{
                    "parentId": 1,
                    "nextId": None,
                    "node": {
                        "id": 2,
                        "type": 2,
                        "tagName": "img",
                        "attributes": {"src": "./after-invalid.png"},
                        "childNodes": [],
                    },
                }],
                "removes": [],
                "texts": [],
                "attributes": [],
            },
            url="https://old.example/original",
        )

        _, bootstrap = self._get_data()
        _, chunk = self._get_data(cursor=bootstrap["next_cursor"])

        mutation_src = chunk["events"][0]["data"]["adds"][0]["node"]["attributes"]["src"]
        self.assertEqual(
            self._proxied_target(mutation_src),
            "https://valid.example/app/after-invalid.png",
        )

    def test_explicit_event_url_supersedes_historical_meta_context(self):
        self._event(
            0,
            4,
            data={
                "href": "https://meta.example/app/page",
                "width": 1440,
                "height": 900,
            },
        )
        self._event(
            1,
            2,
            data={
                "node": {
                    "id": 1,
                    "type": 2,
                    "tagName": "img",
                    "attributes": {"src": "./current.png"},
                    "childNodes": [],
                },
                "initialOffset": {"left": 0, "top": 0},
            },
            extra={"_hymetry_page_url": "https://explicit.example/route/page"},
        )

        _, bootstrap = self._get_data()

        snapshot_src = bootstrap["events"][1]["data"]["node"]["attributes"]["src"]
        self.assertEqual(
            self._proxied_target(snapshot_src),
            "https://explicit.example/route/current.png",
        )

    def test_cursor_contains_state_ids_but_no_recorded_urls(self):
        self._seed_long_recording()
        _, bootstrap = self._get_data()

        cursor_state = signing.loads(
            bootstrap["next_cursor"],
            salt=REPLAY_STREAM_CURSOR_SALT,
        )
        serialized_state = str(cursor_state)

        self.assertIn("after_event_id", cursor_state)
        self.assertNotIn("http://", serialized_state)
        self.assertNotIn("https://", serialized_state)
        self.assertNotIn("meta", serialized_state.lower())

    def test_malformed_or_mismatched_rows_do_not_shift_stream_metadata(self):
        Event.objects.create(
            session=self.session,
            url="https://invalid.example",
            tab_id="tab-a",
            event_type=4,
            timestamp=self.started_at,
            data=["not", "an", "event"],
        )
        Event.objects.create(
            session=self.session,
            url="https://invalid.example",
            tab_id="tab-a",
            event_type=4,
            timestamp=self.started_at + timedelta(seconds=1),
            data={"type": 3, "data": {"source": 2}},
        )
        self._event(10, 4)
        self._event(11, 2)
        self._event(12, 3)

        _, bootstrap = self._get_data()

        self.assertFalse(is_valid_rrweb_event(["not", "an", "event"]))
        self.assertEqual(bootstrap["recording_metadata"]["event_count"], 3)
        self.assertEqual(bootstrap["rrweb_duration"], 2_000)
        self.assertEqual(
            bootstrap["session_start_time"],
            round((self.started_at + timedelta(seconds=10)).timestamp() * 1000, 3),
        )

    @override_settings(
        REPLAY_STREAM_BOOTSTRAP_EVENT_LIMIT=2,
        REPLAY_STREAM_BOOTSTRAP_WINDOW_SECONDS=500,
        REPLAY_STREAM_CHUNK_EVENT_LIMIT=100,
        REPLAY_STREAM_CHUNK_WINDOW_SECONDS=500,
        REPLAY_STREAM_CHUNK_MAX_BYTES=4_000,
    )
    def test_chunk_ceiling_reserves_space_for_sidecars_and_response_envelope(self):
        self._event(0, 4)
        self._event(1, 2)
        for index in range(2, 32):
            self._event(
                index,
                3,
                tab_id=f"tab-{index % 2}",
                marker=f"activity-{index}",
            )

        _, bootstrap = self._get_data()
        response, chunk = self._get_data(cursor=bootstrap["next_cursor"])

        self.assertLessEqual(chunk["chunk"]["payload_bytes"], 4_000)
        self.assertLessEqual(len(response.content), 4_000)
        self.assertNotIn(b'": ', response.content)
        self.assertNotIn(b'", "', response.content)
        self.assertGreater(chunk["chunk"]["sidecar_bytes"], 0)

    def test_tampered_cursor_is_rejected_without_exposing_signing_details(self):
        self._seed_long_recording()
        _, bootstrap = self._get_data()
        cursor = bootstrap["next_cursor"]

        replacement = "x" if cursor[-1] != "x" else "y"
        response, data = self._get_data(cursor=f"{cursor[:-1]}{replacement}")

        self.assertEqual(response.status_code, 400)
        self.assertIsNone(data)
        self.assertEqual(response.json()["code"], "invalid_cursor")
        self.assertEqual(response.json()["error"], "The replay cursor is invalid.")

    def test_cursor_is_bound_to_the_recording_in_the_authorized_url(self):
        self._seed_long_recording()
        _, bootstrap = self._get_data()
        other_session = Session.objects.create(
            visitor=self.session.visitor,
            start_time=self.started_at - timedelta(days=1),
            last_activity=self.started_at - timedelta(days=1),
            ended_at=self.started_at - timedelta(days=1) + timedelta(minutes=1),
        )

        response = self.client.get(
            self._url(session=other_session),
            {"cursor": bootstrap["next_cursor"]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_cursor")

    @override_settings(REPLAY_STREAM_BOOTSTRAP_MAX_BYTES=300)
    def test_initializer_byte_ceiling_returns_typed_compatibility_error(self):
        self._event(0, 4)
        self._event(
            1,
            2,
            data={
                "node": {"id": 1, "type": 0, "childNodes": []},
                "initialOffset": {"left": 0, "top": 0},
                "large": "x" * 1_000,
            },
        )

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "initializer_too_large")

    def test_missing_snapshot_is_an_explicit_unavailable_bootstrap(self):
        self._event(0, 4)
        self._event(1, 3)

        response, data = self._get_data()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["replay_available"])
        self.assertEqual(data["replay_unavailable_reason"], "missing_full_snapshot")
        self.assertEqual(data["events"], [])
        self.assertFalse(data["has_more"])

    def test_stream_reauthorizes_project_and_legacy_data_endpoint_remains_full(self):
        self._seed_long_recording()
        legacy_response = self.client.get(self._url("get_consolidated_data"))
        self.assertEqual(legacy_response.status_code, 200)
        self.assertEqual(len(legacy_response.json()["data"]["events"]), 6)

        other_user = get_user_model().objects.create_user(
            username="other-replay-user",
            email="other-replay-user@example.com",
            password="testpass123",
        )
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(self._url()).status_code, 403)
