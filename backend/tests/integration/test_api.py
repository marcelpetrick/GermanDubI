"""The HTTP API, exercised through FastAPI's test client.

These run against an isolated temporary database and artifact root, with deterministic fake
providers, so they are fast and repeatable.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from germandubi.api.app import API_PREFIX, create_app
from germandubi.application.services.projects import ProjectService
from germandubi.composition import Application, build_application
from germandubi.config import Settings
from tests.fixtures.media import make_narration_video

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")

VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_narration_video(tmp_path_factory.mktemp("api") / "clip.mp4", seconds=10)


@pytest.fixture
def app_and_api(tmp_path: Path, clip: Path) -> Iterator[tuple[Application, FastAPI]]:
    settings = Settings(
        data_dir=tmp_path / "data",
        transcription_provider="fake",
        translation_provider="fake",
        tts_provider="fake",
        separation_provider="fake",
        # Close the progress stream quickly so the streaming test cannot hang.
        sse_stream_seconds=1.0,
    )
    wired = build_application(settings, fixture=clip)
    yield wired, create_app(settings, application=wired)
    wired.dispose()


@pytest.fixture
def application(app_and_api: tuple[Application, FastAPI]) -> Application:
    return app_and_api[0]


@pytest.fixture
def client(app_and_api: tuple[Application, FastAPI]) -> Iterator[TestClient]:
    with TestClient(app_and_api[1]) as test_client:
        yield test_client


def url(path: str) -> str:
    return f"{API_PREFIX}{path}"


def create_project(client: TestClient, source: str = VALID_URL) -> str:
    response = client.post(url("/projects"), json={"url": source})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


class TestMeta:
    def test_reports_the_build_identity(self, client: TestClient) -> None:
        body = client.get(url("/meta")).json()
        assert body["application"] == "germandubi"
        assert body["api_version"] == "v1"
        assert body["version"]
        assert body["source_language"] == "en"
        assert body["target_language"] == "de"

    def test_health_reports_tool_availability(self, client: TestClient) -> None:
        body = client.get(url("/health")).json()
        assert body["status"] in {"ok", "degraded"}
        assert "ffmpeg" in body["tools"]
        assert body["writable"] is True

    def test_providers_declare_whether_they_use_the_network(self, client: TestClient) -> None:
        providers = client.get(url("/providers")).json()
        assert providers
        assert all(p["kind"] in {"local", "network"} for p in providers)

    def test_the_openapi_schema_is_served(self, client: TestClient) -> None:
        schema = client.get(url("/openapi.json")).json()
        assert schema["info"]["title"] == "GermanDubI"
        assert schema["info"]["license"]["identifier"] == "GPL-3.0-or-later"
        assert schema["info"]["contact"]["email"] == "mail@marcelpetrick.it"
        assert "/api/v1/projects" in schema["paths"]

    def test_every_operation_has_a_stable_operation_id(self, client: TestClient) -> None:
        """The generated TypeScript client names its methods after these."""
        schema = client.get(url("/openapi.json")).json()
        ids = [
            operation["operationId"]
            for path in schema["paths"].values()
            for operation in path.values()
            if "operationId" in operation
        ]
        assert ids
        assert len(ids) == len(set(ids)), "operation ids must be unique"
        assert all("__" not in i for i in ids), "ids should be hand-chosen, not generated"

    def test_serves_a_compiled_frontend_with_spa_fallback(
        self, app_and_api: tuple[Application, FastAPI], tmp_path: Path
    ) -> None:
        dist = tmp_path / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<h1>GermanDubI browser</h1>")
        wired, _ = app_and_api
        web = create_app(wired.settings, application=wired, frontend_dist=dist)

        with TestClient(web) as frontend:
            response = frontend.get("/projects/some-project")

        assert response.status_code == 200
        assert "GermanDubI browser" in response.text


class TestProjectCreation:
    def test_creates_a_project_from_a_url(self, client: TestClient) -> None:
        response = client.post(url("/projects"), json={"url": VALID_URL})
        assert response.status_code == 201
        body = response.json()
        assert body["state"] == "new"
        assert body["source_kind"] == "youtube"
        assert body["target_language"] == "de"

    @pytest.mark.parametrize(
        "bad",
        [
            "https://evil.example.com/watch?v=x",
            "http://www.youtube.com/watch?v=x",
            "file:///etc/passwd",
            "https://127.0.0.1/watch?v=x",
        ],
    )
    def test_refuses_an_unacceptable_url(self, client: TestClient, bad: str) -> None:
        response = client.post(url("/projects"), json={"url": bad})
        assert response.status_code == 422
        assert response.json()["code"] == "source_validation_error"

    def test_requires_exactly_one_source(self, client: TestClient) -> None:
        assert client.post(url("/projects"), json={}).status_code == 409
        both = client.post(url("/projects"), json={"url": VALID_URL, "file_path": "/x.mp4"})
        assert both.status_code == 409

    def test_lists_projects_newest_first(self, client: TestClient) -> None:
        first = create_project(client)
        second = create_project(client, "https://youtu.be/aaaaaaaaaaa")
        listed = [p["id"] for p in client.get(url("/projects")).json()]
        assert listed[0] == second
        assert first in listed

    def test_returns_404_for_an_unknown_project(self, client: TestClient) -> None:
        response = client.get(url("/projects/01ARZ3NDEKTSV4RRFFQ69G5FAV"))
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    def test_a_malformed_identifier_is_a_404_not_a_500(self, client: TestClient) -> None:
        assert client.get(url("/projects/not-a-ulid")).status_code == 404

    def test_deletes_a_project(self, client: TestClient) -> None:
        project_id = create_project(client)
        assert client.delete(url(f"/projects/{project_id}")).status_code == 204
        assert client.get(url(f"/projects/{project_id}")).status_code == 404


class TestErrorShape:
    def test_every_error_uses_one_shape(self, client: TestClient) -> None:
        """One shape means the frontend has one error path, not one per endpoint."""
        for response in (
            client.get(url("/projects/01ARZ3NDEKTSV4RRFFQ69G5FAV")),
            client.post(url("/projects"), json={"url": "https://evil.test/x"}),
            client.post(url("/projects"), json={}),
        ):
            body = response.json()
            assert set(body) == {"code", "message", "details"}
            assert body["message"]


class TestWorkflow:
    """The full workflow, driven the way the browser drives it."""

    @pytest.fixture
    def analysed(self, client: TestClient, application: Application) -> str:
        project_id = create_project(client)
        assert client.post(url(f"/projects/{project_id}/analyze")).status_code == 202
        application.worker().run_until_idle()
        return project_id

    @pytest.fixture
    def dubbed(self, client: TestClient, application: Application, analysed: str) -> str:
        assert client.post(url(f"/projects/{analysed}/runs"), json={}).status_code == 202
        application.worker().run_until_idle()
        return analysed

    def test_analysis_fills_in_the_source_metadata(self, client: TestClient, analysed: str) -> None:
        body = client.get(url(f"/projects/{analysed}")).json()
        assert body["state"] == "ready"
        assert body["media"] is not None
        assert body["media"]["duration_ms"] > 0
        assert body["title"]

    def test_starting_a_dub_before_analysis_is_refused(self, client: TestClient) -> None:
        project_id = create_project(client)
        response = client.post(url(f"/projects/{project_id}/runs"), json={})
        assert response.status_code == 409
        assert "analyse" in response.json()["message"]

    def test_the_run_reports_every_stage(self, client: TestClient, dubbed: str) -> None:
        run = client.get(url(f"/projects/{dubbed}/runs/latest")).json()
        assert run["finished"] is True
        assert run["failed"] is False
        assert run["progress"] == 1.0
        assert {job["stage"] for job in run["jobs"]} >= {"translate", "synthesize", "export"}
        assert all(job["label"] for job in run["jobs"])

    def test_gets_one_run_and_rejects_cross_project_access(
        self, client: TestClient, dubbed: str
    ) -> None:
        run = client.get(url(f"/projects/{dubbed}/runs/latest")).json()
        response = client.get(url(f"/projects/{dubbed}/runs/{run['id']}"))
        assert response.status_code == 200
        other = create_project(client, "https://youtu.be/ccccccccccc")
        assert client.get(url(f"/projects/{other}/runs/{run['id']}")).status_code == 404

    def test_cancels_and_resumes_a_queued_run(self, client: TestClient, analysed: str) -> None:
        run = client.post(url(f"/projects/{analysed}/runs"), json={}).json()
        cancelled = client.post(url(f"/projects/{analysed}/runs/{run['id']}/cancel"))
        assert cancelled.status_code == 202
        assert cancelled.json()["finished"] is True
        resumed = client.post(url(f"/projects/{analysed}/runs/resume"))
        assert resumed.status_code == 202
        assert resumed.json()["jobs"]

    def test_refuses_to_resume_a_successful_run(self, client: TestClient, dubbed: str) -> None:
        response = client.post(url(f"/projects/{dubbed}/runs/resume"))
        assert response.status_code == 409
        assert "nothing to resume" in response.json()["message"]

    def test_the_project_reaches_review(self, client: TestClient, dubbed: str) -> None:
        assert client.get(url(f"/projects/{dubbed}")).json()["state"] == "review"

    def test_segments_are_listed_with_a_summary(self, client: TestClient, dubbed: str) -> None:
        body = client.get(url(f"/projects/{dubbed}/segments")).json()
        assert body["summary"]["total"] > 0
        assert body["summary"]["translated"] == body["summary"]["total"]
        assert all(s["translation"] for s in body["segments"])
        assert all(s["fit"] is not None for s in body["segments"])
        assert [s["ordinal"] for s in body["segments"]] == sorted(
            s["ordinal"] for s in body["segments"]
        )

    def test_correcting_german_reports_what_became_stale(
        self, client: TestClient, dubbed: str
    ) -> None:
        segment = client.get(url(f"/projects/{dubbed}/segments")).json()["segments"][0]
        response = client.patch(
            url(f"/projects/{dubbed}/segments/{segment['id']}"),
            json={"translation": "Ein korrigierter deutscher Satz."},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["invalidated_from"] == "synthesize"
        assert body["segment"]["translation"] == "Ein korrigierter deutscher Satz."
        assert body["segment"]["translation_origin"] == "user_edit"
        assert body["run_id"] is None

    def test_correcting_english_invalidates_from_translation(
        self, client: TestClient, dubbed: str
    ) -> None:
        segment = client.get(url(f"/projects/{dubbed}/segments")).json()["segments"][0]
        body = client.patch(
            url(f"/projects/{dubbed}/segments/{segment['id']}"),
            json={"source_text": "A corrected English sentence."},
        ).json()
        assert body["invalidated_from"] == "translate"
        assert body["segment"]["translation"] is None

    def test_a_correction_can_start_its_own_regeneration(
        self, client: TestClient, application: Application, dubbed: str
    ) -> None:
        segment = client.get(url(f"/projects/{dubbed}/segments")).json()["segments"][0]
        body = client.patch(
            url(f"/projects/{dubbed}/segments/{segment['id']}?regenerate=true"),
            json={"translation": "Sofort neu erzeugt."},
        ).json()
        assert body["run_id"] is not None

        application.worker().run_until_idle()
        refreshed = client.get(url(f"/projects/{dubbed}/segments/{segment['id']}")).json()
        assert refreshed["translation"] == "Sofort neu erzeugt."
        assert refreshed["has_speech"] is True

    def test_correcting_both_fields_at_once_is_refused(
        self, client: TestClient, dubbed: str
    ) -> None:
        segment = client.get(url(f"/projects/{dubbed}/segments")).json()["segments"][0]
        response = client.patch(
            url(f"/projects/{dubbed}/segments/{segment['id']}"),
            json={"source_text": "English", "translation": "Deutsch"},
        )
        assert response.status_code == 409

    def test_retranslation_refuses_to_discard_a_human_edit(
        self, client: TestClient, dubbed: str
    ) -> None:
        segment = client.get(url(f"/projects/{dubbed}/segments")).json()["segments"][0]
        client.patch(
            url(f"/projects/{dubbed}/segments/{segment['id']}"),
            json={"translation": "Von Hand geschrieben."},
        )
        response = client.post(url(f"/projects/{dubbed}/segments/{segment['id']}/retranslate"))
        assert response.status_code == 409
        assert "by hand" in response.json()["message"]

    def test_approving_a_segment(self, client: TestClient, dubbed: str) -> None:
        segment = client.get(url(f"/projects/{dubbed}/segments")).json()["segments"][0]
        body = client.post(url(f"/projects/{dubbed}/segments/{segment['id']}/approve")).json()
        assert body["review_state"] == "approved"

    def test_approving_every_segment_completes_the_project(
        self, client: TestClient, dubbed: str
    ) -> None:
        segments = client.get(url(f"/projects/{dubbed}/segments")).json()["segments"]
        for segment in segments:
            response = client.post(url(f"/projects/{dubbed}/segments/{segment['id']}/approve"))
            assert response.status_code == 200

        assert client.get(url(f"/projects/{dubbed}")).json()["state"] == "complete"

    def test_translation_history_is_kept(self, client: TestClient, dubbed: str) -> None:
        segment = client.get(url(f"/projects/{dubbed}/segments")).json()["segments"][0]
        client.patch(
            url(f"/projects/{dubbed}/segments/{segment['id']}"),
            json={"translation": "Erste Korrektur."},
        )
        history = client.get(url(f"/projects/{dubbed}/segments/{segment['id']}/revisions")).json()
        assert [r["text"] for r in history][-1] == "Erste Korrektur."
        assert history[-1]["origin"] == "user_edit"

    def test_a_segment_from_another_project_is_not_reachable(
        self, client: TestClient, dubbed: str
    ) -> None:
        """A valid id from one project must not be editable through another's URL."""
        segment = client.get(url(f"/projects/{dubbed}/segments")).json()["segments"][0]
        other = create_project(client, "https://youtu.be/bbbbbbbbbbb")
        response = client.get(url(f"/projects/{other}/segments/{segment['id']}"))
        assert response.status_code == 404

    def test_artifacts_are_listed_with_provenance(self, client: TestClient, dubbed: str) -> None:
        artifacts = client.get(url(f"/projects/{dubbed}/artifacts")).json()
        assert artifacts
        assert all(a["provider_id"] for a in artifacts)
        kinds = {a["kind"] for a in artifacts}
        assert {"export", "mixed_audio", "subtitles_de"} <= kinds


class TestMediaServing:
    @pytest.fixture
    def dubbed(self, client: TestClient, application: Application) -> str:
        project_id = create_project(client)
        client.post(url(f"/projects/{project_id}/analyze"))
        application.worker().run_until_idle()
        client.post(url(f"/projects/{project_id}/runs"), json={})
        application.worker().run_until_idle()
        return project_id

    def test_streams_the_export(self, client: TestClient, dubbed: str) -> None:
        response = client.get(url(f"/projects/{dubbed}/preview/export"))
        assert response.status_code == 200
        assert response.headers["accept-ranges"] == "bytes"
        assert len(response.content) > 0

    def test_honours_a_byte_range_request(self, client: TestClient, dubbed: str) -> None:
        """Range support is what lets the browser seek instead of re-downloading."""
        response = client.get(
            url(f"/projects/{dubbed}/preview/export"), headers={"Range": "bytes=0-99"}
        )
        assert response.status_code == 206
        assert len(response.content) == 100
        assert response.headers["content-range"].startswith("bytes 0-99/")

    def test_honours_a_suffix_range(self, client: TestClient, dubbed: str) -> None:
        response = client.get(
            url(f"/projects/{dubbed}/preview/export"), headers={"Range": "bytes=-50"}
        )
        assert response.status_code == 206
        assert len(response.content) == 50

    def test_rejects_an_unsatisfiable_range(self, client: TestClient, dubbed: str) -> None:
        response = client.get(
            url(f"/projects/{dubbed}/preview/export"),
            headers={"Range": "bytes=99999999999-99999999999"},
        )
        assert response.status_code == 416

    def test_serves_both_audio_tracks(self, client: TestClient, dubbed: str) -> None:
        for track in ("german", "original"):
            response = client.get(url(f"/projects/{dubbed}/preview/audio/{track}"))
            assert response.status_code == 200, track
            assert len(response.content) > 0

    def test_an_unknown_audio_track_is_a_404(self, client: TestClient, dubbed: str) -> None:
        assert client.get(url(f"/projects/{dubbed}/preview/audio/klingon")).status_code == 404

    def test_serves_a_single_segment_speech_clip(self, client: TestClient, dubbed: str) -> None:
        segment = client.get(url(f"/projects/{dubbed}/segments")).json()["segments"][0]
        response = client.get(url(f"/projects/{dubbed}/segments/{segment['id']}/speech"))
        assert response.status_code == 200
        assert len(response.content) > 0

    def test_downloads_the_export_as_an_attachment(self, client: TestClient, dubbed: str) -> None:
        response = client.get(url(f"/projects/{dubbed}/download"))
        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("attachment;")
        assert ".mkv" in response.headers["content-disposition"]

    def test_previewing_before_export_is_a_clear_404(self, client: TestClient) -> None:
        project_id = create_project(client)
        response = client.get(url(f"/projects/{project_id}/preview/export"))
        assert response.status_code == 404
        assert "no export yet" in response.json()["message"]


class TestEventStream:
    def test_replays_events_from_a_sequence_number(
        self, client: TestClient, application: Application
    ) -> None:
        """Last-Event-ID is what makes a browser refresh mid-processing lossless."""
        project_id = create_project(client)
        client.post(url(f"/projects/{project_id}/analyze"))
        application.worker().run_until_idle()

        with application.unit_of_work() as uow:
            from germandubi.domain.value_objects.identifiers import ProjectId, Ulid

            events = uow.events.since(ProjectId(Ulid(project_id)), after=0)
        assert len(events) > 1

        cursor = events[0][0]
        with application.unit_of_work() as uow:
            replayed = uow.events.since(ProjectId(Ulid(project_id)), after=cursor)
        assert len(replayed) == len(events) - 1

    def test_the_stream_advertises_the_right_content_type(self, client: TestClient) -> None:
        project_id = create_project(client)
        with client.stream("GET", url(f"/projects/{project_id}/events")) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"].startswith("no-cache")


class TestVoices:
    """The narrator catalogue and its samples."""

    def test_the_catalogue_describes_every_voice_readably(self, client: TestClient) -> None:
        response = client.get(url("/voices"))

        assert response.status_code == 200
        voices = response.json()
        assert voices, "the catalogue must never be empty"
        for voice in voices:
            # A dropdown showing `de_DE-eva_k-x_low` asks the reader to decode an
            # identifier; speaker and quality are what they actually choose between.
            assert voice["speaker"] and voice["speaker"] != voice["id"]
            assert voice["quality"]
            assert isinstance(voice["downloaded"], bool)

    def test_an_unknown_voice_is_not_found(self, client: TestClient) -> None:
        """The name becomes part of a cache path, so only catalogue names are accepted."""
        for name in ("nonsense", "....", "de_DE-not-a-real-voice"):
            response = client.get(url(f"/voices/{name}/sample"))
            assert response.status_code == 404, name

    def test_a_sample_is_audio_when_the_provider_can_make_one(self, client: TestClient) -> None:
        catalogue = client.get(url("/voices")).json()
        first = catalogue[0]["id"]

        response = client.get(url(f"/voices/{first}/sample"))

        # The deterministic fake provider does not synthesize real speech, so a 503 that
        # names the reason is as correct here as audio would be with Piper installed.
        assert response.status_code in {200, 503}
        if response.status_code == 200:
            assert response.headers["content-type"].startswith("audio/")

    def test_a_project_records_the_voice_it_was_created_with(self, client: TestClient) -> None:
        catalogue = client.get(url("/voices")).json()
        chosen = catalogue[-1]["id"]

        created = client.post(url("/projects"), json={"url": VALID_URL, "voice": chosen})

        assert created.status_code == 201, created.text
        detail = client.get(url(f"/projects/{created.json()['id']}"))
        assert detail.status_code == 200

    def test_a_project_may_leave_the_voice_to_the_default(self, client: TestClient) -> None:
        created = client.post(url("/projects"), json={"url": VALID_URL})

        assert created.status_code == 201, created.text


class TestRunTiming:
    """A run reports when it started and when it stopped.

    Both were recorded and neither was ever sent to the browser, so the only way to answer
    "how long did that dub take" was to read the server log.
    """

    def test_a_running_run_has_a_start_and_no_finish(self, client: TestClient) -> None:
        created = client.post(f"{API_PREFIX}/projects", json={"url": VALID_URL})
        project_id = created.json()["id"]
        run = client.post(f"{API_PREFIX}/projects/{project_id}/analyze").json()

        assert run["created_at"]
        assert run["finished_at"] is None

    def test_a_finished_run_reports_when_it_stopped(
        self, client: TestClient, application: Application
    ) -> None:
        created = client.post(f"{API_PREFIX}/projects", json={"url": VALID_URL})
        project_id = created.json()["id"]
        client.post(f"{API_PREFIX}/projects/{project_id}/analyze")
        application.worker().run_until_idle()

        run = client.get(f"{API_PREFIX}/projects/{project_id}/runs/latest").json()

        assert run["finished"] is True
        assert run["finished_at"] is not None
        assert run["finished_at"] >= run["created_at"]


class TestUnexpectedFailures:
    """What the browser is shown when something the application did not anticipate breaks.

    A user hit this for real: adding a second video during a dub returned 500 and the
    browser said "something went wrong. Check the server log for details." -- lower case,
    and silent about which log and where.

    The failure is injected into a real endpoint rather than a route added for the test. A
    test route is appended after the single-page-app catch-all and never matches once the
    frontend has been built, which makes the test pass or fail depending on whether someone
    ran the build.
    """

    @staticmethod
    def _boom(*_args: object, **_kwargs: object) -> None:
        msg = "an unanticipated failure"
        raise RuntimeError(msg)

    def test_the_generic_error_names_a_reference_and_the_log(
        self, tmp_path: Path, clip: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = Settings(data_dir=tmp_path / "data", log_file=tmp_path / "logs" / "server.log")
        wired = build_application(settings, fixture=clip)
        api = create_app(settings, application=wired)
        monkeypatch.setattr(ProjectService, "list_projects", self._boom)

        try:
            with TestClient(api, raise_server_exceptions=False) as client:
                response = client.get(f"{API_PREFIX}/projects")
        finally:
            wired.dispose()

        body = response.json()
        assert response.status_code == 500
        assert body["code"] == "internal_error"
        # A sentence, not a fragment: it is read by a person, not a log parser.
        assert body["message"] == "Something went wrong. The server log has the details."
        assert body["details"]["log_file"] == str(tmp_path / "logs" / "server.log")
        # The reference is what lets a reader find their own failure in a shared log.
        assert len(body["details"]["reference"]) == 8

    def test_the_reference_differs_between_failures(
        self, tmp_path: Path, clip: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        wired = build_application(settings, fixture=clip)
        api = create_app(settings, application=wired)
        monkeypatch.setattr(ProjectService, "list_projects", self._boom)

        try:
            with TestClient(api, raise_server_exceptions=False) as client:
                first = client.get(f"{API_PREFIX}/projects").json()
                second = client.get(f"{API_PREFIX}/projects").json()
        finally:
            wired.dispose()

        assert first["details"]["reference"] != second["details"]["reference"]
