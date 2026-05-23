#!/usr/bin/env bash
# demo_final.sh
# End-to-end master demo runner for Context Compiler.
# Designed for the Cerebral Valley Google I/O Hackathon.

set -e

# ANSI escape codes for beautiful styling
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BOLD}${BLUE}========================================================================${NC}"
echo -e "${BOLD}${BLUE}   Context Compiler — Live Master Demo Script${NC}"
echo -e "${BOLD}${BLUE}   Cerebral Valley Google I/O Hackathon 2026${NC}"
echo -e "${BOLD}${BLUE}========================================================================${NC}"

# STEP 1: Run Smoke Test
echo -e "\n${BOLD}${GREEN}[STEP 1] Running Orchestrator Environment Smoke Test...${NC}"
python3 main.py --smoke-test

# STEP 2: Clear any stale live demo directories
echo -e "\n${BOLD}${GREEN}[STEP 2] Preparing Safe Sandbox Directory (/tmp/context_compiler_live_demo_repo)...${NC}"
rm -rf /tmp/context_compiler_live_demo_repo || true

# STEP 3: Run full live demo inside master orchestrator
echo -e "\n${BOLD}${GREEN}[STEP 3] Running Master Orchestration Live Demo (with patch and sandbox test validation)...${NC}"
python3 main.py \
  --repo ./demo_repo \
  --task "Add request validation to the checkout endpoint before payment processing" \
  --target-ratio 0.15 \
  --judge-demo

# STEP 4: Inspect generated master dashboard and files
echo -e "\n${BOLD}${GREEN}[STEP 4] Verifying Final Output Artifact Presence & Sizes...${NC}"
ls -lh \
  demo.html \
  final_diff.txt \
  codebase_manifest.txt \
  semantic_cards.jsonl \
  edit_plan.md \
  selected_context.md \
  proposed_patch.diff \
  patch_report.md \
  validation_report.md

echo -e "\n${BOLD}${BLUE}========================================================================${NC}"
echo -e "${BOLD}${GREEN}   ✓ LIVE DEMO RUN COMPLETED SUCCESSFULLY!${NC}"
echo -e "${BOLD}${YELLOW}   Judges Dashboard: $(pwd)/demo.html${NC}"
echo -e "${BOLD}${YELLOW}   Applied Live Diff: $(pwd)/final_diff.txt${NC}"
echo -e "${BOLD}${BLUE}========================================================================${NC}"
