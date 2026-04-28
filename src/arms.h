#ifndef ARMS_H
#define ARMS_H

#include <pthread.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <assert.h>

#ifndef __cplusplus
#include <stdatomic.h>
#else
#include <atomic>
#define _Atomic(X) std::atomic< X >
#endif

#ifdef __cplusplus
extern "C" {
#endif

#ifdef ALLOC_LRU
#include "policies/lru.h"
#endif

#ifdef ALLOC_SIMPLE
#include "policies/simple.h"
#endif

// Define target system here
// Options are SCAILP and C220G5
#define C220G5


#include "pebs.h"
#include "timer.h"
#include "interpose.h"
#include "fifo.h"

#ifdef C220G5
#define FAULT_THREAD_CPU  (10)
#define STATS_THREAD_CPU  (13)
#elif defined SCAILP
#define FAULT_THREAD_CPU  (0)
#define STATS_THREAD_CPU  (3)
#else
// Compile error - unknown system
#error "Unknown system - valid options are SCAILP and C220G5"
#endif


//#define ARMS_DEBUG
#define STATS_THREAD

#define USE_DMA
#define NUM_CHANNS 2
#define SIZE_PER_DMA_REQUEST (1024*1024)

#define MEM_BARRIER() __sync_synchronize()

extern uint64_t min_interpose_mem_size;

extern uint64_t nvmsize;
extern uint64_t dramsize;
extern char* drampath;
extern char* nvmpath;

#define NVMSIZE_DEFAULT   (64L * (1024L * 1024L * 1024L))
#define DRAMSIZE_DEFAULT  (32L * (1024L * 1024L * 1024L))

#define DRAMPATH_DEFAULT  "/dev/dax0.0"
#define NVMPATH_DEFAULT   "/dev/dax1.0"

#define BASEPAGE_SIZE	  (4UL * 1024UL)
#define HUGEPAGE_SIZE 	(2UL * 1024UL * 1024UL)
#define GIGAPAGE_SIZE   (1024UL * 1024UL * 1024UL)
#define PAGE_SIZE 	    HUGEPAGE_SIZE
#define CACHELINE_SIZE   (64)

#define MAX_NVME_PAGES  (NVMSIZE_DEFAULT / PAGE_SIZE)
#define MAX_DRAM_PAGES  (DRAMSIZE_DEFAULT / PAGE_SIZE)

#define BASEPAGE_MASK	(BASEPAGE_SIZE - 1)
#define HUGEPAGE_MASK	(HUGEPAGE_SIZE - 1)
#define GIGAPAGE_MASK   (GIGAPAGE_SIZE - 1)

#define BASE_PFN_MASK	(BASEPAGE_MASK ^ UINT64_MAX)
#define HUGE_PFN_MASK	(HUGEPAGE_MASK ^ UINT64_MAX)
#define GIGA_PFN_MASK   (GIGAPAGE_MASK ^ UINT64_MAX)

extern FILE *armslogf;
//#define LOG(...) fprintf(stderr, __VA_ARGS__)
//#define LOG(...)	fprintf(armslogf, __VA_ARGS__)
#define LOG(str, ...) while(0) {}

extern FILE *timef;
extern bool timing;

static inline void log_time(const char* fmt, ...)
{
  if (timing) {
    va_list args;
    va_start(args, fmt);
    vfprintf(timef, fmt, args);
    va_end(args);
  }
}


//#define LOG_TIME(str, ...) log_time(str, __VA_ARGS__)
//#define LOG_TIME(str, ...) fprintf(timef, str, __VA_ARGS__)
#define LOG_TIME(str, ...) while(0) {}

extern FILE *statsf;
#define LOG_STATS(str, ...) fprintf(stderr, str,  __VA_ARGS__)
//#define LOG_STATS(str, ...) fprintf(statsf, str, __VA_ARGS__)
//#define LOG_STATS(str, ...) while (0) {}

#if defined (ALLOC_ARMS)
  #define pagefault(...) pebs_pagefault(__VA_ARGS__)
  #define paging_init(...) pebs_init(__VA_ARGS__)
  #define mmgr_add(...) pebs_add_page(__VA_ARGS__)
  #define mmgr_find(...) pebs_find_page(__VA_ARGS__)
  #define mmgr_remove(...) pebs_remove_page(__VA_ARGS__)
  #define mmgr_stats(...) pebs_stats(__VA_ARGS__)
  #define policy_shutdown(...) pebs_shutdown(__VA_ARGS__)
#elif defined (ALLOC_LRU)
  #define pagefault(...) lru_pagefault(__VA_ARGS__)
  #define paging_init(...) lru_init(__VA_ARGS__)
  #define mmgr_remove(...) lru_remove_page(__VA_ARGS__)
  #define mmgr_stats(...) lru_stats(__VA_ARGS__)
  #define policy_shutdown(...) while(0) {}
#elif defined (ALLOC_SIMPLE)
  #define pagefault(...) simple_pagefault(__VA_ARGS__)
  #define paging_init(...) simple_init(__VA_ARGS__)
  #define mmgr_remove(...) simple_remove_page(__VA_ARGS__)
  #define mmgr_stats(...) simple_stats(__VA_ARGS__)
  #define policy_shutdown(...) while(0) {}
#endif


#define MAX_UFFD_MSGS	    (1)
#define MAX_COPY_THREADS  (4)

extern uint64_t cr3;
extern int dramfd;
extern int nvmfd;
extern bool is_init;
extern uint64_t dram_small_allocation_bytes;
extern uint64_t missing_faults_handled;
extern uint64_t migrations_up;
extern uint64_t migrations_down;
extern __thread bool internal_malloc;
extern __thread bool old_internal_call;
extern __thread bool internal_call;
extern __thread bool internal_munmap;

enum memtypes {
  FASTMEM = 0,
  SLOWMEM = 1,
  NMEMTYPES,
};

enum pagetypes {
  HUGEP = 0,
  BASEP = 1,
  NPAGETYPES
};

struct arms_page {
  uint64_t va;
  uint64_t devdax_offset;
  bool in_dram;
  enum pagetypes pt;
  volatile bool migrating;
  bool present;
  uint16_t accesses[NPBUFTYPES][2];
  pthread_mutex_t page_lock;

  // Our system
#ifdef SPATIAL_SMOOTHING
  float s_accesses[NPBUFTYPES];
#endif

  float w[WINDOW_SIZE];
  float score;
  float prev_score;
  uint16_t hot_age;
  bool can_promote;

  struct arms_page *next, *prev;
  struct fifo_list *list;
};
static_assert(sizeof(struct arms_page) == 128);

struct migration_req {
  struct arms_page *dram_page;
  struct arms_page *nvm_page;
  struct arms_page *free_page;
  bool need_demotion;

  struct migration_req *next, *prev;
  struct migration_req_list *list;
};

static inline uint64_t pt_to_pagesize(enum pagetypes pt)
{
  switch(pt) {
  case HUGEP: return HUGEPAGE_SIZE;
  case BASEP: return BASEPAGE_SIZE;
  default: assert(!"Unknown page type");
  }
}

static inline enum pagetypes pagesize_to_pt(uint64_t pagesize)
{
  switch (pagesize) {
    case BASEPAGE_SIZE: return BASEP;
    case HUGEPAGE_SIZE: return HUGEP;
    default: assert(!"Unknown page ssize");
  }
}

static inline void* arms_malloc(size_t z) {
  internal_call = true;
  void *p = malloc(z);
  internal_call = false;
  return p;
}
static inline void* arms_realloc(void *p, size_t z) {
  internal_call = true;
  void *r = realloc(p, z);
  internal_call = false;
  return r;
}

void arms_init();
void arms_stop();
void* arms_mmap(void *addr, size_t length, int prot, int flags, int fd, off_t offset);
int arms_munmap(void* addr, size_t length);
void *handle_fault();
void arms_migrate_up(struct arms_page *page, uint64_t dram_offset);
void arms_migrate_down(struct arms_page *page, uint64_t nvm_offset);
void arms_wp_page(struct arms_page *page, bool protect);
void arms_promote_pages(uint64_t addr);
void arms_demote_pages(uint64_t addr);

#ifdef ALLOC_LRU
void arms_clear_bits(struct arms_page *page);
uint64_t arms_get_bits(struct arms_page *page);
void arms_tlb_shootdown(uint64_t va);
#endif

// Commented out because -- identical to find_page(uint64_t va)
//struct arms_page* get_arms_page(uint64_t va);

void arms_print_stats();
void arms_clear_stats();

void arms_start_timing(void);
void arms_stop_timing(void);

#ifdef __cplusplus
}
#endif

#endif /* ARMS_H */
