"""Real-toolchain runs. Slow (minutes) and need the MEG conda environment:
    pixi run -e dev pytest -m integration
"""
import shutil

import pytest

import meg

pytestmark = pytest.mark.integration

INCLUSIVE = '["t > w+ b, w+ > all all", "t~ > w- b~, w- > all all"]'
DILEPTON = '["t > w+ b, w+ > l+ vl", "t~ > w- b~, w- > l- vl~"]'


@pytest.fixture(autouse=True)
def _need_toolchain():
    if not shutil.which("mg5_aMC"):
        pytest.skip("mg5_aMC not found: run inside the MEG pixi environment")


@pytest.mark.parametrize("over", [
    ['shower.kind="none"'],
    ['shower.kind="pythia8"'],
    ['shower.kind="herwig7"'],
    ['process.order="NLO"', 'shower.kind="pythia8"', "generation.nlo_accuracy=0.05"],
    ['process.order="NLO"', 'shower.kind="herwig7"', "generation.nlo_accuracy=0.05"],
    ["madspin.enable=true", f"madspin.decays={DILEPTON}", 'madspin.define=["l+ = e+ mu+", "l- = e- mu-", '
     '"vl = ve vm", "vl~ = ve~ vm~"]'],
    ["madspin.enable=true", f"madspin.decays={INCLUSIVE}", 'process.order="NLO"', "generation.nlo_accuracy=0.05"],
], ids=["lo-none", "lo-py8", "lo-hw7", "nlo-py8", "nlo-hw7", "lo-py8-madspin", "nlo-py8-madspin"])
def test_real_run(tmp_path, over):
    cfg = meg.load_config(None, [f'run.output_dir="{tmp_path}"', 'run.name="it"', "generation.events=100", *over])
    res = meg.run(cfg, echo="none")
    assert res.manifest["delphes"]["entries"] > 0
    assert res.cross_section_pb and res.cross_section_pb > 0
