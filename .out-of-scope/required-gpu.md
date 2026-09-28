# A GPU is never required

**Decision:** every feature works on a CPU-only machine, including CI runners and older laptops. GPU
acceleration is used when present (Chrome's GPU rasterisation, optional hardware encoders, the RIFE
interpolation extra, Apple Silicon engines) but always has a CPU fallback.

**Why**
- showtime targets macOS (Apple Silicon and Intel), Windows 10/11 and Linux. Requiring CUDA, Metal or a
  particular driver would exclude many of them and make results depend on hardware.
- Renders must be reproducible across machines; the CPU paths define the reference result.

**Consequences:** models are chosen for CPU speed (ONNX, CTranslate2, quantised weights); features that are
only practical with a GPU are optional extras and say so, with a time estimate, before they run.
