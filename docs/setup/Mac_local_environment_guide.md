# FAIRification local environment on macOS

This environment is for the **core FAIRification analysis**: data audit and edge construction, publication-only NMF, linkage associations, policy-window sensitivity, institutional/country summaries, robustness, figures, and the publication-year-stratified local-alignment permutation test. It does not itself retrieve data from Dimensions, and it does not make the AI–mental-health scripts FAIR-ready without the planned field-specific adaptation.

The manual addition of Wilkinson et al. (2016) changes the source-cohort provenance, not this Python environment. The dependency pins, installation procedure, and preflight test below are unchanged.

## Recommended setup

Use **Miniforge** or another conda-forge distribution with Python 3.11. It works on both Apple Silicon and Intel Macs and avoids platform-specific compiled-package issues.

1. Install Apple command-line tools if they are not already installed:

   ```bash
   xcode-select --install
   ```

2. Install Miniforge for the Mac architecture from its official GitHub release, then open a new Terminal window.

3. Copy this `local_setup` directory to the FAIRification project folder. From that folder, create the environment:

   ```bash
   conda env create -f environment-core-macos.yml
   conda activate fairification-py311
   python verify_fairification_environment.py
   ```

4. The expected final line is `CORE ENVIRONMENT READY`.

The environment has exact version pins so all core work is run under one reproducible dependency set. Do not add packages opportunistically to the project environment without recording them in the relevant requirements or environment file.

## Optional exploratory packages

The archive’s mixed-mode community script requires `igraph` and `leidenalg`. These do not block the core FAIRification project. Install them only after the core pipeline is working:

```bash
conda activate fairification-py311
conda install -c conda-forge python-igraph=0.11.6 leidenalg=0.10.2
python verify_fairification_environment.py
```

## If conda is unavailable

A Python virtual environment can run the core package set:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-core.txt
python verify_fairification_environment.py
```

The conda route is preferred. Do not use the system Python for the project.

## What this check does and does not certify

The preflight script confirms that the core Python stack imports correctly. It does not prove that the FAIRification data files have the correct schema, that source curation is documented, that Dimensions retrieval is complete, that the source-to-Dimensions match is valid, or that a FAIR-specific adaptation of the archived code is correct. Those are separate protocol checks.

## Project folders

The companion `fairification_pipeline_template` uses these locations:

```text
fairification_pipeline/
├── data/
│   ├── 00_immutable_source/       # Received 162-record Scopus/WoS export: never edit
│   ├── 01_source_curation/        # Frozen 163-record cohort and its addition manifest
│   ├── 02_dimensions_raw/         # Query log and licensed raw/derived exports
│   ├── 03_matching/               # Candidate matches and match-decision audit
│   └── 04_final_linked/           # Frozen P, G, D inputs for core computations
├── provenance/                    # File hashes, manifests, deviations, package record
├── computations/
│   ├── src/                       # FAIR-adapted scripts, versioned
│   └── outputs/                   # Script-specific derived outputs
└── docs/                           # Protocol, data dictionary, codebook, paper materials
```

The 163-record file in `01_source_curation/` is the source denominator for the Dimensions matching and NMF. The 162-record file in `00_immutable_source/` is retained solely as the untouched received export. Keep the preserved AI–mental-health archive read-only and outside this FAIRification working tree. The FAIRification scripts should record their lineage from the archive but use FAIR-specific paths, inputs, labels, and codebooks.
