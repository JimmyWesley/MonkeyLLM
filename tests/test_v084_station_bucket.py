# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""A forest from a bucket, over REST (spec G.3.1 + G.4.7 + J.8 + J.9 +
J.13.4 + J.13.6.1 + J.20, F.229-F.238 host halves).

What the Station owns in this round: the admission (a bucket is reached
only through a configured store, refused BEFORE the first listing call),
the two batch decisions that now travel in the request (`curate`,
`content`), the inbound trigger whose whole authority is a signature, the
dense build that became a job, and the scent pass that can be ordered and
bounded.

The Gardener is faked where the engine half of this round has not landed,
so what is asserted here is the hand-off — which argument reached which
seam — and never the engine's own behaviour.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
OTHER = "forest-second"
BUCKET = "corp-docs"
SOURCE = f"s3://{BUCKET}/handbook"


# -- fakes ------------------------------------------------------------------


class FakeReport:
    def __init__(self, data: dict):
        self.data = data

    def as_dict(self) -> dict:
        return dict(self.data)


class FakeSteps:
    """A G.10 run with no Gardener behind it: `total` before the first step,
    one document per `next()`, the report on `result` at the close."""

    def __init__(self, total: int = 2, delay: float = 0.0):
        self.total = total
        self.delay = delay
        self.index = 0
        self.report = FakeReport({"planted": [], "updated": [], "errors": []})
        self.result = {"planted": [f"notes/doc-{i}" for i in range(total)],
                       "updated": [], "unchanged": [], "errors": [],
                       "stale": [], "unsupported": []}

    def __iter__(self):
        return self

    def __next__(self) -> dict:
        if self.index >= self.total:
            raise StopIteration
        self.index += 1
        if self.delay:
            time.sleep(self.delay)
        return {"index": self.index, "file": f"doc-{self.index}.md",
                "action": "planted"}


class FakeGardener:
    """Records what the host handed it. Every v0.84 seam the host passes is
    declared here by NAME — `stores`, `curate`, `content` — so an assertion
    can read what was forwarded; `**rest` absorbs the arguments this double
    does not care about and would otherwise have to track."""

    last: "FakeGardener | None" = None
    made: list = []

    def __init__(self, vine, hooks=None, dry_run=False, extra_converters=None,
                 ext_registry=None, provenance=None, on_stage=None,
                 stores=None, curate=None, content=None, config=None,
                 **rest):
        self.vine = vine
        self.hooks = list(hooks or [])
        self.stores = stores
        self.curate = curate
        self.content = content
        self.config = dict(FakeGardener.config_seed or {})
        self.calls: list[tuple] = []
        FakeGardener.last = self
        FakeGardener.made.append(self)

    config_seed: dict = {}
    steps_total = 2
    steps_delay = 0.0

    def adopt_iter(self, source, dest=None):
        self.calls.append(("adopt_iter", str(source), dest))
        return FakeSteps(self.steps_total, self.steps_delay)

    def sync_iter(self, source=None, path=None, dest=None, paths=None,
                  *, consume=False):
        self.calls.append(("sync_iter", str(source) if source else None,
                           path, tuple(paths or ())))
        return FakeSteps(len(paths) if paths else self.steps_total,
                         self.steps_delay)

    def recurate_scent_iter(self, **kwargs):
        self.calls.append(("recurate_scent_iter", kwargs))
        return FakeSteps(kwargs.get("limit") or self.steps_total)

    def rollup(self, curator=None, *, only_ingest=True):
        self.calls.append(("rollup", curator is not None))
        return None

    def unrecorded_sources(self, staging):
        return []


@pytest.fixture()
def gardener(monkeypatch):
    FakeGardener.last = None
    FakeGardener.made = []
    FakeGardener.config_seed = {}
    FakeGardener.steps_total = 2
    FakeGardener.steps_delay = 0.0
    monkeypatch.setattr("monkeyllm.gardener.Gardener", FakeGardener)
    return FakeGardener


# -- the Station ------------------------------------------------------------


@pytest.fixture(scope="session")
def two_forests(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("v084-bucket")
    build_forest(root / FOREST)
    build_forest(root / OTHER)
    return root


@pytest.fixture()
def station(two_forests, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    for var in ("MONKEYLLM_STATION_ADMIN", "MONKEYLLM_STATION_PASSWORD",
                "MONKEYLLM_S3_BUCKET", "MONKEYLLM_INGEST_ROOTS"):
        monkeypatch.delenv(var, raising=False)
    app = build_app(root=two_forests, registry_path=tmp_path / "station.db",
                    mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry, app


def _key(registry, principal, forests, caps=("read", "ingest", "admin")):
    key = registry.issue_key(principal)
    for forest in forests:
        registry.grant(principal, forest, set(caps))
    return {"Authorization": f"Bearer {key}"}


def _admin(registry, principal="boss"):
    return _key(registry, principal, (FOREST, OTHER))


def _store(client, head, bucket=BUCKET, prefix="handbook", name="corp"):
    r = client.post("/v1/admin/stores",
                    json={"name": name, "endpoint": "https://objects.invalid",
                          "bucket": bucket, "prefix": prefix,
                          "access_key": "AK", "secret_key": "SK"},
                    headers=head)
    assert r.status_code == 201, r.text


def _ingest(client, head, **body):
    return client.post(f"/v1/forests/{FOREST}/ingest", json=body, headers=head)


def _poll(client, head, job_id, timeout=30.0, forest=FOREST):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/v1/forests/{forest}/jobs/{job_id}", headers=head)
        assert r.status_code == 200, r.text
        job = r.json()["job"]
        if job["state"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.03)
    raise AssertionError(f"job {job_id} never settled")


# ===========================================================================
# F.230 — a bucket is reached only through a configured store
# ===========================================================================


def test_an_unserved_bucket_is_refused_before_anything_is_listed(station,
                                                                 gardener,
                                                                 monkeypatch):
    """G.3.1 rule 1: the refusal is load-bearing rather than procedural —
    every S3 client in wide use falls back to an ambient credential chain
    and a default endpoint, so an unserved bucket would otherwise resolve
    somewhere, with whatever authority the host process happens to carry."""
    from monkeyllm import fetch

    client, registry, _ = station
    head = _admin(registry)
    touched = []
    monkeypatch.setattr(fetch, "s3_client",
                        lambda creds=None, **kw: touched.append(creds))

    r = _ingest(client, head, mode="adopt", source=SOURCE, dest="uploads")
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "E_FORBIDDEN"
    assert BUCKET in r.json()["error"]["message"]
    assert "SK" not in r.text and "objects.invalid" not in r.text
    assert touched == [], "no store client was built"
    assert FakeGardener.last is None, "and no listing was constructed"


def test_the_host_and_the_engine_refuse_the_same_bucket(station):
    """Two decisions about one question — the host refuses before a job is
    claimed, the engine refuses where the walk is built — so this is where
    they were compared. Without this they are one rule only by intention."""
    from monkeyllm.errors import VineError
    from monkeyllm.sources import open_bucket_source

    client, registry, app = station
    head = _admin(registry)
    _store(client, head)          # serves corp-docs/handbook and nothing else
    resolver = app.state.stores

    for uri in (f"s3://{BUCKET}/finance", "s3://nobodys-bucket/x"):
        served = _ingest(client, head, mode="adopt", source=uri, dest="uploads")
        assert served.status_code == 403, served.text
        host_code = served.json()["error"]["code"]
        try:
            open_bucket_source(uri, stores=resolver,
                               staging=Path("/nonexistent"))
            raise AssertionError(f"the engine admitted {uri}")
        except VineError as e:
            assert e.code == host_code, (uri, e.code, host_code)
            assert uri.split("/")[2] in e.message or "prefix" in e.message

    # And the hint names the stores that exist, on BOTH sides, because the
    # engine reads the resolver's own `names()`.
    assert resolver.names() == ["corp"]


def test_a_prefix_outside_the_stores_own_prefix_is_refused(station, gardener):
    """G.3.1 rule 2: a store declaring `prefix: handbook` serves
    `s3://corp-docs/handbook/legal` and refuses `s3://corp-docs/finance`."""
    client, registry, _ = station
    head = _admin(registry)
    _store(client, head)

    r = _ingest(client, head, mode="adopt", source=f"s3://{BUCKET}/finance",
                dest="uploads")
    assert r.status_code == 403, r.text
    assert "outside what store" in r.json()["error"]["message"]
    assert FakeGardener.last is None

    ok = _ingest(client, head, mode="adopt",
                 source=f"s3://{BUCKET}/handbook/legal", dest="uploads")
    assert ok.status_code == 202, ok.text


def test_a_bucket_source_reaches_adopt_and_carries_the_resolver(station,
                                                                gardener):
    client, registry, _ = station
    head = _admin(registry)
    _store(client, head)

    r = _ingest(client, head, mode="adopt", source=SOURCE, dest="uploads")
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["mode"] == "adopt"
    assert FakeGardener.last.calls[0] == ("adopt_iter", SOURCE, "uploads")
    # J.19.8: the credential reaches the engine through ONE seam, handed at
    # construction — never read out of a registry table by the engine.
    resolver = FakeGardener.last.stores
    assert resolver is not None
    assert resolver.by_bucket(BUCKET).secret_key == "SK"
    assert resolver.by_name("corp").bucket == BUCKET
    _poll(client, head, job["id"])


def test_a_bucket_source_still_needs_admin(station, gardener):
    """J.8 (v0.84): same requirement as a host path, a different reason —
    it spends the deployment's stored credentials."""
    client, registry, _ = station
    _store(client, _admin(registry))
    head = _key(registry, "clerk", (FOREST,), caps=("read", "ingest"))

    r = _ingest(client, head, mode="adopt", source=SOURCE, dest="uploads")
    assert r.status_code == 403
    assert "object store" in r.json()["error"]["message"]


def test_the_roots_list_never_admits_a_bucket(station, gardener):
    """`MONKEYLLM_INGEST_ROOTS` stays what it is: a path allow-list cannot
    express an endpoint, a bucket and a credential."""
    client, registry, _ = station
    head = _admin(registry)
    # No roots are configured in this Station, so a host path is refused...
    denied = _ingest(client, head, mode="adopt", path="/tmp", dest="uploads")
    assert denied.status_code == 403
    assert "host paths" in denied.json()["error"]["message"]
    # ...and a bucket with a store is admitted anyway.
    _store(client, head)
    assert _ingest(client, head, mode="adopt", source=SOURCE,
                   dest="uploads").status_code == 202


# ===========================================================================
# F.233 — curating later is a decision
# ===========================================================================


def _bind_ingest_model(client, registry, head):
    registry.put_provider("fake", "https://models.invalid/v1", "key")
    registry.bind_model(FOREST, "ingest", "fake", "some-model")


def test_curate_false_calls_no_model_and_says_which_of_the_three(station,
                                                                 gardener):
    """G.4.7 rule 1-2: `false` means the model is never called — not
    "called and ignored" — and the report still says whether one IS bound,
    which is what lets a console offer the later pass instead of sending an
    operator to repair a model that was never asked anything."""
    client, registry, _ = station
    head = _admin(registry)
    _bind_ingest_model(client, registry, head)

    r = _ingest(client, head, mode="upload", dest="uploads", wait=True,
                curate=False,
                files=[{"name": "a.md", "text": "# A\n\nOne fact.\n"}])
    assert r.status_code == 200, r.text
    report = r.json()["job"]["report"]
    assert report["bound"] is True, "a model IS bound"
    assert report["curated"] is False
    assert report["curation"] == {"reason": "disabled"}
    assert report["curate"] is False
    # The Curator was never constructed, so no model hook joined the chain.
    assert FakeGardener.last.curate is False


def test_with_no_binding_the_reason_is_unbound(station, gardener):
    client, registry, _ = station
    head = _admin(registry)

    r = _ingest(client, head, mode="upload", dest="uploads", wait=True,
                files=[{"name": "b.md", "text": "# B\n\nAnother fact.\n"}])
    assert r.status_code == 200, r.text
    report = r.json()["job"]["report"]
    assert report["bound"] is False
    assert report["curation"] == {"reason": "unbound"}
    assert "curate" not in report, "nobody decided anything"


def test_curate_true_is_v083_to_the_field(station, gardener):
    """The negative control: a batch that does not mention curation keeps
    v0.83's report, field for field."""
    client, registry, _ = station
    head = _admin(registry)

    absent = _ingest(client, head, mode="upload", dest="uploads", wait=True,
                     files=[{"name": "c.md", "text": "# C\n\nFact.\n"}])
    asked = _ingest(client, head, mode="upload", dest="uploads", wait=True,
                    curate=True,
                    files=[{"name": "d.md", "text": "# D\n\nFact.\n"}])
    for r in (absent, asked):
        assert r.status_code == 200, r.text
        assert "curate" not in r.json()["job"]["report"]
    # G.4.7 rule 1: `false` is the only value that changes anything. The
    # request's word is forwarded verbatim — a host that translated `true`
    # into "said nothing" would be deciding on the caller's behalf — and
    # what the rule promises is the OUTCOME: every value but `false` is
    # v0.83's behaviour to the byte.
    assert [g.curate for g in FakeGardener.made[-2:]] == [None, True]
    assert all(g.curate is not False for g in FakeGardener.made[-2:])


def test_a_bad_curate_or_content_is_refused_rather_than_ignored(station,
                                                               gardener):
    """A parameter silently dropped is a lie about what ran."""
    client, registry, _ = station
    head = _admin(registry)
    for body in ({"curate": "later"}, {"content": "elsewhere"}):
        r = _ingest(client, head, mode="upload", dest="uploads",
                    files=[{"name": "e.md", "text": "# E\n\nFact.\n"}], **body)
        assert r.status_code == 400, r.text
        assert r.json()["error"]["code"] == "E_SCHEMA"


def test_the_content_policy_reaches_the_gardener_and_the_report(station,
                                                               gardener):
    client, registry, _ = station
    head = _admin(registry)
    _store(client, head)

    r = _ingest(client, head, mode="adopt", source=SOURCE, dest="uploads",
                content="cached")
    assert r.status_code == 202, r.text
    # It is the forest's policy for this source, so it reaches the Gardener's
    # own config — which is what a later `sync` of the same source reads.
    assert FakeGardener.last.config["content"] == "cached"
    job = _poll(client, head, r.json()["job"]["id"])
    assert job["report"]["content"] == "cached"


def test_reference_into_a_bucket_is_degraded_and_the_degradation_reported(
        station, gardener):
    """G.7 rule 7: a `reference` body is resolved from its source at every
    `pick`, which for a bucket is a network round trip inside the primitive
    with the tightest budget in this document — the bill K.2 moved out of
    the read path in v0.42, walking back in through the content policy."""
    client, registry, _ = station
    head = _admin(registry)
    _store(client, head)

    r = _ingest(client, head, mode="adopt", source=SOURCE, dest="uploads",
                content="reference")
    assert r.status_code == 202, r.text
    assert FakeGardener.last.config["content"] == "cached"
    job = _poll(client, head, r.json()["job"]["id"])
    assert job["report"]["content"] == "cached"
    assert job["report"]["content_degraded"] is True


# ===========================================================================
# F.237 — a notification is a signature and nothing else
# ===========================================================================


def _subscribe(client, head, forest=FOREST):
    r = client.post(f"/v1/forests/{forest}/ingest/subscriptions",
                    json={"label": "the bucket's own events"}, headers=head)
    assert r.status_code == 201, r.text
    return r.json()["subscription"]["id"], r.json()["secret"]


def _notify(client, sub_id, secret, keys, *, forest=FOREST, when=None,
            signature=None):
    body = json.dumps({"keys": keys}).encode()
    timestamp = str(int(when if when is not None else time.time()))
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body,
                   hashlib.sha256).hexdigest()
    return client.post(
        f"/v1/forests/{forest}/ingest/notify", content=body,
        headers={"X-MonkeyLLM-Subscription": sub_id,
                 "X-MonkeyLLM-Timestamp": timestamp,
                 "X-MonkeyLLM-Signature": signature or f"sha256={mac}",
                 "Content-Type": "application/json"})


def _bucket_forest(client, head, gardener):
    _store(client, head)
    FakeGardener.config_seed = {"source_root": SOURCE}


def test_a_signed_notification_schedules_a_targeted_sync(station, gardener):
    client, registry, _ = station
    head = _admin(registry)
    _bucket_forest(client, head, gardener)
    sub_id, secret = _subscribe(client, head)

    r = _notify(client, sub_id, secret,
                ["handbook/a.md", "handbook/b.md"])
    assert r.status_code == 202, r.text
    assert r.json()["scheduled"] == 2
    job = _poll(client, head, r.json()["job"])
    assert job["state"] == "done"
    assert ("sync_iter", None, None, ("handbook/a.md", "handbook/b.md")) \
        in FakeGardener.last.calls

    # Audited under the subscription, never under a person — and the key
    # COUNT, never a key: a key is a path in somebody's bucket.
    row = next(r for r in registry.audit(limit=20)
               if r["primitive"] == "ingest.notify")
    assert row["principal"] == f"notify:{sub_id}"
    assert row["size"] == 2
    assert "handbook/a.md" not in json.dumps(row, default=str)


def test_every_failure_is_one_byte_identical_refusal(station, gardener):
    """J.20 rule 3: a distinct refusal per cause is an oracle that tells an
    unauthenticated caller which half they got right."""
    client, registry, _ = station
    head = _admin(registry)
    _bucket_forest(client, head, gardener)
    sub_id, secret = _subscribe(client, head)
    keys = ["handbook/a.md"]

    unsigned = client.post(f"/v1/forests/{FOREST}/ingest/notify",
                           json={"keys": keys})
    wrong = _notify(client, sub_id, secret, keys, signature="sha256=00")
    forged = _notify(client, sub_id, "not-the-secret", keys)
    stale = _notify(client, sub_id, secret, keys, when=time.time() - 3600)
    unknown = _notify(client, "ing-sub-nope", secret, keys)
    other_forest = _notify(client, sub_id, secret, keys, forest=OTHER)

    for r in (unsigned, wrong, forged, stale, unknown, other_forest):
        assert r.status_code == 401, r.text
        assert r.text == unsigned.text

    # A removed subscription is the same refusal, which is the whole of its
    # revocation.
    client.delete(f"/v1/forests/{FOREST}/ingest/subscriptions/{sub_id}",
                  headers=head)
    assert _notify(client, sub_id, secret, keys).text == unsigned.text


def test_the_secret_is_shown_once_and_never_read_back(station):
    client, registry, _ = station
    head = _admin(registry)
    sub_id, secret = _subscribe(client, head)

    listed = client.get(f"/v1/forests/{FOREST}/ingest/subscriptions",
                        headers=head)
    assert listed.status_code == 200
    assert secret not in listed.text
    assert listed.json()["subscriptions"][0]["id"] == sub_id
    assert listed.json()["limits"]["max_keys"] == 1000


def test_a_key_escaping_the_prefix_refuses_the_whole_request(station, gardener):
    client, registry, _ = station
    head = _admin(registry)
    _bucket_forest(client, head, gardener)
    sub_id, secret = _subscribe(client, head)

    r = _notify(client, sub_id, secret,
                ["handbook/a.md", "../../etc/passwd", "handbook/b.md"])
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "E_SCHEMA"
    assert "3 keys" in r.json()["error"]["message"]
    assert "etc/passwd" in r.json()["error"]["message"]
    assert FakeGardener.last is None, "and nothing was reconciled"


def test_a_notification_is_an_event_not_a_backfill(station, gardener):
    client, registry, _ = station
    head = _admin(registry)
    _bucket_forest(client, head, gardener)
    sub_id, secret = _subscribe(client, head)

    r = _notify(client, sub_id, secret, [f"handbook/{i}.md" for i in range(1001)])
    assert r.status_code == 400
    assert "at most 1000" in r.json()["error"]["message"]


def test_a_notification_arriving_mid_batch_is_held_and_fires_at_the_settle(
        station, gardener):
    """J.9's v0.84 amendment: the host queues a machine and still never
    queues a person — visible, bounded, coalesced, and dead on restart."""
    client, registry, app = station
    head = _admin(registry)
    _bucket_forest(client, head, gardener)
    sub_id, secret = _subscribe(client, head)
    FakeGardener.steps_total, FakeGardener.steps_delay = 6, 0.12

    started = _ingest(client, head, mode="upload", dest="uploads",
                      files=[{"name": f"q{i}.md", "text": f"# Q{i}\n\nx.\n"}
                             for i in range(6)])
    assert started.status_code == 202, started.text
    running = started.json()["job"]["id"]

    first = _notify(client, sub_id, secret, ["handbook/a.md"])
    second = _notify(client, sub_id, secret, ["handbook/a.md", "handbook/c.md"])
    assert first.status_code == second.status_code == 202
    assert first.json()["queued"] == 1
    # Coalesced: several notifications merge into ONE deduplicated set.
    assert second.json()["queued"] == 2

    # Visible, beside the running job.
    board = client.get(f"/v1/forests/{FOREST}/jobs", headers=head).json()
    assert board["pending"] == {"keys": 2, "dropped": 0}

    # An operator's own batch POST is unchanged and is still refused.
    locked = _ingest(client, head, mode="upload", dest="uploads",
                     files=[{"name": "z.md", "text": "# Z\n\nx.\n"}])
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "E_LOCKED"

    _poll(client, head, running)
    FakeGardener.steps_delay = 0.0

    # The held keys fire at the settle, ONCE, as one deduplicated set. The
    # upload that was running also refreshes through `sync_iter` (J.8's one
    # upload path), so the notification's run is identified by its keys and
    # never by "the last call somebody made".
    def held_runs():
        return [c for g in list(FakeGardener.made) for c in g.calls
                if c[0] == "sync_iter" and set(c[3]) & {"handbook/a.md",
                                                        "handbook/c.md"}]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not held_runs():
        time.sleep(0.05)
    runs = held_runs()
    assert runs, "the held notification never fired"
    assert len(runs) == 1, f"it fired more than once: {runs}"
    assert runs[0][3] == ("handbook/a.md", "handbook/c.md")
    assert client.get(f"/v1/forests/{FOREST}/jobs",
                      headers=head).json().get("pending") is None


def test_a_subscription_is_a_governance_object(station):
    client, registry, _ = station
    head = _admin(registry)
    clerk = _key(registry, "clerk", (FOREST,), caps=("read", "ingest"))
    assert client.get(f"/v1/forests/{FOREST}/ingest/subscriptions",
                      headers=clerk).status_code == 403
    assert client.post(f"/v1/forests/{FOREST}/ingest/subscriptions",
                       json={}, headers=clerk).status_code == 403

    sub_id, _secret = _subscribe(client, head)
    rows = [r for r in registry.audit(limit=20)
            if "subscription" in str(r["primitive"])]
    assert rows and rows[0]["forest"] == FOREST


# ===========================================================================
# F.238 — the dense layer is built as a job
# ===========================================================================


def _bind_embedder(registry, forest=FOREST):
    registry.put_provider("embeds", "https://embed.invalid/v1", "key")
    registry.bind_model(forest, "embed", "embeds", "some-embedder")


class FakeCanopySteps(FakeSteps):
    def __init__(self, total=4, delay=0.0):
        super().__init__(total, delay)
        self.result = {"embedded": total, "nodes": total}


def test_a_build_answers_202_with_a_job_and_takes_the_batch_lock(station,
                                                                gardener,
                                                                monkeypatch):
    client, registry, _ = station
    head = _admin(registry)
    _bind_embedder(registry)
    monkeypatch.setattr("monkeyllm.vine.Vine.build_canopy_iter",
                        lambda self: FakeCanopySteps(4, 0.1), raising=False)

    r = client.post("/v1/admin/canopy", json={"forest": FOREST}, headers=head)
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["mode"] == "canopy" and job["state"] == "running"
    assert r.json()["nodes"] == 4

    # It shares the ONE batch per forest lock: an ingest planting nodes
    # under a running build produces an index that is silently incomplete.
    locked = _ingest(client, head, mode="upload", dest="uploads",
                     files=[{"name": "k.md", "text": "# K\n\nx.\n"}])
    assert locked.status_code == 409
    assert job["id"] in locked.json()["error"]["message"]

    done = _poll(client, head, job["id"])
    assert done["state"] == "done" and done["done"] == 4
    assert done["report"]["embedded"] == 4


def test_an_ingest_blocks_a_build_the_same_way(station, gardener, monkeypatch):
    client, registry, _ = station
    head = _admin(registry)
    _bind_embedder(registry)
    monkeypatch.setattr("monkeyllm.vine.Vine.build_canopy_iter",
                        lambda self: FakeCanopySteps(2), raising=False)
    FakeGardener.steps_total, FakeGardener.steps_delay = 5, 0.1

    started = _ingest(client, head, mode="upload", dest="uploads",
                      files=[{"name": f"m{i}.md", "text": f"# M{i}\n\nx.\n"}
                             for i in range(5)])
    assert started.status_code == 202
    refused = client.post("/v1/admin/canopy", json={"forest": FOREST},
                          headers=head)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "E_LOCKED"
    FakeGardener.steps_delay = 0.0
    _poll(client, head, started.json()["job"]["id"])


def test_a_cancelled_build_leaves_the_index_it_had(station, gardener,
                                                   monkeypatch):
    """K.4 from the other side: an index in two states is worse than no
    index, and a half-built one is a fresh way to produce that."""
    client, registry, _ = station
    head = _admin(registry)
    _bind_embedder(registry)
    monkeypatch.setattr("monkeyllm.vine.Vine.build_canopy_iter",
                        lambda self: FakeCanopySteps(10, 0.08), raising=False)
    before = client.get("/v1/admin/canopy", params={"forest": FOREST},
                        headers=head).json()

    started = client.post("/v1/admin/canopy", json={"forest": FOREST},
                          headers=head)
    job_id = started.json()["job"]["id"]
    assert client.post(f"/v1/forests/{FOREST}/jobs/{job_id}/cancel",
                       headers=head).status_code == 200
    job = _poll(client, head, job_id)
    assert job["state"] == "cancelled"
    assert job["report"]["resumable"] is False

    after = client.get("/v1/admin/canopy", params={"forest": FOREST},
                       headers=head).json()
    for field in ("model", "nodes", "stale", "state"):
        assert after.get(field) == before.get(field), field


def test_the_get_is_unchanged_and_the_switch_still_answers_in_place(station):
    client, registry, _ = station
    head = _admin(registry)
    r = client.get("/v1/admin/canopy", params={"forest": FOREST}, headers=head)
    assert r.status_code == 200 and "job" not in r.json()

    off = client.post("/v1/admin/canopy",
                      json={"forest": FOREST, "enabled": False}, headers=head)
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False and "job" not in off.json()


def test_a_build_with_no_embedder_is_refused_before_the_lock(station):
    client, registry, _ = station
    head = _admin(registry)
    r = client.post("/v1/admin/canopy", json={"forest": FOREST}, headers=head)
    assert r.status_code == 400
    assert "no embedding model" in r.json()["error"]["message"]
    # Nothing was claimed, so the next batch is free.
    assert client.get(f"/v1/forests/{FOREST}/jobs", headers=head) \
        .json()["jobs"] == []


# ===========================================================================
# F.234 — the scent pass is ordered and bounded
# ===========================================================================


def test_order_and_limit_reach_the_pass_and_the_bill_is_the_bounded_number(
        station, gardener):
    client, registry, _ = station
    head = _admin(registry)
    registry.put_provider("fake", "https://models.invalid/v1", "key")
    registry.bind_model(FOREST, "ingest", "fake", "some-model")

    r = client.post("/v1/admin/recurate",
                    json={"forest": FOREST, "derive": ["scent"],
                          "order": "heat", "limit": 3}, headers=head)
    assert r.status_code == 202, r.text
    body = r.json()
    # Rule 9: the number IS the cap and never the scope — stating the scope
    # would be quoting a price nobody is being charged.
    assert body["nodes"] == 3 and body["order"] == "heat" and body["limit"] == 3
    assert ("recurate_scent_iter", {"order": "heat", "limit": 3}) \
        in FakeGardener.last.calls
    _poll(client, head, body["job"]["id"])


def test_a_pass_that_names_neither_is_v075(station, gardener):
    client, registry, _ = station
    head = _admin(registry)
    registry.put_provider("fake", "https://models.invalid/v1", "key")
    registry.bind_model(FOREST, "ingest", "fake", "some-model")

    r = client.post("/v1/admin/recurate",
                    json={"forest": FOREST, "derive": ["scent"]}, headers=head)
    assert r.status_code == 202, r.text
    assert "order" not in r.json() and "limit" not in r.json()
    assert ("recurate_scent_iter", {}) in FakeGardener.last.calls
    _poll(client, head, r.json()["job"]["id"])


def test_a_bad_order_or_limit_is_refused(station, gardener):
    client, registry, _ = station
    head = _admin(registry)
    registry.put_provider("fake", "https://models.invalid/v1", "key")
    registry.bind_model(FOREST, "ingest", "fake", "some-model")
    for body in ({"order": "alphabetical"}, {"limit": 0}, {"limit": "many"}):
        r = client.post("/v1/admin/recurate",
                        json={"forest": FOREST, "derive": ["scent"], **body},
                        headers=head)
        assert r.status_code == 400, r.text
        assert r.json()["error"]["code"] == "E_SCHEMA"


# ===========================================================================
# J.8.4 (v0.84) — a passport names the document, and a document may be a
# branch. The gate is the Station's, so its keying is asserted here.
# ===========================================================================


def test_a_passport_lands_on_the_document_and_not_on_its_parts():
    from monkeyllm_station.compose import passport_gate

    passport = {"title": "The Handbook", "summary": "Everything we know.",
                "tags": ["handbook"]}
    gate = passport_gate({"book.pdf": passport}, vine=None, policy=None)

    document = gate({"source_path": "book.pdf", "title": "book",
                     "summary": "A file called book.pdf."})
    assert document["title"] == "The Handbook"

    chapter = gate({"source_path": "book.pdf", "source_part": "ch-07",
                    "title": "Chapter 7", "summary": "What chapter 7 says."})
    assert chapter["title"] == "Chapter 7", "a part keeps its own scent"
    assert chapter["summary"] == "What chapter 7 says."
    assert "tags" not in chapter
    # The passport was applied once, to the document, and `applied` still
    # keys by source_path so `passports_ignored` keeps working.
    assert gate.applied == {"book.pdf"}
