# Prospective IQCC hardware protocol — NOT RUN

Gate 1: Written authorization, backend/qubit identity, approved pulse/readout elements, execution windows, operational constraints and private credentials storage.
Gate 2: Vendor-configured QUA SDK installed; syntax/serialization check distinguished from cloud simulator and real device jobs.
Gate 3: Verify timing tick, pulse width, phase convention, safe power, readout and reset, T1, Ramsey T2*, Hahn T2, pulse calibration and leakage.
Gate 4: Measure spectator phase accumulation under neighbor readout across relative timing, drive-only and measurement-on controls, separate deterministic ac-Stark shift from stochastic dephasing and other errors.
Gate 5: Pre-register equal-n/T, virtual-Z and standard DD controls; randomize/interleave arms to protect against drift, use independently repeated blocks and coherent uncertainty estimates; log readout correction limitations.
Gate 6: Report actual runtime including queue/compile/calibration overhead. At 300us repetition 280k shots represent 84s nominal repetitions only.
Gate 7: Retain anonymized run IDs, times, calibration versions and raw outcomes in controlled storage. Publish only with laboratory approval.

No executable cloud job should be submitted by an autonomous agent without explicit human permission. Never commit secrets or institution-restricted device configs.
