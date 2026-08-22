# AITier ranking scraper

This project uses only the Python standard library. It collects all 11 configured AITier ranking pages: `general`, `coding`, `math`, `science`, `reasoning`, `agents`, `multimodal`, `image-gen`, `video-gen`, `image-to-video`, and `audio`.

All collected tables are stored as JSON:

- `data/latest.json`: the newest complete run, including ranking rows and model metadata;
- `data/<domain>.json`: the newest result for each individual domain;
- `data/raw/*.html`: optional raw pages when `--keep-raw` is enabled.

Each ranking row keeps the original rank, score, metrics, source, update time, and a joined `model` object. The model object contains all fields exposed by the page, such as provider, pricing, capabilities, modalities, context window, parameter count, and source links.

## Run once

```powershell
python aitier_scraper.py
```

Run selected domains only:

```powershell
python aitier_scraper.py --domain general coding
```

Run every six hours:

```powershell
python aitier_scraper.py --interval-minutes 360
```

The script also works with Windows Task Scheduler. Schedule `python aitier_scraper.py` (or `run_scraper.bat`) for a one-shot run; this is usually easier to monitor than a permanently running process. Each run replaces the latest JSON files and does not keep historical snapshots.

## Miniconda environment

```powershell
conda create -n aitier-scraper python=3.11 -y
conda activate aitier-scraper
python aitier_scraper.py
```

No `pip install` step is required.

## Build an exe

Install PyInstaller once in the isolated environment:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --onefile --name aitier-scraper aitier_scraper.py
```

Place `dist\\aitier-scraper.exe` and `config.json` in the same directory. The exe writes JSON files to its `data` subdirectory. Use `--config` and `--output-dir` for custom locations.

If the site changes its frontend, run with `--keep-raw` and inspect the saved HTML before updating the parser.
