# Models

Three models make up the ALPR pipeline, each kept in the runtime formats the
system can place it on.

| Model | Job | Runs on |
|---|---|---|
| Vehicle detector | Find vehicles in the full frame | Metis AIPU (in the cascade) |
| Plate detector | Find the plate inside each vehicle crop | Metis AIPU (in the cascade) |
| Plate OCR | Read the characters off a plate crop | Arc iGPU via OpenVINO |

## Formats

The same model can be deployed on different silicon depending on the active
backend mode, so each is kept in the format its runtime needs:

- **`weights/`** — the source models (ONNX), the common ancestor everything else
  is built from.
- **`cascade-build/`** — the AIPU-compiled cascade artifacts produced by the
  Voyager SDK, used in production. This is what the worker loads for detection.
- **`openvino/`** — the iGPU/CPU artifacts for OpenVINO. The OCR model always
  runs here; the detectors run here in the all-OpenVINO backend mode.

## Why OCR is split out

The two detectors compile cleanly to the AIPU and run there as a fused cascade.
The OCR model is a transformer-style network that does not compile to the AIPU,
so it always runs on the iGPU. That split is the reason the pipeline is a hybrid
(detection on the AIPU, OCR on the iGPU) rather than fully on the accelerator —
see [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

A lighter CNN-based OCR that *can* run on the AIPU exists as an alternative
cascade definition, but it is not used in production because it trades away plate
accuracy.
