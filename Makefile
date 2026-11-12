# toki1-english: build the English PS1 disc from your own disc.
#
# Needs a toki1-decomp checkout next to this one (or TOKI_DECOMP_DIR) that has
# your disc, its extracted files, the IDO 5.2 compiler and the verified clean
# builds (README.md, "Build the English disc").  Everything this Makefile
# builds lands under build/ here; nothing is written into toki1-decomp.

PYTHON ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
PROFILE ?= config/english.json
DECOMP_DIR := $(shell $(PYTHON) tools/repo_paths.py 2>/dev/null | sed -n 's/^DECOMP=//p')

.PHONY: help patch patch-debug check-prereqs gates fast-check test test-disc-free ci clean \
        lint hydrate fold hook

help:
	@echo "make lint           check the sheets (no disc): format, rows, Japanese, tokens, fit"
	@echo "make hydrate        work/sheets/: the sheets with the Japanese from your disc"
	@echo "make fold           copy English/Status/Notes/Speaker from work/sheets/ back"
	@echo "make hook           run make lint before every commit (git pre-commit hook)"
	@echo "make check-prereqs  what the build needs from toki1-decomp, and whether it is there"
	@echo "make patch          build the English disc + PPF (PROFILE=$(PROFILE))"
	@echo "make patch-debug    the debug profile (config/english-debug.json)"
	@echo "make gates          re-check the last build (text gates, hooks, PPF, disc self-test)"
	@echo "make fast-check     symbol sync + unit test + every profile without the ISO"
	@echo "make test           every unit test (some need the disc, via toki1-decomp)"
	@echo "make test-disc-free the tests CI runs (no disc)"
	@echo "make ci             the CI jobs in a clean checkout of HEAD"
	@echo "toki1-decomp: $(or $(DECOMP_DIR),NOT FOUND (check it out next to this repository or set TOKI_DECOMP_DIR))"

check-prereqs:
	@test -n "$(DECOMP_DIR)" || { echo "toki1-decomp not found: check it out next to this repository or set TOKI_DECOMP_DIR"; exit 1; }
	@ok=1; for f in disks/SLPS_000.65 \
	    "disks/Tokimeki Memorial - Forever with You (Japan) (Rev 1) (Track 1).bin" \
	    assets/extracted_iso/CDROM assets/overlays \
	    tools/ido-static-recomp/build/5.2/out/cc \
	    build/SLPS_000.65.clean build/overlay; do \
	  if [ -e "$(DECOMP_DIR)/$$f" ]; then echo "ok       $$f"; else echo "MISSING  $$f"; ok=0; fi; done; \
	  [ $$ok = 1 ] || { echo "in $(DECOMP_DIR): make validate-disc extract-assets setup-ido52 check-clean-main check-exn-all"; exit 1; }

patch: check-prereqs
	$(PYTHON) tools/build_patched.py $(PROFILE)

patch-debug: check-prereqs
	$(PYTHON) tools/build_patched.py config/english-debug.json

# the independent read-backs of the last `make patch` (the build runs its
# own gates too; these re-check its outputs from the bytes)
gates:
	$(PYTHON) tools/text_gates.py
	$(PYTHON) tools/verify_hooks.py --profile config/english.json
	$(PYTHON) tools/verify_ppf.py build/patch/english.ppf
	$(PYTHON) tools/verify_disc.py --self-test

# the fast gate after a change to patch/, config/ or the tools:
# symbol sync, unit test, the debug/drawlog/release profiles without the ISO
fast-check: check-prereqs
	$(PYTHON) tools/fast_check.py

# the disc-free tests: what CI runs
test-disc-free:
	$(PYTHON) tools/test_sync_patch_symbols.py
	$(PYTHON) tools/test_audit_drawn_text.py
	$(PYTHON) tools/test_check_translation.py
	$(PYTHON) tools/test_lint_sheets.py
	$(PYTHON) tools/reviewer/test_review_model.py
	$(PYTHON) tools/sync_patch_symbols.py --check

# everything, including the tests that read the extracted disc in toki1-decomp
test: test-disc-free
	$(PYTHON) tools/test_art_frames.py
	$(PYTHON) tools/test_mag_genre_tags.py
	$(PYTHON) tools/test_name_ent_labels.py
	$(PYTHON) tools/test_name_plates.py
	$(PYTHON) tools/test_option_nbn.py
	$(PYTHON) tools/test_tacotex_operations.py
	$(PYTHON) tools/test_build_jev_qa_kit.py
	$(PYTHON) tools/reviewer/test_scene_assets.py

ci:
	PYTHON=$(PYTHON) tools/ci/run_ci_locally.sh

# The sheets, without the disc (and without toki1-decomp): format, stable
# rows, no Japanese script, tokens, byte limit, fit.  LINT_ARGS: e.g.
# --base origin/main (the rows a pull request must keep), --allow-rows.
lint:
	$(PYTHON) tools/lint_sheets.py $(LINT_ARGS)

# work/sheets/: every sheet with a Japanese column read from your disc
# (toki1-decomp, after its `make setup`); ignored by git, never committed
hydrate:
	$(PYTHON) tools/hydrate.py hydrate

# English, Status, Notes and Speaker from work/sheets/ back into sheets/
fold:
	$(PYTHON) tools/hydrate.py fold

# a git pre-commit hook that runs the lint (and refuses a staged work/ file)
hook:
	@printf '#!/bin/sh\nexec make -s lint LINT_ARGS="--staged -q"\n' > .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "installed .git/hooks/pre-commit (make lint before every commit)"

clean:
	rm -rf build/patch
