"""Fixture: a fake conda prefix with fake MG5/Delphes/Herwig, selected through PATH/CONDA_PREFIX."""
import json
import stat
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

HERWIG_TEMPLATE = """\
read snippets/PPCollider.in
set LesHouchesReader:FileName events.lhe
set /Herwig/Partons/LHAPDF:PDFName NNPDF30
set EventGenerator:NumberOfEvents 10
set EventGenerator:RandomNumberGenerator:Seed 1
saverun LHE EventGenerator
"""


def _script(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\nimport sys; sys.path.insert(0, {str(HERE)!r})\n"
                    f"import fake_tools\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def toolchain(tmp_path, monkeypatch):
    prefix = tmp_path / "prefix"
    for d in ("bin", "input", "models/sm", "models/loop_sm", "share/Herwig",
              "HEPTools/MG5aMC_PY8_interface", "HEPTools/ninja/lib", "conda-meta", "share/LHAPDF"):
        (prefix / d).mkdir(parents=True)
    (prefix / "models" / "loop_sm" / "restrict_no_b_mass.dat").write_text("# restriction\n")
    (prefix / "HEPTools/ninja/lib/libninja.a").write_text("x")
    (prefix / "input" / "mg5_configuration.txt").write_text("# pythia8_path = None\n")
    (prefix / "VERSION").write_text("version = 3.6.0\n")
    (prefix / "HEPTools/MG5aMC_PY8_interface/MG5aMC_PY8_interface").write_text("x")
    _script(prefix / "bin" / "mg5_aMC", "fake_tools.mg5(sys.argv[1:])")
    _script(prefix / "bin" / "DelphesLHEF", "fake_tools.delphes(sys.argv[1:], 'LHEF')")
    _script(prefix / "bin" / "DelphesHepMC2", "fake_tools.delphes(sys.argv[1:], 'HepMC2')")
    _script(prefix / "bin" / "DelphesHepMC3", "fake_tools.delphes(sys.argv[1:], 'HepMC3')")
    _script(prefix / "bin" / "Herwig", "fake_tools.herwig(sys.argv[1:])")
    for t in ("lhapdf-config", "lhapdf", "fastjet-config", "pythia8-config", "gfortran"):
        _script(prefix / "bin" / t, "print('stub 1.0')")
    for name in ("LHE.in", "LHE-MCatNLO.in"):
        (prefix / "share" / "Herwig" / name).write_text(HERWIG_TEMPLATE)
    for i, s in enumerate(("NNPDF30_nlo_as_0118", "NNPDF23_lo_as_0130_qed", "CT14lo", "CT14nlo")):
        (prefix / "share/LHAPDF" / s).mkdir()
        (prefix / "share/LHAPDF" / s / f"{s}.info").write_text(f"SetIndex: {260000 + i}\n")
    (prefix / "conda-meta" / "pythia8-8.3-0.json").write_text(
        json.dumps({"name": "pythia8", "version": "8.3", "build": "0", "channel": "conda-forge"}))

    import os
    monkeypatch.setenv("CONDA_PREFIX", str(prefix))
    monkeypatch.setenv("PATH", f"{prefix / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_MG5_ROOT", str(prefix))
    monkeypatch.setenv("MEG_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("MEG_MODELS_LOCK", str(tmp_path / "models.lock"))
    monkeypatch.delenv("MEG_OFFLINE", raising=False)
    monkeypatch.delenv("FAKE_DELPHES_ERROR", raising=False)
    monkeypatch.delenv("FAKE_HEPMC_FORMAT", raising=False)
    monkeypatch.delenv("FAKE_MG5_SLEEP", raising=False)
    monkeypatch.delenv("FAKE_MADSPIN_NO_OUTPUT", raising=False)
    monkeypatch.delenv("FAKE_MADSPIN_NO_CARD", raising=False)
    monkeypatch.delenv("MG5_BIN", raising=False)
    monkeypatch.chdir(tmp_path)
    import meg.sysenv
    import meg.toolchain
    monkeypatch.setattr(meg.sysenv, "is_macos", lambda: False)
    monkeypatch.setattr(meg.toolchain, "is_macos", lambda: False)
    return prefix
