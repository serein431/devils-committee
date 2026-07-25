# Avatar Debate Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-screen four-head debate stage and move the current research interface below it.

**Architecture:** Keep the single-file frontend. Add a stage state controller beside the existing SSE renderer; claim events feed both the stage queue and the existing evidence cards. FastAPI continues to serve compressed WebP files from `/assets`.

**Tech Stack:** HTML, CSS, browser JavaScript, FastAPI StaticFiles, jsdom, Playwright CLI.

---

### Task 1: Lock the stage behavior with tests

**Files:**
- Modify: `tests/frontend.test.mjs`
- Test: `tests/test_server.py`

- [ ] Add assertions for four `.face-player` elements, `#faceStage` before `#detailsStart`, one active speaker after a claim, and a speaking WebP source.
- [ ] Remove assertions tied to avatars inside evidence cards.
- [ ] Run `./scripts/test_frontend.sh` and confirm failure because the stage does not exist.

### Task 2: Build the first-screen stage

**Files:**
- Modify: `web/index.html`

- [ ] Add the four-head stage, command area, scroll hint, and details wrapper.
- [ ] Add `activateStageSpeaker()`, a claim queue, and a two-second turn timer.
- [ ] Restore compact evidence cards without embedded avatars.
- [ ] Rename open status text from `仍在吵` to `未达成一致`.
- [ ] Run `./scripts/test_frontend.sh` and confirm all checks pass.

### Task 3: Verify assets and real layout

**Files:**
- Verify: `web/assets/avatars/*.webp`
- Create: `output/playwright/avatar-stage-desktop.png`
- Create: `output/playwright/avatar-stage-mobile.png`

- [ ] Run `.venv/bin/python -m pytest tests/test_server.py -q`.
- [ ] Start the local service and verify a real research flow in Chromium.
- [ ] Capture desktop and mobile screenshots and confirm no text overflow or console errors.
