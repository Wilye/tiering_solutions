#!/bin/bash

RESULTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="/users/shelby/tiering_solutions/src"
TIMEOUT=1800  # 30 minutes

# --- Workload binaries and args ---
XSBENCH_BIN="/users/shelby/workloads/XSBench/openmp-threading/XSBench"
XSBENCH_ARGS="-g 130000 -p 20000000 -t 20"

GAPBS_BC_BIN="/users/shelby/workloads/gapbs/bc"
GAPBS_BC_ARGS="-n 16 -f /users/shelby/workloads/gapbs/benchmark/graphs/twitter.sg"

GAPBS_PR_BIN="/users/shelby/workloads/gapbs/pr"
GAPBS_PR_ARGS="-n 16 -f /users/shelby/workloads/gapbs/benchmark/graphs/twitter.sg"

SILO_BIN="/users/shelby/tiering_solutions/apps/silo/silo/out-perf.masstree/benchmarks/dbtest"
SILO_ARGS="--verbose --bench tpcc --num-threads 20 --scale-factor 100 --ops-per-worker 8000000 --numa-memory 85743345664"

LIBLINEAR_BIN="/users/shelby/workloads/liblinear-2.47/train"
LIBLINEAR_ARGS="-s 6 -m 20 /users/shelby/workloads/liblinear-2.47/kddb"

MIN_SIZE=2097152                # 2 MiB (minimum allocation)
MAX_DRAM=35934699520            # 33.47 GiB (dax0.0 capacity)
MAX_NVM=84555071488             # 78.73 GiB (dax1.0 capacity)

run_workload() {
    local name=$1
    local bin=$2
    local args=$3
    local dramsize=$4
    local nvmsize=$5
    local label=$6
    local extra_env=$7

    local outfile="${RESULTS_DIR}/${name}_${label}.txt"
    echo "=== Running ${name} ${label} ==="
    echo "  DRAMSIZE=${dramsize} NVMSIZE=${nvmsize}"
    echo "  Output: ${outfile}"

    { time timeout ${TIMEOUT} sudo numactl -N0 env DRAMSIZE=${dramsize} NVMSIZE=${nvmsize} ${extra_env} \
        LD_PRELOAD=${SRC_DIR}/libarms.so \
        ${bin} ${args} ; } > "${outfile}" 2>&1

    local exit_code=$?
    if [ ${exit_code} -eq 124 ]; then
        echo "  TIMED OUT after ${TIMEOUT}s"
    else
        echo "  Done (exit code: ${exit_code})"
    fi
}

# --- Build default ---
echo "Building default..."
cd ${SRC_DIR}
make clean && make
echo ""

# All DRAM: DRAMSIZE = dax0.0 capacity, NVMSIZE = original from run scripts (for overflow)
# All NVM:  DRAMSIZE = MIN_SIZE (or enough for overflow), NVMSIZE = at least RSS

# # --- XSBench (RSS: 64.97 GiB) ---
# # all_dram: 33.47 GiB DRAM + 57.75 GiB NVM overflow
# # all_nvm: 2 MiB DRAM + 64.97 GiB NVM (need full RSS in NVM)
# run_workload "xsbench" "${XSBENCH_BIN}" "${XSBENCH_ARGS}" \
#     ${MAX_DRAM} 62008590336 "all_dram"
# run_workload "xsbench" "${XSBENCH_BIN}" "${XSBENCH_ARGS}" \
#     ${MIN_SIZE} 69759664128 "all_nvm"

# # --- GapBS BC Twitter (RSS: 13.08 GiB) ---
# # all_dram: 33.47 GiB DRAM (RSS fits) + 64 GiB NVM
# # all_nvm: 2 MiB DRAM + 64 GiB NVM (RSS fits)
# run_workload "gapbs_bc_twitter" "${GAPBS_BC_BIN}" "${GAPBS_BC_ARGS}" \
#     ${MAX_DRAM} 68719476736 "all_dram" \
#     "OMP_NUM_THREADS=20 MIN_INTERPOSE_MEM_SIZE=134217728"
# run_workload "gapbs_bc_twitter" "${GAPBS_BC_BIN}" "${GAPBS_BC_ARGS}" \
#     ${MIN_SIZE} 68719476736 "all_nvm" \
#     "OMP_NUM_THREADS=20 MIN_INTERPOSE_MEM_SIZE=134217728"

# --- GapBS PR Twitter (RSS: 12.32 GiB) ---
# all_dram: 33.47 GiB DRAM (RSS fits) + 64 GiB NVM
# all_nvm: 2 MiB DRAM + 64 GiB NVM (RSS fits)
# run_workload "gapbs_pr_twitter" "${GAPBS_PR_BIN}" "${GAPBS_PR_ARGS}" \
#     ${MAX_DRAM} 68719476736 "all_dram" \
#     "OMP_NUM_THREADS=20 MIN_INTERPOSE_MEM_SIZE=134217728"
run_workload "gapbs_pr_twitter" "${GAPBS_PR_BIN}" "${GAPBS_PR_ARGS}" \
    ${MIN_SIZE} 68719476736 "all_nvm" \
    "OMP_NUM_THREADS=20 MIN_INTERPOSE_MEM_SIZE=134217728"

# --- Silo TPCC (RSS: 79.85 GiB) ---
# all_dram: 33.47 GiB DRAM + 77.32 GiB NVM overflow
# all_nvm: 3.11 GiB DRAM (RSS overflows dax1.0 by ~1.1 GiB + 2 GiB headroom) + 78.73 GiB NVM (dax1.0 cap)
run_workload "silo_tpcc" "${SILO_BIN}" "${SILO_ARGS}" \
    ${MAX_DRAM} 83019956224 "all_dram" \
    "OMP_NUM_THREADS=20"
run_workload "silo_tpcc" "${SILO_BIN}" "${SILO_ARGS}" \
    3336568832 ${MAX_NVM} "all_nvm" \
    "OMP_NUM_THREADS=20"

# --- Liblinear (RSS: 20.99 GiB) ---
# all_dram: 33.47 GiB DRAM (RSS fits) + 18.66 GiB NVM
# all_nvm: 2 MiB DRAM + 20.99 GiB NVM (need full RSS in NVM)
# run_workload "liblinear_kddb" "${LIBLINEAR_BIN}" "${LIBLINEAR_ARGS}" \
#     ${MAX_DRAM} 20034093056 "all_dram"
# run_workload "liblinear_kddb" "${LIBLINEAR_BIN}" "${LIBLINEAR_ARGS}" \
#     ${MIN_SIZE} 22535995392 "all_nvm"

echo ""
echo "All experiments complete. Results in: ${RESULTS_DIR}"
