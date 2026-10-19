"""Campaigns: replicas with different seeds, the job contract, HTCondor files, collecting results."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

import meg
from meg import toolchain as tc
from meg.batch import collect as col
from meg.batch import htcondor, job
from meg.batch import submit as sub
from meg.batch.campaign import Campaign, campaign_id, tag, unique_name
from meg.util import MegError

SRC = Path(__file__).resolve().parents[1] / "src"


def bcfg(*over, name="camp", executor="local", build_once=False):
    return meg.load_config(None, [f'run.name="{name}"', "generation.events=7", 'shower.kind="pythia8"',
                                  f'execution.executor="{executor}"', "execution.campaign_dir=\"camps\"",
                                  f"execution.build_once={'true' if build_once else 'false'}", *over])


@pytest.fixture
def local_env(toolchain, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(SRC))        # the local executor starts `python -m meg`
    return toolchain


@pytest.fixture
def fake_condor(tmp_path, monkeypatch, toolchain):
    d = tmp_path / "condorbin"
    d.mkdir()
    log = tmp_path / "condor_calls.txt"
    sub_s = d / "condor_submit"
    sub_s.write_text(f"#!/bin/sh\necho \"$@ cwd=$(pwd)\" >> {log}\n"
                     "echo '5000 job(s) submitted to cluster 4242.'\n")
    q = d / "condor_q"
    q.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\ncat {tmp_path}/queue.json\n")
    dag = d / "condor_submit_dag"
    dag.write_text(f"#!/bin/sh\necho \"dag $@ cwd=$(pwd)\" >> {log}\n"
                   "echo '1 job(s) submitted to cluster 777.'\n")
    rm = d / "condor_rm"
    rm.write_text(f"#!/bin/sh\necho \"rm $@\" >> {log}\necho removed\n")
    for f in (sub_s, q, rm, dag):
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "queue.json").write_text("[]")
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    return log


# --------------------------------------------------------------------------- config and identity

def test_seeds_and_ids():
    c = bcfg("execution.replicas=4", "execution.seed_start=10")
    assert c.seeds() == [10, 11, 12, 13]
    d = bcfg("execution.replicas=9", "run.seed=5", 'execution.retrieve="all"')
    assert d.seeds()[0] == 5 and d.process_id() == c.process_id()            # same physics, same id
    assert campaign_id(c) == f"camp-{c.process_id()}"
    assert bcfg("process.definition=\"p p > t t~ j\"").process_id() != c.process_id()
    assert unique_name("camp-ab12cd34", 7, "delphes") == "camp-ab12cd34_s0007.delphes.root"
    assert tag(12345) == "s12345"


def test_retrieve_defaults_and_checks():
    assert bcfg().execution.retrieve == ["delphes"]
    assert bcfg('detector.kind="none"').execution.retrieve == ["lhe"]
    with pytest.raises(MegError, match="delphes"):
        bcfg('detector.kind="none"', 'execution.retrieve=["delphes"]')
    with pytest.raises(MegError, match="seeds run up"):
        bcfg("execution.replicas=5", f"execution.seed_start={meg.config.MAX_SEED - 1}")
    with pytest.raises(MegError, match="HH:MM:SS"):
        bcfg('execution.walltime="12h"')


def test_site_file_gives_defaults_and_project_wins(tmp_path, monkeypatch):
    site = tmp_path / "site.toml"
    site.write_text('[execution.htcondor]\naccounting_group = "grp.x"\n[execution]\nmemory = "9GB"\n')
    monkeypatch.setenv("MEG_SITE", str(site))
    c = meg.load_config(None, ["execution.disk=\"5GB\""])
    assert c.execution.htcondor.accounting_group == "grp.x" and c.execution.memory == "9GB"
    assert meg.load_config(None, ['execution.memory="2GB"']).execution.memory == "2GB"
    site.write_text("[run]\nseed = 3\n")
    with pytest.raises(MegError, match="only an \\[execution\\] table"):
        meg.load_config(None, [])


def test_configure_mg5_does_nothing_when_already_configured(toolchain):
    mg5 = tc.locate_mg5(dict(os.environ))
    env = dict(os.environ)
    tc.configure_mg5(mg5, env)
    cfg_file = mg5.config
    cfg_file.chmod(0o444)                  # a read-only tree on a worker node
    before = cfg_file.read_text()
    tc.configure_mg5(mg5, env)             # must neither write nor spawn MG5
    assert cfg_file.read_text() == before


# --------------------------------------------------------------------------- the job contract

def _meta_files(tmp_path, cfg):
    (tmp_path / "campaign.json").write_text(json.dumps({"id": campaign_id(cfg), "offline": False}))
    (tmp_path / "config.json").write_text(cfg.model_dump_json())
    return tmp_path / "campaign.json", tmp_path / "config.json"


def test_job_leaves_a_uniquely_named_outbox(toolchain, tmp_path):
    cfg = bcfg('execution.retrieve=["delphes", "lhe", "hepmc"]')
    meta, conf = _meta_files(tmp_path, cfg)
    outbox = tmp_path / "outbox"
    assert job.run_replica(meta, conf, 7, outbox) == 0
    cid = campaign_id(cfg)
    names = sorted(p.name for p in outbox.iterdir())
    assert names == sorted([f"{cid}_s0007.delphes.root", f"{cid}_s0007.lhe.gz", f"{cid}_s0007.hepmc.gz",
                            f"{cid}_s0007.manifest.json", f"{cid}_s0007.logs.tar.gz", "status.json"])
    st = json.loads((outbox / "status.json").read_text())
    assert st["state"] == "ok" and st["seed"] == 7 and st["events"] == 7 and st["xsec_pb"] == pytest.approx(508.9)
    assert set(st["files"]) == set(names) - {"status.json"} and all(v["sha256"] for v in st["files"].values())
    assert json.loads((outbox / f"{cid}_s0007.manifest.json").read_text())["config"]["run"]["seed"] == 7
    assert not list(tmp_path.glob("meg-*"))                       # scratch removed


def test_job_all_makes_one_archive(toolchain, tmp_path):
    cfg = bcfg('execution.retrieve="all"')
    meta, conf = _meta_files(tmp_path, cfg)
    assert job.run_replica(meta, conf, 3, tmp_path / "outbox") == 0
    assert (tmp_path / "outbox" / f"{campaign_id(cfg)}_s0003.run.tar.gz").is_file()


def test_failed_job_still_returns_logs_and_a_status(toolchain, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_DELPHES_ERROR", "1")
    cfg = bcfg()
    meta, conf = _meta_files(tmp_path, cfg)
    outbox = tmp_path / "outbox"
    assert job.run_replica(meta, conf, 2, outbox) == 1
    st = json.loads((outbox / "status.json").read_text())
    assert st["state"] == "failed" and "delphes" in st["error"].lower()
    assert (outbox / f"{campaign_id(cfg)}_s0002.logs.tar.gz").stat().st_size > 0


def test_stale_outbox_is_cleared(toolchain, tmp_path):
    cfg = bcfg()
    meta, conf = _meta_files(tmp_path, cfg)
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    (outbox / "status.json").write_text('{"state": "ok"}')
    (outbox / "old.root").write_text("x")
    job.run_replica(meta, conf, 1, outbox)
    assert not (outbox / "old.root").exists()


# --------------------------------------------------------------------------- local campaign end to end

def test_local_campaign_collect_and_combine(local_env):
    cfg = bcfg("execution.replicas=3", "execution.seed_start=20", "execution.max_running=2")
    c = sub.submit(cfg)
    text, by = sub.status_text(c)
    assert len(by["ok"]) == 3 and "all done" in text
    cid = c.id
    assert (c.replica_dir(21) / "outbox" / f"{cid}_s0021.delphes.root").is_file()
    s = col.collect(c, verify=True)
    assert s["ok"] == 3 and s["events"] == 21 and s["xsec_pb"] == pytest.approx(508.9)
    files = sorted(p.name for p in c.outputs.iterdir())
    for seed in (20, 21, 22):
        assert f"{cid}_s{seed:04d}.delphes.root" in files and f"{cid}_s{seed:04d}.manifest.json" in files
    assert len(set(files)) == len(files)
    assert "combined cross-section" in col.summary_text(s)
    # seeds really differ between replicas
    seeds = {json.loads((c.outputs / f"{cid}_{tag(x)}.manifest.json").read_text())["config"]["run"]["seed"]
             for x in (20, 21, 22)}
    assert seeds == {20, 21, 22}
    with pytest.raises(MegError, match="already exists"):
        sub.submit(cfg)


def test_local_campaign_reports_and_resubmits_failures(local_env, monkeypatch):
    cfg = bcfg("execution.replicas=2", "execution.seed_start=1")
    monkeypatch.setenv("FAKE_DELPHES_ERROR", "1")
    c = sub.submit(cfg)
    text, by = sub.status_text(c)
    assert len(by["failed"]) == 2 and "meg resubmit" in text
    monkeypatch.delenv("FAKE_DELPHES_ERROR")
    assert sub.resubmit(c) == [1, 2]
    assert sorted(sub.status_text(c)[1]) == ["ok"]
    assert sub.resubmit(c) == []                                  # nothing left to do


def test_output_dir_keeps_results_off_the_campaign_disk(local_env, tmp_path):
    eos = tmp_path / "eos"
    cfg = bcfg("execution.replicas=2", "execution.seed_start=5", f'execution.output_dir="{eos}"')
    c = sub.submit(cfg)
    cid = c.id
    assert c.meta["output_dir"] == str(eos / cid)
    assert (eos / cid / f"{cid}_s0005.delphes.root").is_file()
    assert (eos / cid / f"{cid}_s0006.logs.tar.gz").is_file()
    back = sorted(p.name for p in c.outbox(5).iterdir())
    assert back == ["status.json"]                                # nothing big came back
    assert not list((eos / cid).glob("*.part"))
    s = col.collect(c, verify=True)
    assert s["ok"] == 2 and s["output_dir"] == str(eos / cid) and "results are in" in col.summary_text(s)
    assert not list(c.outputs.glob("*.delphes.root"))             # not copied onto the campaign disk
    (eos / cid / f"{cid}_s0005.delphes.root").write_text("tampered")
    with pytest.raises(MegError, match="does not match"):
        col.collect(c)
    (eos / cid / f"{cid}_s0005.delphes.root").unlink()
    with pytest.raises(MegError, match="missing"):
        col.collect(c)


def test_output_dir_unwritable_fails_the_replica_and_keeps_logs(local_env, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")                                       # a file where a directory is needed
    c = sub.submit(bcfg("execution.replicas=1", f'execution.output_dir="{blocker}/sub"'))
    st = c.read_status(1)
    assert st["state"] == "failed" and "copying the results" in st["error"]
    left = sorted(p.name for p in c.outbox(1).iterdir())
    assert left == [f"{c.id}_s0001.logs.tar.gz", f"{c.id}_s0001.manifest.json", "status.json"]


def test_output_dir_must_be_absolute():
    with pytest.raises(MegError, match="absolute"):
        bcfg('execution.output_dir="relative/eos"')


def test_collect_detects_damage(local_env):
    c = sub.submit(bcfg("execution.replicas=1"))
    f = next((c.replica_dir(1) / "outbox").glob("*.delphes.root"))
    f.write_text("tampered")
    with pytest.raises(MegError, match="does not match"):
        col.collect(c)


def test_combine_weights_by_error():
    out = col.combine([(100.0, 1.0), (110.0, 2.0)])
    assert out["xsec_pb"] == pytest.approx((100 / 1 + 110 / 4) / (1 + 1 / 4))
    assert out["chi2_ndf"] == pytest.approx(1.0 * (100 - out["xsec_pb"]) ** 2 + 0.25 * (110 - out["xsec_pb"]) ** 2)
    assert col.combine([(5.0, None), (7.0, None)])["xsec_pb"] == 6.0


# --------------------------------------------------------------------------- HTCondor

def test_htcondor_dry_run_writes_everything_and_submits_nothing(toolchain, fake_condor, monkeypatch):
    monkeypatch.delenv("PIXI_PROJECT_ROOT", raising=False)
    cfg = bcfg("execution.replicas=5", "execution.seed_start=100", 'execution.walltime="02:30:00"',
               "execution.max_running=50", "execution.cores=4", 'execution.memory="8GB"',
               'execution.htcondor.accounting_group="grp.hep"',
               "execution.htcondor.extra=[\"+JobFlavour = 'workday'\"]", executor="htcondor")
    c = sub.submit(cfg, dry_run=True)
    assert not fake_condor.exists()
    text = (c.dir / "submit.sub").read_text()
    for needle in ("universe = vanilla", "arguments = $(seed)", "transfer_output_files = outbox",
                   "initialdir = replicas/$(tag)", "request_cpus = 4", "request_memory = 8GB", "+MaxRuntime = 9000",
                   "max_materialize = 50", "accounting_group = grp.hep", "+JobFlavour = 'workday'",
                   "queue seed,tag from seeds.txt", f"batch_name = {c.id}"):
        assert needle in text, needle
    assert (c.dir / "seeds.txt").read_text().splitlines() == ["100,s0100", "101,s0101", "102,s0102",
                                                              "103,s0103", "104,s0104"]
    assert os.access(c.dir / "job.sh", os.X_OK) and "meg _job" in (c.dir / "job.sh").read_text()
    env = (c.dir / "env.sh").read_text()
    assert "MEG_OFFLINE=1" in env and "MEG_CACHE=" in env and str(toolchain) in env
    frozen = json.loads((c.dir / "config.json").read_text())
    assert frozen["execution"]["cores"] == 4 and Path(frozen["detector"]["card"]).is_absolute()
    assert (c.dir / "replicas" / "s0102").is_dir()


def test_htcondor_submit_records_the_cluster_and_status_reads_the_queue(toolchain, fake_condor, tmp_path,
                                                                        monkeypatch):
    monkeypatch.delenv("PIXI_PROJECT_ROOT", raising=False)
    c = sub.submit(bcfg("execution.replicas=4", "execution.seed_start=1", executor="htcondor"))
    assert "submit.sub" in fake_condor.read_text() and f"cwd={c.dir}" in fake_condor.read_text()
    assert c.meta["submissions"][0]["cluster"] == 4242
    # the toolchain was prepared on the submit host, and jobs are told to stay offline
    assert "pythia8_path" in (toolchain / "input/mg5_configuration.txt").read_text()
    assert c.meta["offline"] is True
    # queue: proc 0 running, proc 1 held; proc 2 finished ok (outbox); proc 3 vanished
    (tmp_path / "queue.json").write_text(json.dumps([
        {"ProcId": 0, "JobStatus": 2}, {"ProcId": 1, "JobStatus": 5, "HoldReason": "memory exceeded"}]))
    ob = c.outbox(3)
    ob.mkdir(parents=True)
    (ob / "status.json").write_text(json.dumps({"state": "ok", "events": 7, "files": {}}))
    states, asked = sub.seed_states(c)
    assert asked and states[1][0] == "running" and states[2] == ("held", "memory exceeded")
    assert states[3][0] == "ok" and states[4][0] == "lost"
    text, _ = sub.status_text(c)
    assert "held" in text and "memory exceeded" in text and "meg resubmit" in text


def test_htcondor_resubmit_only_failed_and_lost(toolchain, fake_condor, tmp_path, monkeypatch):
    monkeypatch.delenv("PIXI_PROJECT_ROOT", raising=False)
    c = sub.submit(bcfg("execution.replicas=3", "execution.seed_start=1", executor="htcondor"))
    ok = c.outbox(1)
    ok.mkdir(parents=True)
    (ok / "status.json").write_text(json.dumps({"state": "ok", "events": 7, "files": {}}))
    bad = c.outbox(2)
    bad.mkdir(parents=True)
    (bad / "status.json").write_text(json.dumps({"state": "failed", "error": "boom", "files": {}}))
    # seed 3 is lost: not in the queue, no results
    todo = sub.resubmit(c)
    assert todo == [2, 3]
    assert (c.dir / "seeds_2.txt").read_text() == "2,s0002\n3,s0003\n"
    assert "queue seed,tag from seeds_2.txt" in (c.dir / "submit_2.sub").read_text()
    assert not bad.exists()                                       # stale outbox removed
    assert len(Campaign.load(c.dir).meta["submissions"]) == 2
    assert sub.cancel(c) == [4242, 4242]
    assert "rm 4242" in fake_condor.read_text()


def test_htcondor_needs_a_submit_host(toolchain, monkeypatch):
    monkeypatch.delenv("PIXI_PROJECT_ROOT", raising=False)
    monkeypatch.setenv("PATH", f"{toolchain / 'bin'}:/usr/bin:/bin")        # no condor tools
    cfg = bcfg("execution.replicas=1", executor="htcondor")
    with pytest.raises(MegError, match="condor_submit not found"):
        sub.submit(cfg)
    assert htcondor.queue_states.__name__          # (queue_states returns None when condor_q is missing)


def test_campaign_load_errors_helpfully(tmp_path):
    with pytest.raises(MegError, match="not a campaign directory"):
        Campaign.load(tmp_path)


def test_cli_job_is_hidden_but_works(toolchain, tmp_path, capsys):
    from meg import cli
    cfg = bcfg()
    meta, conf = _meta_files(tmp_path, cfg)
    rc = cli.main(["_job", "--meta", str(meta), "--config", str(conf), "--seed", "4", "--outbox",
                   str(tmp_path / "ob")])
    assert rc == 0 and (tmp_path / "ob" / "status.json").is_file()
    assert "_job" not in cli.build_parser().format_help()


def test_python_module_entry_exists():
    assert (SRC / "meg" / "__main__.py").is_file() and sys.executable


def test_generated_job_script_works_from_an_empty_scratch_dir(toolchain, fake_condor, tmp_path, monkeypatch):
    """What HTCondor does: copy the three input files into a bare directory and run job.sh there."""
    import shutil
    import subprocess
    monkeypatch.delenv("PIXI_PROJECT_ROOT", raising=False)
    monkeypatch.setenv("PYTHONPATH", str(SRC))
    meg_bin = toolchain / "bin" / "meg"
    meg_bin.write_text(f"#!/bin/sh\nexec {sys.executable} -m meg \"$@\"\n")
    meg_bin.chmod(0o755)
    c = sub.submit(bcfg("execution.replicas=2", "execution.seed_start=8", executor="htcondor"))
    scratch = tmp_path / "node_scratch"
    scratch.mkdir()
    for f in ("campaign.json", "config.json", "env.sh"):
        shutil.copy(c.dir / f, scratch / f)
    shutil.copy(c.dir / "job.sh", scratch / "job.sh")
    env = {k: v for k, v in os.environ.items() if k not in ("CONDA_PREFIX",)}
    env["PATH"] = "/usr/bin:/bin"                 # a bare node: only env.sh may provide meg and the tools
    env["TMPDIR"] = str(scratch)
    r = subprocess.run(["bash", "job.sh", "9"], cwd=scratch, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:] + r.stdout[-2000:]
    cid = c.id
    assert (scratch / "outbox" / f"{cid}_s0009.delphes.root").is_file()
    assert json.loads((scratch / "outbox" / "status.json").read_text())["seed"] == 9
    # MEG_OFFLINE came from env.sh: the job did not need the network
    assert "MEG_OFFLINE=1" in (c.dir / "env.sh").read_text()


# =========================================================================== build the process once

def test_make_relocatable_and_relocate(tmp_path):
    from meg import process_dir
    root = tmp_path / "build" / "proc"
    (root / "lib").mkdir(parents=True)
    (root / "Cards").mkdir()
    outside = tmp_path / "env" / "lib"
    outside.mkdir(parents=True)
    (outside / "libx.a").write_text("x")
    os.symlink(os.path.relpath(outside / "libx.a", root / "lib"), root / "lib" / "out.a")      # leaves the tree
    (root / "Cards" / "a.dat").write_text("x")
    os.symlink("a.dat", root / "Cards" / "inside.dat")                                         # stays inside
    (root / "Cards" / "conf.txt").write_text(f"dir = {root}\n")
    (root / "Cards" / "blob.bin").write_bytes(b"\0\1" + str(root).encode())
    assert process_dir.make_relocatable(root) == 1
    assert os.readlink(root / "lib" / "out.a") == str(outside / "libx.a")
    assert os.readlink(root / "Cards" / "inside.dat") == "a.dat"
    assert process_dir.relocate(root, str(root), "/new/place/proc") == 1                # the text file only
    assert (root / "Cards" / "conf.txt").read_text() == "dir = /new/place/proc\n"
    assert str(root).encode() in (root / "Cards" / "blob.bin").read_bytes()
    assert process_dir.relocate(root, "/same", "/same") == 0


def test_prepare_then_replica_from_the_prebuilt_process(toolchain, tmp_path, monkeypatch):
    from meg.batch import prepare
    cfg = bcfg()
    meta, conf = _meta_files(tmp_path, cfg)
    (tmp_path / "campaign.json").write_text(json.dumps({"id": campaign_id(cfg), "offline": False, "seeds": [1, 2]}))
    pre = tmp_path / "pre"
    assert prepare.run_prepare(meta, conf, pre) == 0
    st = json.loads((pre / "status.json").read_text())
    assert st["state"] == "ok" and st["bytes"] > 0 and (pre / "process.tar.gz").is_file()
    deep = tmp_path / "node" / "scratch" / "dir"            # a different depth than where it was built:
    deep.mkdir(parents=True)                                # relative symlinks would dangle without relocation
    monkeypatch.setenv("TMPDIR", str(deep))
    ob = tmp_path / "ob"
    assert job.run_replica(meta, conf, 5, ob, pre / "process.tar.gz") == 0
    assert json.loads((ob / "status.json").read_text())["state"] == "ok"
    import tarfile
    with tarfile.open(ob / f"{campaign_id(cfg)}_s0005.logs.tar.gz") as t:
        names = t.getnames()
    assert any(n.endswith("launch.log") for n in names) and not any(n.endswith("proc.log") for n in names)
    with tarfile.open(pre / f"{campaign_id(cfg)}_prepare.logs.tar.gz") as t:
        assert any(n.endswith("proc.log") for n in t.getnames())


def test_replica_seed_is_applied_to_a_prebuilt_process(toolchain, tmp_path):
    from meg.batch import prepare
    cfg = bcfg()
    meta, conf = _meta_files(tmp_path, cfg)
    (tmp_path / "campaign.json").write_text(json.dumps({"id": campaign_id(cfg), "offline": False, "seeds": [1]}))
    prepare.run_prepare(meta, conf, tmp_path / "pre")
    for seed in (11, 12):
        assert job.run_replica(meta, conf, seed, tmp_path / f"ob{seed}", tmp_path / "pre" / "process.tar.gz") == 0
    import tarfile
    for seed in (11, 12):
        with tarfile.open(tmp_path / f"ob{seed}" / f"{campaign_id(cfg)}_s{seed:04d}.logs.tar.gz") as t:
            rc = next(n for n in t.getnames() if n.endswith("run_card.dat"))
            body = t.extractfile(rc).read().decode()
        assert f" {seed} = iseed" in body


def test_local_campaign_builds_the_process_once(local_env):
    c = sub.submit(bcfg("execution.replicas=3", "execution.seed_start=30", build_once=True))
    text, by = sub.status_text(c)
    assert len(by["ok"]) == 3 and "process build: ok" in text
    assert (c.dir / "prepare" / "outbox" / "process.tar.gz").is_file()
    import tarfile
    built = 0
    for s in (30, 31, 32):
        with tarfile.open(c.outbox(s) / f"{c.id}_{tag(s)}.logs.tar.gz") as t:
            built += sum(n.endswith("proc.log") for n in t.getnames())
    assert built == 0                                           # no replica generated the process itself
    assert col.collect(c)["ok"] == 3


def test_failed_build_stops_a_local_campaign_early(local_env, monkeypatch):
    monkeypatch.setenv("FAKE_MG5_NO_PROCESS", "1")
    with pytest.raises(MegError, match="building the MG5 process failed"):
        sub.submit(bcfg("execution.replicas=3", build_once=True))


def test_htcondor_dag_files(toolchain, fake_condor, monkeypatch):
    monkeypatch.delenv("PIXI_PROJECT_ROOT", raising=False)
    c = sub.submit(bcfg("execution.replicas=3", "execution.cores=2", executor="htcondor", build_once=True),
                   dry_run=True)
    assert (c.dir / "campaign.dag").read_text() == (
        "# PREPARE builds the MG5 process once; REPLICAS (one job per seed) start when it has succeeded\n"
        "JOB PREPARE prepare.sub\nJOB REPLICAS submit.sub\nPARENT PREPARE CHILD REPLICAS\n")
    prep = (c.dir / "prepare.sub").read_text()
    assert "executable" in prep and "prepare.sh" in prep and f"initialdir = {c.dir / 'prepare'}" in prep
    assert "request_cpus = 2" in prep and prep.rstrip().endswith("queue")
    assert "meg _prepare" in (c.dir / "prepare.sh").read_text()
    archive = c.dir / "prepare" / "outbox" / "process.tar.gz"
    assert f"{archive}" in (c.dir / "submit.sub").read_text().split("transfer_input_files = ")[1].splitlines()[0]
    assert "arguments = $(seed)\n" in (c.dir / "submit.sub").read_text()
    # by path instead of transferring it to every job
    c2 = sub.submit(bcfg("execution.replicas=3", "execution.process_transfer=false", executor="htcondor",
                         build_once=True, name="bypath"), dry_run=True)
    text = (c2.dir / "submit.sub").read_text()
    assert f"arguments = $(seed) {c2.dir / 'prepare' / 'outbox' / 'process.tar.gz'}" in text
    assert "process.tar.gz" not in text.split("transfer_input_files = ")[1].splitlines()[0]
    assert not fake_condor.exists()


def test_htcondor_dag_submission_and_status(toolchain, fake_condor, tmp_path, monkeypatch):
    monkeypatch.delenv("PIXI_PROJECT_ROOT", raising=False)
    c = sub.submit(bcfg("execution.replicas=3", "execution.seed_start=5", executor="htcondor", build_once=True))
    calls = fake_condor.read_text()
    assert "dag -f campaign.dag" in calls and f"cwd={c.dir}" in calls and "submit.sub" not in calls.split("dag")[0]
    assert c.meta["submissions"][0]["dag_cluster"] == 777
    q = tmp_path / "queue.json"
    # the PREPARE job is queued; no replica jobs exist yet
    q.write_text(json.dumps([{"JobStatus": 1}]))
    states, _ = sub.seed_states(c)
    assert {v[0] for v in states.values()} == {"waiting"}
    assert "process build: not finished yet" in sub.status_text(c)[0]
    # PREPARE finished, replicas running / held
    (c.dir / "prepare" / "outbox").mkdir(parents=True)
    (c.dir / "prepare" / "outbox" / "status.json").write_text(json.dumps({"state": "ok"}))
    q.write_text(json.dumps([{"Args": "5", "JobStatus": 2}, {"Args": "6", "JobStatus": 5, "HoldReason": "no disk"},
                             {"Args": "7", "JobStatus": 1}]))
    states, _ = sub.seed_states(c)
    assert [states[s][0] for s in (5, 6, 7)] == ["running", "held", "idle"]
    # PREPARE finished, DAGMan gone, nothing queued, no results: lost
    q.write_text("[]")
    assert {v[0] for v in sub.seed_states(c)[0].values()} == {"lost"}
    assert sub.cancel(c) == [777] and "rm 777" in fake_condor.read_text()


def test_failed_prepare_blocks_replicas_and_resubmit_rebuilds(toolchain, fake_condor, tmp_path, monkeypatch):
    monkeypatch.delenv("PIXI_PROJECT_ROOT", raising=False)
    c = sub.submit(bcfg("execution.replicas=3", "execution.seed_start=1", executor="htcondor", build_once=True))
    (c.dir / "prepare" / "outbox").mkdir(parents=True)
    (c.dir / "prepare" / "outbox" / "status.json").write_text(
        json.dumps({"state": "failed", "error": "StageError: no diagrams"}))
    (tmp_path / "queue.json").write_text("[]")
    states, _ = sub.seed_states(c)
    assert {v[0] for v in states.values()} == {"blocked"} and "no diagrams" in states[1][1]
    text = sub.status_text(c)[0]
    assert "process build: FAILED" in text and "meg resubmit" in text
    assert sub.resubmit(c) == [1, 2, 3]
    assert not (c.dir / "prepare" / "outbox").exists()                          # rebuilt from scratch
    assert (c.dir / "campaign_2.dag").read_text().splitlines()[2] == "JOB REPLICAS submit_2.sub"
    assert "dag -f campaign_2.dag" in fake_condor.read_text()
    assert Campaign.load(c.dir).meta["submissions"][1]["dag_cluster"] == 777


def test_resubmit_after_a_good_build_only_reruns_replicas(toolchain, fake_condor, tmp_path, monkeypatch):
    monkeypatch.delenv("PIXI_PROJECT_ROOT", raising=False)
    c = sub.submit(bcfg("execution.replicas=2", "execution.seed_start=1", executor="htcondor", build_once=True))
    (c.dir / "prepare" / "outbox").mkdir(parents=True)
    (c.dir / "prepare" / "outbox" / "status.json").write_text(json.dumps({"state": "ok"}))
    (c.dir / "prepare" / "outbox" / "process.tar.gz").write_text("x")
    (tmp_path / "queue.json").write_text("[]")
    assert sub.resubmit(c) == [1, 2]
    calls = fake_condor.read_text()
    assert "submit_2.sub" in calls and "campaign_2.dag" not in calls
    assert (c.dir / "prepare" / "outbox" / "process.tar.gz").is_file()


def test_generated_job_script_uses_the_prebuilt_process(toolchain, fake_condor, tmp_path, monkeypatch):
    import shutil
    import subprocess
    monkeypatch.delenv("PIXI_PROJECT_ROOT", raising=False)
    monkeypatch.setenv("PYTHONPATH", str(SRC))
    meg_bin = toolchain / "bin" / "meg"
    meg_bin.write_text(f"#!/bin/sh\nexec {sys.executable} -m meg \"$@\"\n")
    meg_bin.chmod(0o755)
    c = sub.submit(bcfg("execution.replicas=2", executor="htcondor", build_once=True), dry_run=True)
    env = {k: v for k, v in os.environ.items() if k != "CONDA_PREFIX"} | {"PATH": "/usr/bin:/bin"}
    # node 1: PREPARE
    n1 = tmp_path / "node1"
    n1.mkdir()
    for f in ("campaign.json", "config.json", "env.sh", "prepare.sh"):
        shutil.copy(c.dir / f, n1 / f)
    r = subprocess.run(["bash", "prepare.sh"], cwd=n1, env=env | {"TMPDIR": str(n1)}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:] + r.stdout[-1500:]
    assert (n1 / "outbox" / "process.tar.gz").is_file()
    # node 2: a replica, with the archive transferred in beside the other inputs
    n2 = tmp_path / "node2"
    n2.mkdir()
    for f in ("campaign.json", "config.json", "env.sh", "job.sh"):
        shutil.copy(c.dir / f, n2 / f)
    shutil.copy(n1 / "outbox" / "process.tar.gz", n2 / "process.tar.gz")
    r = subprocess.run(["bash", "job.sh", "1"], cwd=n2, env=env | {"TMPDIR": str(n2)}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:] + r.stdout[-1500:]
    import tarfile
    with tarfile.open(next((n2 / "outbox").glob("*.logs.tar.gz"))) as t:
        assert not any(n.endswith("proc.log") for n in t.getnames())
    # node 3: by-path variant, no transfer: the archive is the second argument
    n3 = tmp_path / "node3"
    n3.mkdir()
    for f in ("campaign.json", "config.json", "env.sh", "job.sh"):
        shutil.copy(c.dir / f, n3 / f)
    r = subprocess.run(["bash", "job.sh", "2", str(n1 / "outbox" / "process.tar.gz")], cwd=n3,
                       env=env | {"TMPDIR": str(n3)}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:] + r.stdout[-1500:]


def test_output_dir_with_a_prebuilt_process(local_env, tmp_path):
    eos = tmp_path / "eos"
    c = sub.submit(bcfg("execution.replicas=2", f'execution.output_dir="{eos}"', build_once=True))
    assert (eos / c.id / f"{c.id}_s0001.delphes.root").is_file()
    assert [p.name for p in c.outbox(2).iterdir()] == ["status.json"]
    assert col.collect(c, verify=True)["ok"] == 2
