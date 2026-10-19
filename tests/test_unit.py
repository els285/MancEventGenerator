from pathlib import Path

import pytest

from meg import cards, delphes, herwig, models
from meg.config import load_config
from meg.plan import build_plan
from meg.util import MegError


# ---- config
def test_defaults_lo():
    c = load_config(None)
    assert (c.model.name, c.generation.pdf, c.process.definition) == ("sm", "builtin", "p p > t t~")


def test_defaults_nlo_and_overrides():
    c = load_config(None, ["process.order=\"NLO\"", "generation.events=50", "shower.kind=herwig7",
                           "model.params.cHW=0.1"])
    assert c.model.name == "loop_sm-no_b_mass" and c.generation.pdf == "NNPDF30_nlo_as_0118"
    assert c.generation.events == 50 and c.model.params == {"cHW": 0.1}


@pytest.mark.parametrize("over,msg", [
    (["shower.kidn=1"], "Extra inputs"),
    (["shower.kind=\"pythia9\""], "pythia8"),
    (["process.order=\"NLO\"", "shower.kind=\"none\""], "NLO"),
    (["process.order=\"NLO\"", "generation.pdf=\"builtin\""], "builtin"),
    (["model.git=\"https://x\"", "model.name=\"M\""], "rev"),
    (["generation.events=0"], "greater than 0"),
    (["run.name=\"a b\""], "letters"),
])
def test_config_errors(over, msg):
    with pytest.raises(MegError, match=msg):
        load_config(None, over)


def test_load_toml_file(tmp_path):
    p = tmp_path / "r.toml"
    p.write_text('[run]\nname = "x"\n[generation]\nevents = 7\n')
    assert load_config(p).generation.events == 7
    with pytest.raises(MegError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_fingerprint_ignores_output_location():
    a, b = load_config(None, ["run.name=\"a\""]), load_config(None, ["run.name=\"b\""])
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != load_config(None, ["run.seed=2"]).fingerprint()


# ---- plan
def test_plan_switches():
    def p(*o):
        return build_plan(load_config(None, list(o)))
    assert p().mg5_shower_switch == "Pythia8" and p().stages == ("inputs", "generate", "detector", "manifest")
    assert p("shower.kind=\"none\"").mg5_shower_switch is None
    nlo = p("process.order=\"NLO\"")
    assert (nlo.mg5_shower_switch, nlo.parton_shower, nlo.mg5_process) == ("PYTHIA8", "PYTHIA8", "p p > t t~ [QCD]")
    hw = p("process.order=\"NLO\"", "shower.kind=\"herwig7\"")
    assert (hw.mg5_shower_switch, hw.parton_shower) == ("OFF", "HERWIGPP")
    assert "shower" in hw.stages and hw.herwig_pdf == "NNPDF30_nlo_as_0118"
    lo_hw = p("shower.kind=\"herwig7\"")
    assert lo_hw.mg5_shower_switch is None and lo_hw.herwig_pdf == "NNPDF23_lo_as_0130_qed"
    assert "CT14lo" in lo_hw.pdf_sets and not lo_hw.uses_lhapdf


def test_nlo_keeps_user_brackets():
    c = load_config(None, ["process.order=\"NLO\"", "process.definition=\"p p > t t~ [QED]\""])
    assert build_plan(c).mg5_process == "p p > t t~ [QED]"


# ---- cards
RUN = "  100 = nevents ! n\n  0 = iseed ! s\n  nn23lo1 = pdlabel ! pdf\n  .true. = use_syst ! x\n"


def test_run_card_edit(tmp_path):
    p = tmp_path / "run_card.dat"
    p.write_text(RUN)
    cards.edit_run_card(p, {"NEVENTS": 5, "use_syst": False, "pdlabel": "'lhapdf'"})
    t = p.read_text()
    assert " 5 = nevents" in t and ".false. = use_syst" in t and "'lhapdf' = pdlabel" in t
    assert "! n" in t                       # comments kept


def test_run_card_unknown_key_is_error(tmp_path):
    p = tmp_path / "run_card.dat"
    p.write_text(RUN)
    with pytest.raises(MegError, match="nope"):
        cards.edit_run_card(p, {"nope": 1})
    assert p.read_text() == RUN             # nothing half-written


PARAM = ("BLOCK MASS #\n      6 1.73e+02 # MT\nBlock SMEFT #\n      1 0.0 # cHW\n"
         "Block ALT #\n      1 0.0 # cHW\nDECAY  6 1.35 # WT\n")


def test_param_card_by_name_block_and_decay(tmp_path):
    p = tmp_path / "param_card.dat"
    p.write_text(PARAM)
    cards.edit_param_card(p, {"MT": 172.5, "SMEFT:1": 0.3, "WT": 1.4})
    t = p.read_text()
    assert "6 172.5 # MT" in t and "1 0.3 # cHW" in t and "DECAY  6 1.4 # WT" in t
    assert t.count("0.0 # cHW") == 1       # only the SMEFT one changed


def test_param_card_decay_without_comment(tmp_path):
    p = tmp_path / "param_card.dat"
    p.write_text("Block MASS #\n  6 1.7e2 # MT\nDECAY   6 1.33 \nDECAY  23 2.4952 # WZ\n")
    cards.edit_param_card(p, {"DECAY:6": 1.5, "WZ": 2.5})
    assert "DECAY   6 1.5" in p.read_text() and "DECAY  23 2.5 # WZ" in p.read_text()


def test_param_card_errors(tmp_path):
    p = tmp_path / "param_card.dat"
    p.write_text(PARAM)
    with pytest.raises(MegError, match="matches 2"):
        cards.edit_param_card(p, {"cHW": 1})
    with pytest.raises(MegError, match="not found"):
        cards.edit_param_card(p, {"cXX": 1})


# ---- herwig input
TMPL = ("set LesHouchesReader:FileName a.lhe\nset /Herwig/Partons/LHAPDF:PDFName X\n"
        "set EventGenerator:NumberOfEvents 1\nset EventGenerator:RandomNumberGenerator:Seed 9\n"
        "saverun LHE EventGenerator\n")


def test_herwig_input():
    text, name = herwig.build_input(TMPL, lhe=__import__("pathlib").Path("/x/e.lhe"), pdf="P", events=5, seed=3)
    assert name == "LHE" and "FileName /x/e.lhe" in text and "NumberOfEvents 5" in text
    assert text.index("read snippets/HepMC.in") < text.index("saverun")


def test_herwig_changed_template_fails_loudly():
    with pytest.raises(MegError, match="matched 0"):
        herwig.build_input(TMPL.replace("Seed 9", "Seed9"), lhe=Path("e"), pdf="P", events=1, seed=1)


# ---- delphes reader choice
def test_reader_by_header(tmp_path, toolchain):
    import os
    env = dict(os.environ)
    legacy, v3, lhe = tmp_path / "a.hepmc", tmp_path / "b.hepmc", tmp_path / "c.lhe"
    legacy.write_text("HepMC::Version 2\nHepMC::IO_GenEvent-START_EVENT_LISTING\n")
    v3.write_text("HepMC::Version 3\nHepMC::Asciiv3-START_EVENT_LISTING\n")
    lhe.write_text("<LesHouchesEvents>\n")
    assert delphes.executable_for(legacy, env).endswith("DelphesHepMC2")
    assert delphes.executable_for(v3, env).endswith("DelphesHepMC3")
    assert delphes.executable_for(lhe, env).endswith("DelphesLHEF")


def test_packaged_card_and_missing_card():
    assert delphes.resolve_card("ATLAS").name == "ATLAS.tcl"
    with pytest.raises(MegError, match="neither a file"):
        delphes.resolve_card("nonsense")


# ---- models
def _make_ufo_tar(tmp_path):
    import hashlib
    import io
    import tarfile
    arc = tmp_path / "m.tar.gz"
    with tarfile.open(arc, "w:gz") as t:
        for f in models.REQUIRED + ["restrict_massless.dat"]:
            data = b"# x\n"
            i = tarfile.TarInfo(f"wrap/UFO/{f}")
            i.size = len(data)
            t.addfile(i, io.BytesIO(data))
    return arc, hashlib.sha256(arc.read_bytes()).hexdigest()


def test_model_archive_fetch_lock_and_tamper(tmp_path, toolchain):
    arc, h = _make_ufo_tar(tmp_path)
    spec = {"url": f"file://{arc}", "sha256": h, "subdir": "UFO"}
    m = models.fetch("MyModel", spec, "massless")
    assert m.path.is_dir() and m.restrictions == ["massless"]
    assert models.lock_path().exists()
    # second call: from the cache, even offline
    import os
    os.environ["MEG_OFFLINE"] = "1"
    try:
        assert models.fetch("MyModel", spec).path == m.path
        with pytest.raises(MegError, match="not cached"):
            models.fetch("Other", spec)
    finally:
        del os.environ["MEG_OFFLINE"]
    with pytest.raises(MegError, match="restriction"):
        models.fetch("MyModel", spec, "nope")
    # wrong archive hash
    with pytest.raises(MegError, match="mismatch"):
        models.fetch("Bad", {**spec, "sha256": "0" * 64})


def test_model_name_and_unknown(toolchain):
    with pytest.raises(MegError, match="only letters"):
        models.fetch("bad-name", {"git": "x", "rev": "0" * 40})
    with pytest.raises(MegError, match="unknown model"):
        models.fetch("NotRegistered")
    assert "SMEFTsim_U35_alphaScheme_UFO" in models.registry()
    assert all(len(s["rev"]) == 40 for s in models.registry().values())


def test_tag_instead_of_sha_rejected(toolchain):
    with pytest.raises(MegError, match="40-character"):
        models.fetch("T", {"git": "https://example.invalid/x", "rev": "v3.0.2"})
