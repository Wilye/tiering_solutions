#!/bin/bash

RESULTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="/users/shelby/tiering_solutions/src"
NUM_RUNS=3
TIMEOUT=1800  # 30 minutes

XSBENCH_BIN="/users/shelby/XSBench/openmp-threading/XSBench"
XSBENCH_ARGS="-g 130000 -p 20000000 -t 12"

GAPBS_BIN="/mnt/data/gapbs_copy/gapbs/bc"
GAPBS_ARGS="-n 16 -f /mnt/data/gapbs/benchmark/graphs/twitter.sg"
GAPBS_NVMSIZE=68719476736  # 64 GiB

# GiB to bytes (rounded down to 2 MiB page alignment)
gib_to_bytes() {
    python3 -c "
v = $1 * 1024 * 1024 * 1024
page = 2 * 1024 * 1024
v = int(v // page) * page
print(v)
"
}

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

    timeout ${TIMEOUT} sudo env DRAMSIZE=${dramsize} NVMSIZE=${nvmsize} ${extra_env} \
        LD_PRELOAD=${SRC_DIR}/libarms.so \
        ${bin} ${args} > "${outfile}" 2>&1

    local exit_code=$?
    if [ ${exit_code} -eq 124 ]; then
        echo "  TIMED OUT after ${TIMEOUT}s"
    else
        echo "  Done (exit code: ${exit_code})"
    fi
}

# XSBench ratios
XSBENCH_RATIOS="2-1 1-1 1-2 1-4 1-8 1-16"
declare -A XSBENCH_DRAM XSBENCH_NVM
XSBENCH_DRAM[2-1]=43.31;  XSBENCH_NVM[2-1]=21.66
XSBENCH_DRAM[1-1]=32.49;  XSBENCH_NVM[1-1]=32.49
XSBENCH_DRAM[1-2]=21.66;  XSBENCH_NVM[1-2]=43.31
XSBENCH_DRAM[1-4]=12.99;  XSBENCH_NVM[1-4]=51.98
XSBENCH_DRAM[1-8]=7.22;   XSBENCH_NVM[1-8]=57.75
XSBENCH_DRAM[1-16]=3.82;  XSBENCH_NVM[1-16]=61.15

# GapBS BC twitter ratios
GAPBS_RATIOS="2-1 1-1 1-2 1-4 1-8 1-16"
declare -A GAPBS_DRAM
GAPBS_DRAM[2-1]=8.72
GAPBS_DRAM[1-1]=6.54
GAPBS_DRAM[1-2]=4.36
GAPBS_DRAM[1-4]=2.62
GAPBS_DRAM[1-8]=1.45
GAPBS_DRAM[1-16]=0.77

# --- CBA ON ---
echo "Building with CBA ON (default)..."
cd ${SRC_DIR}
make clean && make
echo ""

for ratio in ${XSBENCH_RATIOS}; do
    dram=$(gib_to_bytes ${XSBENCH_DRAM[$ratio]})
    nvm=$(gib_to_bytes ${XSBENCH_NVM[$ratio]})
    for i in $(seq 1 ${NUM_RUNS}); do
        run_workload "xsbench_${ratio}" "${XSBENCH_BIN}" "${XSBENCH_ARGS}" \
            ${dram} ${nvm} "cba_on" ${i}
    done
done

for ratio in ${GAPBS_RATIOS}; do
    dram=$(gib_to_bytes ${GAPBS_DRAM[$ratio]})
    for i in $(seq 1 ${NUM_RUNS}); do
        run_workload "gapbs_bc_twitter_${ratio}" "${GAPBS_BIN}" "${GAPBS_ARGS}" \
            ${dram} ${GAPBS_NVMSIZE} "cba_on" ${i} \
            "OMP_NUM_THREADS=12 MIN_INTERPOSE_MEM_SIZE=134217728"
    done
done

# --- CBA OFF ---
echo "Building with CBA OFF..."
cd ${SRC_DIR}
make no-cba
echo ""

for ratio in ${XSBENCH_RATIOS}; do
    dram=$(gib_to_bytes ${XSBENCH_DRAM[$ratio]})
    nvm=$(gib_to_bytes ${XSBENCH_NVM[$ratio]})
    for i in $(seq 1 ${NUM_RUNS}); do
        run_workload "xsbench_${ratio}" "${XSBENCH_BIN}" "${XSBENCH_ARGS}" \
            ${dram} ${nvm} "cba_off" ${i}
    done
done

for ratio in ${GAPBS_RATIOS}; do
    dram=$(gib_to_bytes ${GAPBS_DRAM[$ratio]})
    for i in $(seq 1 ${NUM_RUNS}); do
        run_workload "gapbs_bc_twitter_${ratio}" "${GAPBS_BIN}" "${GAPBS_ARGS}" \
            ${dram} ${GAPBS_NVMSIZE} "cba_off" ${i} \
            "OMP_NUM_THREADS=12 MIN_INTERPOSE_MEM_SIZE=134217728"
    done
done

# --- Rebuild default ---
echo "Rebuilding default (CBA ON)..."
cd ${SRC_DIR}
make clean && make

echo ""
echo "All experiments complete. Results in: ${RESULTS_DIR}"
