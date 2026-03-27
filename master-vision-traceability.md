# Strict Traceability Matrix

## Scope
This matrix maps the master vision-related clauses in claudeprd.md to exact coverage points in visionprd.md and task.md.

Legend:
- Covered: Requirement is explicitly represented.
- Covered (Normalized): Requirement is represented with equivalent wording/operationalization.
- Gap: Missing or insufficient coverage.

## Clause-by-Clause Mapping

| ID | Master Clause (Source) | Canonical Requirement | visionprd.md Coverage | task.md Coverage | Status | Notes |
|---|---|---|---|---|---|---|
| M-VIS-001 | claudeprd.md:146, claudeprd.md:1098-1100 | Vision subsystem runs on Raspberry Pi 5 with Ubuntu 24.04 | visionprd.md:7-9, visionprd.md:62, visionprd.md:68 | task.md:11, task.md:15 | Covered | Platform and OS now fully aligned. |
| M-VIS-002 | claudeprd.md:149-151, claudeprd.md:1106 | Pi HQ Camera (IMX477) is the vision source | visionprd.md:8, visionprd.md:134 | task.md:12, task.md:117 | Covered | Camera assumptions aligned. |
| M-VIS-003 | claudeprd.md:197, claudeprd.md:219, claudeprd.md:1166 | Capture aligns with 10-second measurement cycle | visionprd.md:78, visionprd.md:135 | task.md:126 | Covered | Cadence explicit in PRD and chunk prompts. |
| M-VIS-004 | claudeprd.md:219 | Capture artifacts are saved as image files (JPEG in master flow) | visionprd.md:141 | task.md:132 | Covered | Explicit JPEG persistence added. |
| M-VIS-005 | claudeprd.md:223-226, claudeprd.md:1048-1063 | Parallel specialist execution (sensor + vision) feeding fusion | visionprd.md:118-126 | task.md:136-155 | Covered (Normalized) | Execution contract and specialist orchestration reflected. |
| M-VIS-006 | claudeprd.md:185, claudeprd.md:834-835, claudeprd.md:914-915 | Vision contributes severity (0-10) and confidence (0-1) | visionprd.md:114-115, visionprd.md:168-169 | task.md:123, task.md:138 | Covered | Scoring requirements explicit. |
| M-VIS-007 | claudeprd.md:188, claudeprd.md:1064, claudeprd.md:2562 | Outputs feed dashboard/runtime UI | visionprd.md:51-54, visionprd.md:335-342 | task.md:180-184 | Covered (Normalized) | Dashboard behavior placed in demo and UX chunks. |
| M-VIS-008 | claudeprd.md:892-899, claudeprd.md:910-929 | Vision features include rust coverage, pitting, color, morphology | visionprd.md:159-164 | task.md:122 | Covered | Feature taxonomy matches master specialist scope. |
| M-VIS-009 | claudeprd.md:815, claudeprd.md:831-838, claudeprd.md:900 | Vision specialist produces schema-valid JSON | visionprd.md:176-181, visionprd.md:185-216 | task.md:140, task.md:147, task.md:151 | Covered | JSON contract explicit in both requirements and execution plan. |
| M-VIS-010 | claudeprd.md:957, claudeprd.md:1025-1030, claudeprd.md:1568 | Default fusion policy uses 60/40 weighting | visionprd.md:122, visionprd.md:356 | task.md:162 | Covered | Weighting policy aligned exactly. |
| M-VIS-011 | claudeprd.md:1011-1014 | Conflict threshold is severity delta > 3 | visionprd.md:123, visionprd.md:355 | task.md:161 | Covered | Threshold aligned exactly. |
| M-VIS-012 | claudeprd.md:1053-1061 | Orchestrator checks conflicts and resolves before fusion output | visionprd.md:118-126, visionprd.md:351-358 | task.md:157-174 | Covered (Normalized) | Policy flow represented in interface and fusion chunk. |
| M-VIS-013 | claudeprd.md:812, claudeprd.md:882, claudeprd.md:937, claudeprd.md:1074-1085 | Gemini 3 Flash baseline for specialist/fusion orchestration | visionprd.md:126 | task.md:141 | Covered | Model baseline explicit in both docs. |
| M-VIS-014 | claudeprd.md:1113-1115, claudeprd.md:1368, claudeprd.md:2006-2015 | Camera runtime stack uses picamera2/libcamera ecosystem | visionprd.md:69, visionprd.md:473 | task.md:117-126 | Covered (Normalized) | PRD includes command/toolchain fallback semantics. |
| M-VIS-015 | claudeprd.md:1943-2015 | Deployment/setup assumptions are Ubuntu-based, camera bring-up validated | visionprd.md:68-70, visionprd.md:252-267 | task.md:15, task.md:44-48 | Covered (Normalized) | Setup and calibration workflow aligned. |
| M-VIS-016 | claudeprd.md:2524-2536, claudeprd.md:2558-2577 | Demo phase includes baseline behavior and visual correlation | visionprd.md:278-293 | task.md:218-223 | Covered | Phase A and launch script alignment present. |
| M-VIS-017 | claudeprd.md:2614-2634 | Accelerated corrosion phase increases rust/severity | visionprd.md:294-305 | task.md:221, task.md:233 | Covered | Trend expectations captured in PRD and C09 outcomes. |
| M-VIS-018 | claudeprd.md:2640-2652 | Fresh-sample swap should show severity reset/drop | visionprd.md:330-342 | task.md:233 | Covered | Contrast expectation explicitly retained. |
| M-VIS-019 | claudeprd.md:2667, claudeprd.md:2703-2710 | End-to-end analysis should be nominally under 10 seconds | visionprd.md:223, visionprd.md:227 | task.md:30, task.md:238-240 | Covered (Normalized) | Nominal and degraded latency bounds explicit. |
| M-VIS-020 | claudeprd.md:2667, claudeprd.md:2524-2531 | Demo runtime reliability: no unrecovered failures in extended run | visionprd.md:231, visionprd.md:481 | task.md:29, task.md:133 | Covered | 1-hour stability and run gating maintained. |
| M-VIS-021 | claudeprd.md:1471-1474, claudeprd.md:1572, claudeprd.md:3102+ | Error/degraded handling with fallback and continued operation | visionprd.md:147, visionprd.md:178-180, visionprd.md:374-380 | task.md:25, task.md:124, task.md:152, task.md:202 | Covered | Degraded mode and fallback behavior enforced in plan and PRD. |
| M-VIS-022 | claudeprd.md:894, claudeprd.md:1525-1531 | Quality controls for frame validity are required | visionprd.md:144-148, visionprd.md:266 | task.md:121, task.md:131 | Covered | Blur/exposure gating + retries retained. |
| M-VIS-023 | claudeprd.md:831-838, claudeprd.md:1405-1411 | Structured fields for explainability and confidence drivers | visionprd.md:170-172, visionprd.md:203-211 | task.md:32, task.md:144 | Covered | Human-readable and machine-readable explainability preserved. |
| M-VIS-024 | claudeprd.md:1523-1529, claudeprd.md:2006-2015 | Calibration and controlled capture conditions are mandatory | visionprd.md:252-267 | task.md:120-121 | Covered | Calibration workflow and locked settings represented. |
| M-VIS-025 | claudeprd.md:224, claudeprd.md:2575-2580 | Visual evidence should correlate with electrochemical trends | visionprd.md:344-358 | task.md:172, task.md:233 | Covered | Correlation warning logic and trend outcomes aligned. |
| M-VIS-026 | claudeprd.md:197-226, claudeprd.md:1523-1531 | Vision pipeline execution block requires capture, quality, analysis, output | visionprd.md:268-274, visionprd.md:412-420 | task.md:116-134 | Covered | Chunk C04 directly maps to master flow. |
| M-VIS-027 | claudeprd.md:831-838, claudeprd.md:1568-1572 | Specialist service contracts require deterministic schema + timeout behavior | visionprd.md:176-181, visionprd.md:233 | task.md:136-155 | Covered | C05 aligns to schema validation and timeout fallback. |
| M-VIS-028 | claudeprd.md:1011-1030, claudeprd.md:1568-1569 | Fusion policy requires conflict handling + explicit weighting | visionprd.md:118-126, visionprd.md:355-358 | task.md:157-174 | Covered | C06 exactly aligned to master thresholds/weights. |
| M-VIS-029 | claudeprd.md:2524-2670 | Demo runtime requires phase visibility, operator clarity, and final sign-off flow | visionprd.md:278-342, visionprd.md:433-436 | task.md:177-236 | Covered | C07-C09 preserve phase orchestration and go/no-go logic. |
| M-VIS-030 | claudeprd.md:2703-2710, claudeprd.md:2755 | Vision specialist latency and role in multimodal stack must remain practical | visionprd.md:223-227, visionprd.md:458-461 | task.md:30, task.md:238-240 | Covered (Normalized) | Performance bars kept realistic and master-consistent. |

## Gap Summary
- Total mapped clauses: 30
- Covered: 24
- Covered (Normalized): 6
- Gap: 0

## Strict Alignment Verdict
The current vision and execution documents are strictly aligned to the vision-related master clauses in claudeprd.md, with no unresolved traceability gaps.

## Files Assessed
- claudeprd.md
- visionprd.md
- task.md
