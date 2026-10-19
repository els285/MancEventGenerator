"""Stand-ins for mg5_aMC, Delphes and Herwig, so the whole pipeline can be tested without the real
(multi-GB) toolchain. They mimic the real programs' awkward habits: MG5 exits 0 after an error,
Delphes prints '** ERROR' and exits 0, and each Delphes reader rejects the other's HepMC layout."""
from __future__ import annotations

import gzip
import os
import re
import sys
from pathlib import Path

RUN_CARD = """\
#*********************************************************************
  %(nevents)s = nevents ! Number of unweighted events requested
  0   = iseed   ! rnd seed (0=assigned automatically=default))
  nn23lo1 = pdlabel     ! PDF set
  230000    = lhaid     ! if pdlabel=lhapdf, this is the lhapdf number
  -1 = nevt_job ! split jobs
  0.01 = req_acc ! accuracy
  HERWIG6 = parton_shower
  .true. = reweight_scale ! reweight
  .true. = reweight_pdf   ! reweight
  20.0 = ptj ! minimum pt for the jets
"""
PARAM_CARD = """\
BLOCK MASS #
      6 1.730000e+02 # MT
     25 1.250000e+02 # MH
Block SMEFT #
      1 0.000000e+00 # cHW
      2 0.000000e+00 # cHB
Block ALT #
      1 0.000000e+00 # cHW
DECAY  6 1.350000e+00 # WT
"""


def _n_events_from_card(cards: Path) -> int:
    m = re.search(r"^\s*(\d+)\s*=\s*nevents", (cards / "run_card.dat").read_text(), re.MULTILINE)
    return int(m.group(1)) if m else 1


def mg5(argv: list[str]) -> None:
    if os.environ.get("FAKE_MG5_SLEEP"):             # a tool that ignores Ctrl+C, like a busy MG5
        import signal
        import subprocess
        import time
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        subprocess.Popen([sys.executable, "-c", "import signal,time;signal.signal(signal.SIGINT,signal.SIG_IGN);"
                          "signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(120)"])
        print("fake mg5: busy ...", flush=True)
        time.sleep(float(os.environ["FAKE_MG5_SLEEP"]))
        return
    lines = Path(argv[0]).read_text().splitlines()
    root = Path(os.environ["FAKE_MG5_ROOT"])
    lhapdf_off = False
    for i, line in enumerate(lines):
        line = line.strip()
        if line == "set lhapdf_py3 None":
            lhapdf_off = True
        elif line.startswith("import model "):
            target = line[len("import model "):]
            # MG5: models/<name>/restrict_<restriction>.dat, or <ufo dir>-<restriction> for a path
            name, _, restriction = target.rpartition("-") if target.startswith("/") else target.partition("-")
            if not name:
                name = target
            found = (root / "models" / name).is_dir() and (
                not restriction or (root / "models" / name / f"restrict_{restriction}.dat").is_file())
            if not found and not Path(name).is_dir() and not Path(target).is_dir():
                print(f"Command \"import model {target}\" interrupted with error:")
                print("InvalidCmd : Model not found")
                return                                            # exit status 0, like MG5
            print(f"fake mg5: imported {target}")
        elif line.startswith("output "):
            name = line.split()[1]
            d = Path(name)
            (d / "Cards").mkdir(parents=True)
            (d / "Source").mkdir()
            (d / "SubProcesses").mkdir()
            (d / "Cards" / "run_card.dat").write_text(RUN_CARD % {"nevents": 10000})
            (d / "Cards" / "param_card.dat").write_text(PARAM_CARD)
            (d / "Source" / "make_opts").write_text("" if lhapdf_off else "lhapdf=/x/bin/lhapdf-config\n")
            print("run_card missed argument foo. Takes default: bar")     # noise the console hides
        elif line.startswith("launch "):
            name = line.split()[1]
            d = Path(name)
            n = _n_events_from_card(d / "Cards")
            switches = [x for x in lines[i + 1:i + 5] if "=" in x and not x.startswith("set")]
            shower = next((x.split("=")[1] for x in switches if x.startswith("shower=")), None)
            madspin = "madspin=ON" in switches
            ev = d / "Events" / "run_01"
            ev.mkdir(parents=True)
            _write_lhe(ev / "unweighted_events.lhe.gz", n, "5.0890e+02 1.2e+00 5.0890e+02 1")
            out = ev
            if madspin:
                card = d / "Cards" / "madspin_card.dat"
                if not card.is_file() and not os.environ.get("FAKE_MADSPIN_NO_CARD"):
                    print("MadSpin card missing")
                    return
                out = d / "Events" / "run_01_decayed_1"
                out.mkdir()
                if not os.environ.get("FAKE_MADSPIN_NO_OUTPUT"):
                    # MadSpin folds the branching ratio into the cross-section
                    _write_lhe(out / "unweighted_events.lhe.gz", n, "1.2000e+02 1.0e+00 1.2000e+02 1")
                    (out / "card_used.dat").write_text(card.read_text())
                else:
                    out.rmdir()
            if shower and shower.upper() == "PYTHIA8" and out.is_dir():
                with gzip.open(out / "events_PYTHIA8_0.hepmc.gz", "wt") as f:
                    f.write(hepmc_text(n, v3=False))
            print(f"fake mg5: launched {name} with {n} events, shower={shower}, madspin={madspin}")


def _write_lhe(path: Path, n: int, xsec_line: str) -> None:
    body = ["<LesHouchesEvents>", "<init>", "2212 2212 6.5e3 6.5e3 0 0 230000 230000 -4 1", xsec_line, "</init>"]
    body += ["<event>", "x", "</event>"] * n + ["</LesHouchesEvents>"]
    with gzip.open(path, "wt") as f:
        f.write("\n".join(body) + "\n")


def hepmc_text(n: int, v3: bool) -> str:
    head = ("HepMC::Version 3.02.05\nHepMC::Asciiv3-START_EVENT_LISTING\n" if v3 else
            "HepMC::Version 2.06.09\nHepMC::IO_GenEvent-START_EVENT_LISTING\n")
    return head + "".join(f"E {i} 1 1\n" for i in range(n)) + "HepMC::IO_GenEvent-END_EVENT_LISTING\n"


def _count_events(path: Path) -> int:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as f:
        text = f.read()
    return text.count("<event>") + len(re.findall(r"^E \d+", text, re.MULTILINE))


def delphes(argv: list[str], flavour: str) -> None:
    out, inp = Path(argv[1]), Path(argv[2])
    if os.environ.get("FAKE_DELPHES_ERROR"):
        print("** ERROR: cannot parse input file")
        return                                                    # exit 0, no output
    if flavour != "LHEF":
        head = inp.read_text().splitlines()[1]
        if ("Asciiv3" in head) != (flavour == "HepMC3"):
            print(f"** ERROR: {flavour} cannot read this layout: {head}")
            out.write_bytes(b"")
            return
    import numpy as np
    import uproot
    n = _count_events(inp)
    jets = np.zeros(n, dtype="int32") + 2
    with uproot.recreate(out) as f:
        f["Delphes"] = {"Jet": jets, "Jet_size": jets}
    print(f"fake delphes {flavour}: {n} events")


def herwig(argv: list[str]) -> None:
    if argv[0] == "read":
        text = Path(argv[1]).read_text()
        lhe = re.search(r"^set LesHouchesReader:FileName (.*)$", text, re.MULTILINE).group(1)
        assert Path(lhe).is_file(), f"LHE not found: {lhe}"
        assert "read snippets/HepMC.in" in text
        name = re.search(r"^saverun (\S+) EventGenerator", text, re.MULTILINE).group(1)
        Path(f"{name}.run").write_text(text)
        print("fake herwig: read ok")
    elif argv[0] == "run":
        text = Path(argv[1]).read_text()
        lhe = Path(re.search(r"^set LesHouchesReader:FileName (.*)$", text, re.MULTILINE).group(1))
        n = _count_events(lhe)
        v3 = os.environ.get("FAKE_HEPMC_FORMAT") == "v3"
        Path(argv[1].replace(".run", ".hepmc")).write_text(hepmc_text(n, v3))
        print("fake herwig: run ok")
