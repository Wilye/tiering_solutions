#!/bin/bash

RESULTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="/users/shelby/tiering_solutions/src"
NUM_RUNS=1
TIMEOUT=1800  # 30 minutes

# Silo TPC-C config (1:8, c220g5)
SILO_BIN="/users/shelby/tiering_solutions/apps/silo/silo/out-perf.masstree/benchmarks/dbtest"
SILO_ARGS="--verbose --bench tpcc --num-threads 20 --scale-factor 100 --ops-per-worker 8000000 --numa-memory 85743345664"
SILO_DRAMSIZE=9299992576    # 8.66 GiB
SILO_NVMSIZE=83019956224    # 77.32 GiB (69.32 + 8 extra)

# GapBS PageRank g25 config (1:8)
PR_BIN="/users/shelby/workloads/gapbs/pr"
PR_ARGS="-n 16 -g 25"
PR_DRAMSIZE=1415577600      # 1.32 GiB
PR_NVMSIZE=11370758144      # 10.59 GiB

run_workload() {
    local name=$1
    local bin=$2
    local args=$3
    local dramsize=$4
    local nvmsize=$5
    local cba_label=$6
    local run_num=$7
    local extra_env=$8

    local outfile="${RESULTS_DIR}/${name}_${cba_label}_run${run_num}.txt"
    echo "=== Running ${name} ${cba_label} run ${run_num} ==="
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

# --- Default (normal sort) ---
echo "Building default (normal sort)..."
cd ${SRC_DIR}
make clean && make
echo ""

for i in $(seq 1 ${NUM_RUNS}); do
    run_workload "silo_tpcc_1-8" "${SILO_BIN}" "${SILO_ARGS}" \
        ${SILO_DRAMSIZE} ${SILO_NVMSIZE} "normal" ${i} \
        "OMP_NUM_THREADS=20"
done

# --- Inverted sort ---
echo "Building with inverted sort..."
cd ${SRC_DIR}
make invert-sort-no-cba
echo ""

for i in $(seq 1 ${NUM_RUNS}); do
    run_workload "silo_tpcc_1-8" "${SILO_BIN}" "${SILO_ARGS}" \
        ${SILO_DRAMSIZE} ${SILO_NVMSIZE} "invert_sort" ${i} \
        "OMP_NUM_THREADS=20"
done

# --- Rebuild default ---
echo "Rebuilding default..."
cd ${SRC_DIR}
make clean && make

echo ""
echo "All experiments complete. Results in: ${RESULTS_DIR}"
