"""End-to-end flows with the fake toolchain: what runs, in what order, and how failures look."""
import json
import os

import pytest

import meg
from meg import cli
from meg.util import MegError, StageError
from test_unit import _make_ufo_tar


def cfg(*over, name="t"):
    return meg.load_config(None, [f'run.name="{name}"', "generation.events=7", *over])


def test_lo_parton_level_delphes_lhef(toolchain):
    r = meg.run(cfg('shower.kind="none"'))
    assert r.cross_section_pb == pytest.approx(508.9)
    assert r.manifest["delphes"]["entries"] == 7 and r.manifest["lhe"]["events"] == 7
    assert r.delphes_root.name == "delphes.root"
    # run card edited, and builtin PDF switched LHAPDF off
    rc = (r.run_dir / "generate/mg5_proc/Cards/run_card.dat").read_text()
    assert " 7 = nevents" in rc and " 1 = iseed" in rc and "nn23lo1" in rc
    assert "set lhapdf_py3 None" in (r.run_dir / "generate/proc.mg5").read_text()
    # MG5 got configured once
    assert "pythia8_path" in (toolchain / "input/mg5_configuration.txt").read_text()


def test_lo_pythia8_uses_the_menu_and_legacy_reader(toolchain):
    r = meg.run(cfg())
    launch = (r.run_dir / "generate/launch.mg5").read_text().splitlines()
    assert launch[-4:] == ["launch mg5_proc", "shower=Pythia8", "done", "done"]
    assert r.manifest["delphes"]["entries"] == 7
    assert "DelphesHepMC2" in (r.run_dir / "detector/delphes.log").read_text().split("\n")[0]


@pytest.mark.parametrize("fmt,reader", [("legacy", "DelphesHepMC2"), ("v3", "DelphesHepMC3")])
def test_lo_herwig_reader_follows_header(toolchain, monkeypatch, fmt, reader):
    monkeypatch.setenv("FAKE_HEPMC_FORMAT", fmt)
    r = meg.run(cfg('shower.kind="herwig7"'))
    assert reader in (r.run_dir / "detector/delphes.log").read_text().split("\n")[0]
    assert r.manifest["delphes"]["entries"] == 7
    hw = (r.run_dir / "shower/hw7.in").read_text()
    assert "PDFName NNPDF23_lo_as_0130_qed" in hw          # builtin LO PDF -> its LHAPDF twin


def test_nlo_pythia8(toolchain):
    r = meg.run(cfg('process.order="NLO"', "generation.nlo_accuracy=0.05"))
    rc = (r.run_dir / "generate/mg5_proc/Cards/run_card.dat").read_text()
    assert "PYTHIA8 = parton_shower" in rc and ".false. = reweight_scale" in rc
    assert " 0.05 = req_acc" in rc and "'lhapdf' = pdlabel" in rc and " 260000 = lhaid" in rc
    assert " 7 = nevt_job" in rc
    assert "generate p p > t t~ [QCD]" in (r.run_dir / "generate/proc.mg5").read_text()
    assert "shower=PYTHIA8" in (r.run_dir / "generate/launch.mg5").read_text()


def test_nlo_herwig7_switches_mg5_shower_off(toolchain):
    r = meg.run(cfg('process.order="NLO"', 'shower.kind="herwig7"'))
    assert "shower=OFF" in (r.run_dir / "generate/launch.mg5").read_text()
    assert "HERWIGPP = parton_shower" in (r.run_dir / "generate/mg5_proc/Cards/run_card.dat").read_text()
    assert "PDFName NNPDF30_nlo_as_0118" in (r.run_dir / "shower/hw7.in").read_text()


def test_user_run_card_has_the_last_word_and_typos_fail(toolchain):
    r = meg.run(cfg('shower.kind="none"', "generation.run_card.ptj=35.0"))
    assert " 35.0 = ptj" in (r.run_dir / "generate/mg5_proc/Cards/run_card.dat").read_text()
    with pytest.raises(MegError, match="ptjj"):
        meg.run(cfg('shower.kind="none"', "generation.run_card.ptjj=1", name="typo"))


def test_detector_none_stops_after_generation(toolchain):
    r = meg.run(cfg('detector.kind="none"'))
    assert r.delphes_root is None and r.lhe is not None and "delphes" not in r.manifest


def test_resume_skips_and_reruns_only_what_changed(toolchain):
    meg.run(cfg('shower.kind="herwig7"'))
    r = meg.run(cfg('shower.kind="herwig7"'))
    assert set(r.manifest["stages"].values()) >= {"cached"} and r.manifest["stages"]["generate"] == "cached"
    assert r.manifest["stages"]["shower"] == "cached" and r.manifest["stages"]["detector"] == "cached"
    # a different Delphes card re-runs only the detector
    card = os.path.abspath("my.tcl")
    open(card, "w").write("# card\n")
    r = meg.run(cfg('shower.kind="herwig7"', f'detector.card="{card}"'))
    st = r.manifest["stages"]
    assert (st["generate"], st["shower"]) == ("cached", "cached") and st["detector"] != "cached"
    # a different seed re-runs everything
    r = meg.run(cfg('shower.kind="herwig7"', "run.seed=2", f'detector.card="{card}"'))
    assert r.manifest["stages"]["generate"] != "cached"


def test_force_and_refusing_foreign_directories(toolchain):
    meg.run(cfg('shower.kind="none"'))
    r = meg.run(cfg('shower.kind="none"'), force=True)
    assert r.manifest["stages"]["generate"] != "cached"
    os.makedirs("results/foreign")
    open("results/foreign/precious.txt", "w").write("x")
    with pytest.raises(MegError, match="not a MEG run directory"):
        meg.run(cfg(name="foreign"), force=True)
    assert os.path.exists("results/foreign/precious.txt")


def test_mg5_error_with_exit_zero_is_caught_and_diagnosed(toolchain):
    with pytest.raises(StageError, match="exited 0 but reported") as ei:
        meg.run(cfg('process.extra_commands=["import model zzz"]', name="bad"))
    assert ei.value.diag and ei.value.diag.is_file()
    text = ei.value.diag.read_text()
    assert "### error" in text and "interrupted with error" in text and "### resolved configuration" in text


def test_delphes_error_exit_zero_is_caught(toolchain, monkeypatch):
    monkeypatch.setenv("FAKE_DELPHES_ERROR", "1")
    with pytest.raises(StageError, match=r"\*\* ERROR"):
        meg.run(cfg('shower.kind="none"', name="d"))


def test_wrong_reader_empty_output_is_caught(toolchain, monkeypatch):
    # Herwig writes HepMC3 but the header says legacy: a mismatch must not pass silently
    monkeypatch.setenv("FAKE_HEPMC_FORMAT", "v3")
    import meg.delphes
    monkeypatch.setattr(meg.delphes, "hepmc_header", lambda p: "HepMC::IO_GenEvent")
    with pytest.raises(StageError):
        meg.run(cfg('shower.kind="herwig7"', name="w"))


def test_ufo_model_with_parameters(toolchain, tmp_path):
    arc, h = _make_ufo_tar(tmp_path)
    c = cfg('shower.kind="none"', 'model.name="MyUfo"', 'model.restriction="massless"',
            f'model.url="file://{arc}"', f'model.sha256="{h}"', 'model.subdir="UFO"',
            "model.params.SMEFT:1=0.25", name="ufo")
    r = meg.run(c)
    assert r.manifest["model"]["tree_sha256"] and "MyUfo" in r.manifest["model"]["name"]
    proc_in = (r.run_dir / "generate/proc.mg5").read_text()
    assert "import model " in proc_in and proc_in.count("-massless") == 1 and "MyUfo__" in proc_in
    pc = (r.run_dir / "generate/mg5_proc/Cards/param_card.dat").read_text()
    assert "1 0.25 # cHW" in pc and pc.count("0.000000e+00 # cHW") == 1       # only the SMEFT block entry
    # a name that two blocks share must be reported, not guessed
    with pytest.raises(MegError, match="matches 2"):
        meg.run(cfg('shower.kind="none"', 'model.name="MyUfo"', f'model.url="file://{arc}"',
                    f'model.sha256="{h}"', 'model.subdir="UFO"', "model.params.cHW=1", name="amb"))


def test_manifest_contents(toolchain):
    r = meg.run(cfg())
    m = json.loads(r.manifest_path.read_text())
    assert m["config"]["run"]["seed"] == 1 and m["toolchain"]["mg5_version"] == "3.6.0"
    assert m["toolchain"]["packages"]["pythia8"]["version"] == "8.3"
    assert m["model"] == {"name": "sm", "builtin": True} and len(m["delphes"]["sha256"]) == 64
    assert set(m["stages"]) >= {"inputs", "generate", "detector"}


# ---- CLI
def test_cli_plan_init_and_errors(toolchain, capsys):
    assert cli.main(["plan", "--set", 'process.order="NLO"']) == 0
    assert "[QCD]" in capsys.readouterr().out
    assert cli.main(["init", "x.toml"]) == 0 and cli.main(["init", "x.toml"]) == 1
    assert cli.main(["plan", "x.toml"]) == 0
    assert cli.main(["plan", "--set", "shower.kidn=1"]) == 1
    assert "Extra inputs" in capsys.readouterr().err


def test_cli_run_prints_summary_and_failure_points_to_diag(toolchain, capsys):
    assert cli.main(["generate", "-q", "--set", 'run.name="c"', "--set", "generation.events=3"]) == 0
    out = capsys.readouterr().out
    assert "cross-section : 508.9" in out and "Delphes ROOT" in out and "3 entries" in out
    bad = ["--set", 'process.extra_commands=["import model zzz"]', "--set", 'run.name="c2"']
    assert cli.main(["generate", "-q", *bad]) == 1
    assert "diagnostics written to" in capsys.readouterr().err


def test_cli_doctor(toolchain, capsys):
    assert cli.main(["doctor"]) == 0
    assert "RESULT: ok" in capsys.readouterr().out


# ---- saving event files
def test_nothing_saved_by_default(toolchain):
    r = meg.run(cfg())
    assert r.saved_lhe is None and r.saved_hepmc is None and not (r.run_dir / "output").exists()
    assert "output" not in meg.build_plan(cfg()).stages


def test_save_lhe_and_hepmc_compressed(toolchain):
    import gzip
    r = meg.run(cfg("output.lhe=true", "output.hepmc=true"))
    assert r.saved_lhe.name == "t.lhe.gz" and r.saved_hepmc.name == "t.hepmc.gz"
    assert gzip.open(r.saved_lhe, "rt").read().count("<event>") == 7
    assert "HepMC::IO_GenEvent" in gzip.open(r.saved_hepmc, "rt").read()
    assert r.manifest["saved"] == {"lhe": "output/t.lhe.gz", "hepmc": "output/t.hepmc.gz"}


def test_save_uncompressed_is_a_hard_link(toolchain):
    r = meg.run(cfg("output.lhe=true", "output.compress=false"))
    assert r.saved_lhe.name == "t.lhe" and r.saved_hepmc is None
    assert os.stat(r.saved_lhe).st_nlink >= 2            # no second copy on disk


def test_save_herwig_hepmc_and_resume_adds_it_late(toolchain):
    meg.run(cfg('shower.kind="herwig7"'))
    r = meg.run(cfg('shower.kind="herwig7"', "output.hepmc=true"))        # same run dir, now ask for it
    assert r.manifest["stages"]["generate"] == "cached" and r.manifest["stages"]["shower"] == "cached"
    assert r.saved_hepmc.is_file() and "HepMC::IO_GenEvent" in __import__("gzip").open(r.saved_hepmc, "rt").read()


def test_save_works_without_detector(toolchain):
    r = meg.run(cfg('detector.kind="none"', "output.lhe=true"))
    assert r.saved_lhe.is_file() and r.delphes_root is None


def test_hepmc_without_shower_is_a_config_error():
    with pytest.raises(MegError, match="no HepMC"):
        meg.load_config(None, ['shower.kind="none"', "output.hepmc=true"])


def test_mg5_shortcut_runs_in_workdir_with_fixed_env(toolchain, monkeypatch, tmp_path):
    seen = {}

    def fake_exec(path, argv, env):
        seen.update(path=path, argv=argv, env=env, cwd=os.getcwd())
        raise SystemExit(0)

    monkeypatch.setattr(os, "execve", fake_exec)
    (tmp_path / "cmds.mg5").write_text("help\n")
    with pytest.raises(SystemExit):
        cli.main(["mg5", "cmds.mg5", "-h"])
    assert seen["cwd"] == str(tmp_path / "work") and seen["path"].endswith("mg5_aMC")
    assert seen["argv"][1:] == [str(tmp_path / "cmds.mg5"), "-h"]      # file resolved, flag untouched
    assert "-std=c++14" in seen["env"]["CXXFLAGS"]


# ---- MadSpin: the decay syntax is the user's own
INCL = ['madspin.decays=["t > w+ b, w+ > all all", "t~ > w- b~, w- > all all"]']


def test_madspin_uses_the_users_decays_and_the_decayed_events(toolchain):
    r = meg.run(cfg("madspin.enable=true", *INCL))
    launch = (r.run_dir / "generate/launch.mg5").read_text().splitlines()
    assert launch[-5:] == ["launch mg5_proc", "shower=Pythia8", "madspin=ON", "done", "done"]
    card = (r.run_dir / "generate/mg5_proc/Cards/madspin_card.dat").read_text()
    assert card.splitlines() == ["# written by MEG", "set seed 1", "decay t > w+ b, w+ > all all",
                                 "decay t~ > w- b~, w- > all all", "launch"]
    # the decayed run (xsec 120) is used, not the undecayed one (508.9)
    assert r.cross_section_pb == pytest.approx(120.0)
    assert r.manifest["delphes"]["entries"] == 7
    assert r.manifest["config"]["madspin"]["decays"][0] == "t > w+ b, w+ > all all"


def test_madspin_define_options_and_optional_keywords(toolchain):
    r = meg.run(cfg("madspin.enable=true",
                    'madspin.decays=["t > w+ b, w+ > l+ vl", "decay t~ > w- b~, w- > j j"]',
                    'madspin.define=["l+ = e+ mu+", "define vl = ve vm"]',
                    "madspin.options.BW_cut=15", 'madspin.options.spinmode="onshell"', "run.seed=5"))
    card = (r.run_dir / "generate/mg5_proc/Cards/madspin_card.dat").read_text().splitlines()
    assert card == ["# written by MEG", "set seed 5", "set BW_cut 15", "set spinmode onshell",
                    "define l+ = e+ mu+", "define vl = ve vm",       # keyword accepted but not doubled
                    "decay t > w+ b, w+ > l+ vl", "decay t~ > w- b~, w- > j j", "launch"]


def test_madspin_without_shower_and_with_nlo_herwig(toolchain):
    r = meg.run(cfg("madspin.enable=true", *INCL, 'shower.kind="none"', name="a"))
    assert (r.run_dir / "generate/launch.mg5").read_text().splitlines()[-3:] == ["madspin=ON", "done", "done"]
    assert r.cross_section_pb == pytest.approx(120.0)
    r = meg.run(cfg("madspin.enable=true", *INCL, 'process.order="NLO"', 'shower.kind="herwig7"', name="b"))
    assert "shower=OFF" in (r.run_dir / "generate/launch.mg5").read_text()
    assert r.manifest["delphes"]["entries"] == 7 and r.cross_section_pb == pytest.approx(120.0)


def test_madspin_enable_needs_decays():
    with pytest.raises(MegError, match="needs 'decays'"):
        meg.load_config(None, ["madspin.enable=true"])
    with pytest.raises(MegError, match="Extra inputs"):
        meg.load_config(None, ['madspin.channel="dilepton"'])          # the old preset key is gone
    # decays given but not enabled: allowed, and nothing happens (easy to toggle with --set)
    assert not meg.build_plan(meg.load_config(None, INCL)).madspin


def test_madspin_that_silently_did_nothing_is_an_error(toolchain, monkeypatch):
    monkeypatch.setenv("FAKE_MADSPIN_NO_OUTPUT", "1")
    with pytest.raises(StageError, match="no decayed events"):
        meg.run(cfg("madspin.enable=true", *INCL, name="m"))


def test_madspin_off_is_unchanged(toolchain):
    r = meg.run(cfg(*INCL))                       # decays listed but enable is false
    assert not (r.run_dir / "generate/mg5_proc/Cards/madspin_card.dat").exists()
    assert "madspin" not in (r.run_dir / "generate/launch.mg5").read_text()
    assert r.cross_section_pb == pytest.approx(508.9)


# ---- how much is printed
def test_progress_lines_and_logs(toolchain, capsys):
    assert cli.main(["generate", "-q", "--set", 'run.name="q1"', "--set", "generation.events=3"]) == 0
    cap = capsys.readouterr()
    assert "stage generate  running" in cap.err and "stage generate  done in" in cap.err
    assert "cross-section" in cap.out
    assert "fake mg5: launched" in open("results/q1/generate/launch.log").read()


def test_default_shows_mg5_output_without_the_noise(toolchain, capsys):
    cli.main(["generate", "--set", 'run.name="q2"', "--set", "generation.events=3"])
    out = capsys.readouterr().out
    assert "fake mg5: imported" in out and "run_card missed argument" not in out


def test_v_shows_everything(toolchain, capsys):
    cli.main(["generate", "-v", "--set", 'run.name="q3"', "--set", "generation.events=3"])
    assert "run_card missed argument" in capsys.readouterr().out


def test_quiet_hides_tool_output_but_keeps_progress(toolchain, capsys):
    cli.main(["generate", "-q", "--set", 'run.name="q4"', "--set", "generation.events=3"])
    cap = capsys.readouterr()
    assert "fake mg5" not in cap.out and "cross-section" in cap.out and "stage generate  done" in cap.err


def test_failure_shows_the_end_of_the_hidden_log(toolchain, capsys):
    bad = ["--set", 'process.extra_commands=["import model zzz"]', "--set", 'run.name="q5"']
    assert cli.main(["generate", "-q", *bad]) == 1
    err = capsys.readouterr().err
    assert "end of the log" in err and "Model not found" in err and "diag.txt" in err


def test_heartbeat_while_a_tool_is_silent(tmp_path, caplog):
    import logging
    import sys

    from meg import proc
    caplog.set_level(logging.INFO, logger="meg")
    proc.run([sys.executable, "-c", "import time; time.sleep(0.5)"], log_file=tmp_path / "l.log", cwd=tmp_path,
             env=os.environ, heartbeat=0.1)
    assert any("still running" in r.message for r in caplog.records)


# ---- stopping a run
def _alive(pid: int) -> bool:
    try:
        return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


def test_ctrl_c_stops_the_tool_and_everything_it_started(toolchain, capsys, monkeypatch):
    import re
    import signal
    import threading
    import time

    from meg import proc
    monkeypatch.setattr(proc, "TERMINATE_GRACE", 0.3)
    monkeypatch.setenv("FAKE_MG5_SLEEP", "120")
    threading.Timer(1.5, os.kill, (os.getpid(), signal.SIGINT)).start()
    t0 = time.time()
    rc = cli.main(["generate", "-q", "--set", 'run.name="stop"'])
    assert rc == 130 and time.time() - t0 < 20
    assert "interrupted" in capsys.readouterr().err
    log = open("results/stop/generate/proc.log").read()
    assert "busy" in log
    # the tool ignored SIGINT and SIGTERM-resistant grandchildren existed: all must be gone
    time.sleep(0.5)
    out = os.popen("ps -eo pid,args").read()
    assert not re.search(r"time\.sleep\(120\)", out)
    # the interrupted stage left no completion record, so the same command runs it again
    monkeypatch.delenv("FAKE_MG5_SLEEP")
    assert cli.main(["generate", "-q", "--set", 'run.name="stop"', "--set", "generation.events=3"]) == 0


def test_sigterm_also_stops_cleanly(toolchain, capsys, monkeypatch):
    import signal
    import threading

    from meg import proc
    monkeypatch.setattr(proc, "TERMINATE_GRACE", 0.3)
    monkeypatch.setenv("FAKE_MG5_SLEEP", "120")
    threading.Timer(1.5, os.kill, (os.getpid(), signal.SIGTERM)).start()
    assert cli.main(["generate", "-q", "--set", 'run.name="term"']) == 130
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def test_run_is_still_accepted_as_an_alias(toolchain, capsys):
    assert cli.main(["run", "-q", "--set", 'run.name="alias"', "--set", "generation.events=3"]) == 0
    assert "cross-section" in capsys.readouterr().out


def test_python_api_generate_is_run():
    assert meg.generate is meg.run


def test_builtin_model_with_restriction(toolchain):
    from meg import toolchain as tc
    mg5 = tc.locate_mg5({})
    assert mg5.is_builtin_model("sm")
    assert mg5.is_builtin_model("loop_sm-no_b_mass")       # MG5 'model-restriction' syntax
    assert not mg5.is_builtin_model("loop_sm-nonexistent")
    assert not mg5.is_builtin_model("SMEFTsim_general_MwScheme_UFO")


def test_ninja_detection_and_nlo_skips_install_when_present(toolchain):
    from meg import toolchain as tc
    mg5 = tc.locate_mg5({})
    assert mg5.has_ninja()
    tc.ensure_loop_tools(mg5, {})                  # nothing to do, must not start MG5
    (mg5.root / "HEPTools/ninja/lib/libninja.a").unlink()
    assert not mg5.has_ninja()
