---
artifact_id: ART-MARKETOS-VENDOR-COMPUTE-ADDENDUM-001
version: "0.24.2-CANDIDATE"
authority: DIRECT_OWNER_REQUIREMENT
status: PENDING_C0_1_RECONCILIATION
phases: [C0.1, C5, C6, 08A, 08B, 10B]
live_trading_state: HARD_LOCKED
profitability: UNPROVEN
---

# MARKET-OS — Vendor Compute, Mathematical Acceleration and Quant Finance Addendum

## 1. Verdict

The v0.23 vendor matrix is a valid first-pass inventory, not an exhaustive final specification. C0.1 must merge this addendum before C1. C5 and C6 must produce locked, benchmarkable Claude Code contracts for every relevant vendor and vendor-neutral compute path.

No library is adopted because of branding, documentation, or a vendor benchmark.

## 2. NVIDIA candidate stack

### CPU / Grace and compatible Arm platforms
- NVIDIA Performance Libraries (NVPL): BLAS, LAPACK, FFT, RAND, Sparse, ScaLAPACK, Tensor.
- NVIDIA HPC SDK: NVC++, NVFORTRAN, OpenACC, OpenMP, C++ parallel algorithms.
- NVPL is admitted only on an explicitly supported CPU/platform; DGX Spark/GB10 support must be probed rather than assumed.

### GPU mathematical core
- CUDA Toolkit.
- cuBLAS and cuBLASLt.
- cuSOLVER and cuDSS.
- cuSPARSE and cuSPARSELt.
- cuFFT, cuRAND, cuTENSOR, CUTLASS and CCCL.
- MathDx: cuBLASDx, cuFFTDx, cuSolverDx, cuRANDDx, nvCOMPDx.
- AmgX where iterative sparse solvers are relevant.
- nvCOMP and GPUDirect Storage for data movement/compression experiments.

### Data science and distributed compute
- RAPIDS: cuDF, cuML, cuGraph, cuVS, RAFT, RMM, cuOpt.
- Dask-CUDA and UCX-Py.
- cuPyNumeric + Legate for NumPy-style multi-node/multi-rank workloads.
- CuPy and NVIDIA numba-cuda as Python kernel candidates.
- NCCL, NVSHMEM, UCX and MPI.

### AI/model execution
- TensorRT-LLM, Triton Inference Server, vLLM/SGLang where supported.
- These accelerate the Model Council but never replace deterministic numerical tools.

### Diagnostics and qualification
- Nsight Systems, Nsight Compute, Compute Sanitizer, CUDA-GDB.
- DCGM, NVML, NCCL-tests, nvbandwidth.
- GPU Operator only after driver/platform compatibility is proven.

## 3. AMD candidate stack

### CPU / Zen
- AOCL 5.3 candidate family: BLAS, LAPACK, ScaLAPACK, Sparse, RNG, SecureRNG, FFTW, FFTZ, LibM, LibMem, Data Analytics, DLP, Compression, Cryptography and Utils.
- AOCC and AMD uProf as compiler/profiler candidates.
- AOCL-enabled NumPy, SciPy, PyTorch and NumExpr wheels must be compared against standard wheels.

### GPU / ROCm
- HIP, HIPIFY and ROCm LLVM.
- rocBLAS, hipBLAS, hipBLASLt, rocSOLVER and hipSOLVER.
- rocSPARSE, hipSPARSE, hipSPARSELt, rocALUTION, rocFFT/hipFFT and rocRAND/hipRAND.
- rocPRIM, rocThrust, hipCUB, Composable Kernel, rocWMMA and hipTensor.
- MIOpen, hipDNN, RCCL, rocSHMEM and hipFile.

### ROCm Data Science
- hipDF, hipMM, hipRAFT and hipVS.
- hipGraph only after current support and hardware compatibility are verified.
- Compare against CPU Polars/DuckDB and NVIDIA RAPIDS on identical semantics.

### AMD Finance
- ROCm Finance: ROCm-enabled XGBoost, LightGBM and ThunderGBM.
- Treat hardware support as narrow and version-specific; current official support is primarily AMD Instinct, not a blanket promise for Radeon/consumer GPUs.

### FPGA / Alveo
- Vitis, Vitis HLS, XRT and Vitis Quantitative Finance.
- Vitis Math, Statistics and Linear Algebra libraries.
- Candidate workloads: Monte Carlo option pricing, Heston/Black-Scholes, risk, fixed pipelines, feed parsing and deterministic controls.
- Vendor speedup charts are hypotheses until reproduced against MARKET-OS baselines.

### Diagnostics
- ROCm Compute Profiler, ROCm Systems Profiler, ROCprofiler SDK, AMD SMI, RDC/RVS, rocminfo, TransferBench and RCCL tests.

## 4. Intel candidate stack

- oneAPI DPC++/C++ and SYCL; Level Zero.
- oneMKL: BLAS/LAPACK, Sparse BLAS, FFT/DFT, RNG and Vector Math.
- oneDAL: statistics, covariance, regression, trees, clustering and distributed/streaming analytics.
- oneDNN, oneTBB, oneDPL, oneCCL, Intel MPI, Intel IPP and OpenVINO.
- oneMKL Black-Scholes and Monte Carlo reference samples.
- oneMKL host-vs-device RNG paths and SYCL multi-GPU Monte Carlo option pricing.
- Intel Extension for Scikit-learn / oneDAL Python path; dpctl/dpnp after support verification.
- VTune, Advisor, PCM/RAPL and XPU Manager where applicable.
- Intel Inspector is EOL and must not be planned as a new dependency.
- Quartus Prime, OPAE/OFS and current oneAPI FPGA tooling remain conditional.

## 5. Vendor-neutral numerical and quantitative layer

Vendor libraries are acceleration backends, not financial knowledge. The portable authority layer includes NumPy, SciPy, statsmodels, arch, Numba, JAX, PyTorch, BLAS/LAPACK/OpenBLAS/BLIS, FFTW, SuiteSparse, PETSc, SLEPc, MAGMA, QuantLib, CVXPY, OSQP, HiGHS, Ipopt, NLopt, Pyomo, CasADi, PyMC, Stan, NumPyro, nutpie, BlackJAX, Riskfolio-Lib, skfolio, PyPortfolioOpt, DoWhy, EconML, CausalML, Polars, Arrow, DuckDB, Dask, Ray, MPI, UCX, XGBoost, LightGBM, CatBoost, Qlib, vectorbt, NautilusTrader, LEAN, hftbacktest, ABIDES and JAX-LOB.

Each financial method must have a vendor-neutral reference before acceleration.

## 6. Workload-to-backend tournament

| Workload | Golden reference | Accelerated candidates |
|---|---|---|
| exact cash/accounting | integer/decimal CPU | none unless semantics remain exact |
| covariance/SVD/eigen | CPU FP64 LAPACK | cuSOLVER, rocSOLVER, oneMKL |
| Monte Carlo/QMC | deterministic CPU oracle | cuRANDDx/CUDA, rocRAND/HIP, oneMKL SYCL, Vitis QF |
| VaR/Expected Shortfall | CPU reference | GPU/vectorized/FPGA candidates |
| bootstrap/walk-forward/PBO | CPU process pool | GPU only when algorithmic structure benefits |
| sparse exposure graph | SuiteSparse/PETSc | cuSPARSE/cuGraph, rocSPARSE/hipGraph, oneMKL Sparse |
| factor ETL/PIT joins | Polars/DuckDB reference | RAPIDS, ROCm-DS, oneDAL paths |
| tabular ML | CPU XGBoost/LightGBM | RAPIDS cuML, ROCm Finance, oneDAL |
| time-series/deep models | CPU baseline | CUDA/ROCm/Intel XPU frameworks |
| L2/L3 replay | CPU event-driven oracle | GPU/FPGA only after semantic equivalence |
| option pricing/Greeks | QuantLib/CPU FP64 | CUDA, ROCm, oneMKL, Vitis QF |
| distributed simulation | single-node deterministic | NCCL/RCCL/oneCCL/MPI/UCX |

## 7. Mandatory gates

1. Probe the actual node, driver, firmware, ISA, device and supported precision.
2. Lock exact versions, packages, hashes, images and licenses.
3. Reproduce a CPU Golden Oracle.
4. Compare absolute/relative/ULP error, tail quantiles and changed decisions.
5. Test determinism across seeds, process counts, devices and restarts.
6. Measure throughput, latency, memory, storage, network, energy and TCO.
7. Run cold/warm, contention, spill, corruption, thermal and soak tests.
8. Record unsupported hardware as NOT_RUN, never as rejected or supported.
9. Quarantine a backend per workload when it diverges.
10. Maintain a tested CPU fallback.
11. Never infer support from vendor family names.
12. No vendor benchmark closes a MARKET-OS gate.

## 8. Required C0.1/C5/C6 changes

- Add this document to the requirement crosswalk and Memory Vault.
- Add AMD Finance and Vitis Quantitative Finance explicitly.
- Add NVIDIA MathDx, cuPyNumeric/Legate and the complete RAPIDS stack.
- Add the full AOCL and ROCm-DS stacks.
- Add Intel finance-specific oneMKL/SYCL experiments.
- Mark Intel Inspector EOL.
- Produce a machine-readable vendor capability registry.
- Produce one Claude Code execution contract for vendor probes and one for workload tournaments.
- Require the Node Pack to report PRESENT, DRIVER_READY, SDK_READY, DIAGNOSTIC_PASS and BENCHMARKED_FOR_ROLE separately.
- No global winner: selection is workload × node × precision × cost × reliability.

## 9. Source set to pin during C0.1

Official documentation families: NVIDIA CUDA Toolkit, CUDA math libraries, MathDx, RAPIDS, NVPL, HPC SDK, NCCL, DCGM and Nsight; AMD AOCL, ROCm Core SDK, ROCm Data Science, ROCm Finance, Vitis Quantitative Finance, AMD SMI/RVS and ROCprofiler; Intel oneAPI, oneMKL, oneDAL, oneDNN, oneTBB, oneCCL, VTune, Advisor, IPP, OpenVINO and current FPGA tools.

All exact URLs, release versions and compatibility matrices must be refreshed and locked on the execution date.
