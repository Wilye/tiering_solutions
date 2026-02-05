#define _GNU_SOURCE
#include <stdlib.h>
#include <pthread.h>
#include <semaphore.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdbool.h>
#include <pthread.h>
#include <assert.h>
#include <sys/time.h>
#include <unistd.h>
#include <asm/unistd.h>
#include <linux/perf_event.h>
#include <linux/hw_breakpoint.h>
#include <sys/mman.h>
#include <sched.h>
#include <sys/ioctl.h>
#include <float.h>
#include <fcntl.h>
#include <math.h>

#include "arms.h"
#include "pebs.h"
#include "timer.h"
#include "spsc-ring.h"

#include "khash.h"
#include "kdq.h"
#include "kbtree.h"

// Hash table for ARMS-handled pages
KHASH_MAP_INIT_INT64(kPagesMap, struct arms_page*)
khash_t(kPagesMap) *pages;
pthread_mutex_t pages_lock = PTHREAD_MUTEX_INITIALIZER;

#ifdef SPATIAL_SMOOTHING
/*
#define ktree_cmp(a,b) ((a) < (b.va) ? -1 : (a.va) > (b.va))
#define ktree_cmp(a,b) (                                                      \
  ((((struct arms_page*)a)->va) < (((struct arms_page*)b)->va))             \
    ? -1 : ((((struct arms_page*)a)->va) > (((struct arms_page*)b)->va)) )
KBTREE_INIT(kPagesTree, struct arms_page*, ktree_cmp)
*/
typedef struct {
  struct arms_page* page;
  uint64_t va;
} page_tree_entry_t;

#define ktree_cmp(a,b) (((a).va) < ((b).va) ? -1 : ((a).va) > ((b).va))
KBTREE_INIT(kPagesTree, page_tree_entry_t, ktree_cmp);

kbtree_t(kPagesTree) *pages_tree;
#else
khash_t(kPagesMap) *pages_map;
#endif

struct score_entry *scores;

//static struct fifo_list dram_hot_list;
//static struct fifo_list dram_cold_list;
//static struct fifo_list nvm_hot_list;
//static struct fifo_list nvm_cold_list;

static struct fifo_list dram_free_list;
static struct fifo_list nvm_free_list;

static struct migration_req_list migration_queue;
sem_t submission_sem;
sem_t completion_sem;

//static ring_handle_t promote_page_ring;
//static ring_handle_t demote_page_ring;

// Pages to be freed/added in the next interval
typedef struct mod_page {
  struct arms_page* page;
  bool free;
} mod_page_t;
static_assert(sizeof(mod_page_t) == 16);

KDQ_INIT(mod_page_t);

static kdq_t(mod_page_t) *mod_page_dq;
static pthread_mutex_t mod_page_dq_lock = PTHREAD_MUTEX_INITIALIZER;

/*
static ring_handle_t free_page_ring;
static pthread_mutex_t free_page_ring_lock = PTHREAD_MUTEX_INITIALIZER;
static ring_handle_t add_pages_ring;
static pthread_mutex_t add_pages_ring_lock = PTHREAD_MUTEX_INITIALIZER;
*/

static const float w_ewma_alpha[WINDOW_SIZE] = W_EWMA_ALPHA;
static const float hist_bias[WINDOW_SIZE] = HIST_BIAS;
static const float recn_bias[WINDOW_SIZE] = RECN_BIAS;

// Neighbour buffers
#ifdef SPATIAL_SMOOTHING
static ring_handle_t l_neighbours;
static ring_handle_t r_neighbours;
#endif

uint32_t policy_thread_period = PEBS_KSWAPD_INTERVAL_BIG;

volatile uint64_t global_version = 0;
volatile uint8_t curr_access_version = 0;
volatile uint8_t prev_access_version; // = 1 - curr_access_version

volatile uint8_t curr_window_index = 0;
volatile uint8_t prev_window_version;

double dram_bw_ewma = 0.0;
double nvm_bw_ewma = 0.0;
double nvm_bw_std = 0.0;
float promotion_cost_avg = MIN_PROMOTION_COST;
float demotion_cost_avg = MIN_DEMOTION_COST;
float latency_diff = UNLOADED_DRAM_LAT - UNLOADED_NVM_LAT;

float min_score, max_score;

// Migration effectiveness guardrail state
float prev_dram_bw = 0.0;
float prev_nvm_bw = 0.0;
uint64_t mig_eff_migrations_since_bw_check = 0;
float mig_eff_baseline_bw_var = 0.0;
float mig_eff_gain_per_migration = 0.0;
bool mig_eff_calibrated = false;
uint64_t mig_eff_violations = 0;
uint64_t mig_eff_checks = 0;

//uint64_t global_clock = 0;

uint64_t arms_pages_cnt = 0;
uint64_t other_pages_cnt = 0;
uint64_t total_pages_cnt = 0;
uint64_t zero_pages_cnt = 0;
uint64_t throttle_cnt = 0;
uint64_t unthrottle_cnt = 0;
uint64_t cools = 0;

const float * bias     = hist_bias; // History bias by default until triggered by PAR
uint32_t sampling_mode = DEFAULT_SAMPLING;

static struct perf_event_mmap_page *perf_page[PEBS_NPROCS][NPBUFTYPES];
int pfd[PEBS_NPROCS][NPBUFTYPES];

volatile bool need_cool_dram = false;
volatile bool need_cool_nvm = false;

static long perf_event_open(struct perf_event_attr *hw_event, pid_t pid,
  int cpu, int group_fd, unsigned long flags)
{
int ret;

ret = syscall(__NR_perf_event_open, hw_event, pid, cpu,
  group_fd, flags);
return ret;
}

#ifdef SCAILP
int mem_fd = -1;
void *imc_mmio_addr[NUM_IMC];
uint64_t prev_ctr_val[NUM_TIERS][NUM_IMC][NUM_BW_COUNTERS] = {0};

static uint32_t get_imc_bw_counter_offset(enum imc_bw_counters e) {
  switch(e) {
    case DRAM_READS:  return PCM_SERVER_IMC_DRAM_READS;
    case DRAM_WRITES: return PCM_SERVER_IMC_DRAM_WRITES;
    case NVM_READS:   return PCM_SERVER_IMC_PMM_READS;
    case NVM_WRITES:  return PCM_SERVER_IMC_PMM_WRITES;
    default: assert(!"Unknown IMC counter");
  }
}

uint64_t measure_bw(int tier)
{
  int i, j;
  uint64_t cur_ctr_val = 0;
  uint64_t cur_bw = 0;

  if (tier == 0) { // DRAM
    for (i=0; i<NUM_IMC; i++) {
      for (j=0; j<2; j++) {
        cur_ctr_val = *((uint64_t *)(imc_mmio_addr[i] + get_imc_bw_counter_offset(j)));
        cur_bw     += cur_ctr_val - prev_ctr_val[0][i][j];
        prev_ctr_val[tier][i][j] = cur_ctr_val;
      }
    }
  } else if (tier == 1) { // NVM
    for (i=0; i<NUM_IMC; i++) {
      for (j=2; j<4; j++) {
        cur_ctr_val = *((uint64_t *)(imc_mmio_addr[i] + get_imc_bw_counter_offset(j)));
        cur_bw     += cur_ctr_val - prev_ctr_val[1][i][j];
        prev_ctr_val[tier][i][j] = cur_ctr_val;
      }
    }
  }

  return cur_bw;
}

static int setup_imc_bw_counters() {
  mem_fd = open("/dev/mem", O_RDONLY);
  if (mem_fd == -1) {
    perror("open");
    return -1;
  }

  for (int i = 0; i < NUM_IMC; i++) {
    // Base address of each iMC increases by 0x80000
    imc_mmio_addr[i] = (char *)libc_mmap(NULL, PCM_SERVER_IMC_MMAP_SIZE, PROT_READ, MAP_SHARED, mem_fd, IMC_BASE_ADDR + (0x80000 * i));
    if (imc_mmio_addr[i] == MAP_FAILED) {
      perror("mmap");
      return -1;
    }
  }

  // Measure the bandwidth once to get the initial values
  for (int i = 0; i < NUM_TIERS; i++) {
    measure_nvm_bw(i);
  }

  return 0;
}

#elif defined C220G5

int bw_fds[NUM_TIERS][NUM_EVENTS][NUM_IMC];
uint64_t prev_bw_val[NUM_TIERS][NUM_EVENTS][NUM_IMC] = {0};

uint64_t measure_bw(int tier)
{
  uint64_t cur_bw = 0;
  uint64_t cur_val = 0;

  for (int j = 0; j < NUM_EVENTS; j++) {
    for (int k = 0; k < NUM_IMC; k++) {
      if (read(bw_fds[tier][j][k], &cur_val, sizeof(cur_val)) == -1) {
        LOG_ERROR("ERROR: Failed to read perf event for BW monitoring\n");
        exit(1);
      }
      cur_bw                 += cur_val - prev_bw_val[tier][j][k];
      prev_bw_val[tier][j][k] = cur_val;
    }
  }

  return cur_bw;
}
void open_perf_events()
{
  int fd;
  struct perf_event_attr pe;

  for (unsigned long i = 0; i < NUM_TIERS; i++) {
    for (unsigned long j = 0; j < NUM_EVENTS; j++) {
      for (unsigned long k = 0; k < NUM_IMC; k++) {
        memset(&pe, 0, sizeof(pe));
        pe.type = i + 12; // TODO: read type from /sys/devices/uncore_imc_x/type
        pe.size = sizeof(pe);
        pe.disabled = 1;
        pe.inherit = 1;
        pe.config = (j == 0) ? 0x304:0xC04;

        fd = perf_event_open(&pe, -1, 10, -1, 0);
        if (fd == -1) {
          LOG_ERROR("ERROR: Failed to open perf event for BW monitoring\n");
          exit(1);
        }
        bw_fds[i][j][k] = fd;
      }
    }
  }
}

static int setup_imc_bw_counters()
{
  open_perf_events();

  // Reset the counters
  for (int i = 0; i < NUM_TIERS; i++) {
    for (int j = 0; j < NUM_EVENTS; j++) {
      for (int k = 0; k < NUM_IMC; k++) {
        ioctl(bw_fds[i][j][k], PERF_EVENT_IOC_RESET, 0);
        ioctl(bw_fds[i][j][k], PERF_EVENT_IOC_ENABLE, 0);
      }
    }
    measure_bw(i); // Measure once to get the initial values
  }

  return 0;
}
#endif

void pebs_print_config();

static struct perf_event_mmap_page* perf_setup(__u64 config, __u64 config1, __u64 cpu, __u64 type)
{
  struct perf_event_attr attr;

  memset(&attr, 0, sizeof(struct perf_event_attr));

  attr.type = PERF_TYPE_RAW;
  attr.size = sizeof(struct perf_event_attr);

  attr.config = config;
  attr.config1 = config1;
  attr.sample_period = DEFAULT_SAMPLE_PERIOD;

  attr.sample_type = PERF_SAMPLE_IP | PERF_SAMPLE_TID | PERF_SAMPLE_ADDR;
  attr.pinned = 1;
  attr.disabled = 0;
  //attr.inherit = 1;
  attr.exclude_kernel = 1;
  attr.exclude_hv = 1;
  attr.exclude_callchain_kernel = 1;
  attr.exclude_callchain_user = 1;
  attr.precise_ip = 1;

  pfd[cpu][type] = perf_event_open(&attr, -1, cpu, -1, 0);
  if(pfd[cpu][type] == -1) {
    perror("perf_event_open");
  }
  assert(pfd[cpu][type] != -1);

  size_t mmap_size = sysconf(_SC_PAGESIZE) * PERF_PAGES;
  struct perf_event_mmap_page *p = mmap(NULL, mmap_size, PROT_READ | PROT_WRITE, MAP_SHARED, pfd[cpu][type], 0);
  if(p == MAP_FAILED) {
    perror("mmap");
  }
  assert(p != MAP_FAILED);

  return p;
}

static void update_sampling_frequency()
{
  int ret = 0;
  uint64_t sample_period = DEFAULT_SAMPLE_PERIOD;

  if (sampling_mode == HIGH_FIDELITY) {
    sample_period = HF_SAMPLE_PERIOD;
  }

  for (int i = 0; i < PEBS_NPROCS; i++) {
#ifdef JOSEPM
      if (i >= 8 && i < 16) {
        continue;
      }
#elif defined C220G5
      if (i >= 10 && i < 20) {
      continue;
      }
#endif
    for (int j = 0; j < NPBUFTYPES; j++) {
      ret = ioctl(pfd[i][j], PERF_EVENT_IOC_PERIOD, &sample_period);
      if (ret != 0) {
        perror("PERF_EVENT_IOC_PERIOD");
      }
    }
  }
}

void *pebs_scan_thread()
{
#ifdef SAMPLE_BASED_COOLING
  uint64_t samples_since_cool = 0;
#endif

  cpu_set_t cpuset;
  pthread_t thread;

  thread = pthread_self();
  CPU_ZERO(&cpuset);
  CPU_SET(SCANNING_THREAD_CPU, &cpuset);
  int s = pthread_setaffinity_np(thread, sizeof(cpu_set_t), &cpuset);
  if (s != 0) {
    perror("pthread_setaffinity_np");
    assert(0);
  }

  for(;;) {
    for (int i = 0; i < PEBS_NPROCS; i++) {
#ifdef JOSEPM
      if (i >= 8 && i < 16) {
        continue;
      }
#elif defined C220G5
	  if (i >= 10 && i < 20) {
		continue;
	  }
#endif
      for(int j = 0; j < NPBUFTYPES; j++) {
        struct perf_event_mmap_page *p = perf_page[i][j];
        char *pbuf = (char *)p + p->data_offset;

        __sync_synchronize();

        if(p->data_head == p->data_tail) {
          continue;
        }

        struct perf_event_header *ph = (void *)(pbuf + (p->data_tail % p->data_size));
        struct perf_sample* ps;
        struct arms_page* page;

        switch(ph->type) {
        case PERF_RECORD_SAMPLE:
            ps = (struct perf_sample*)ph;
            assert(ps != NULL);
            if(ps->addr != 0) {
              __u64 pfn = ps->addr & HUGE_PFN_MASK;
              page = pebs_find_page(pfn);
              if (page != NULL) {
                if (page->va != 0) {
                  page->accesses[j][curr_access_version]++;
                }
                arms_pages_cnt++;
              } else {
                other_pages_cnt++;
              }
              total_pages_cnt++;
            }
            else {
              zero_pages_cnt++;
            }
  	      break;
        case PERF_RECORD_THROTTLE:
        case PERF_RECORD_UNTHROTTLE:
          LOG_INFO("%s event!\n", ph->type == PERF_RECORD_THROTTLE ? "THROTTLE" : "UNTHROTTLE");
          if (ph->type == PERF_RECORD_THROTTLE) {
              throttle_cnt++;
          }
          else {
              unthrottle_cnt++;
          }
          break;
        default:
          LOG_ERROR("ERROR: Unknown perf_event type %u\n", ph->type);
          assert(0);
          break;
        }

        p->data_tail += ph->size;
      }
    }
  }

  return NULL;
}

static void pebs_migrate_down(struct arms_page *page, uint64_t offset)
{
  struct timeval start, end;

  gettimeofday(&start, NULL);

  page->migrating = true;
  arms_wp_page(page, true);
  arms_migrate_down(page, offset);
  page->migrating = false;

  gettimeofday(&end, NULL);
  LOG_DEBUG("migrate_down: %f s\n", elapsed(&start, &end));
}

static void pebs_migrate_up(struct arms_page *page, uint64_t offset)
{
  struct timeval start, end;

  gettimeofday(&start, NULL);

  page->migrating = true;
  arms_wp_page(page, true);
  arms_migrate_up(page, offset);
  page->migrating = false;

  gettimeofday(&end, NULL);
  LOG_DEBUG("migrate_up: %f s\n", elapsed(&start, &end));
}

// Sorts in ascending order
int ulong_sort_cmp(const void *a, const void *b) {
  uint64_t _a = *(const uint64_t *)a;
  uint64_t _b = *(const uint64_t *)b;
  return (_a < _b) ? -1 : (_a > _b);
}

// Sorts in descending order
int sort_entry_cmp(const void *a, const void *b) {
  struct score_entry _a = *(const struct score_entry*)a;
  struct score_entry _b = *(const struct score_entry*)b;

  return (_a.score > _b.score) ? -1 : (_a.score < _b.score);
}

static void reset_page_access_fields(struct arms_page *page)
{
  for (int i = 0; i < NPBUFTYPES; i++) {
    page->accesses[i][0] = 0;
    page->accesses[i][1] = 0;
    #ifdef SPATIAL_SMOOTHING
    page->s_accesses[i] = 0;
    #endif
  }
  for (int i = 0; i < WINDOW_SIZE; i++) {
    page->w[i] = 0;
  }
  page->hot_age = 0;
  page->prev_score = 0;
}

static inline void update_window(struct arms_page* page) {
#ifdef SPATIAL_SMOOTHING
  float accesses = page->s_accesses[DRAMREAD] + page->s_accesses[NVMREAD] + (NVM_WRITES_WEIGHT * page->s_accesses[WRITE]);
#else
  uint32_t accesses = page->accesses[DRAMREAD][prev_access_version] + page->accesses[NVMREAD][prev_access_version] + (NVM_WRITES_WEIGHT * page->accesses[WRITE][prev_access_version]);
#endif

  if (sampling_mode == DEFAULT_SAMPLING) {
    for (uint8_t i = 0; i < WINDOW_SIZE; i++) {
      page->w[i] = (1. - w_ewma_alpha[i]) * page->w[i] +
          (w_ewma_alpha[i] * ((DEFAULT_SAMPLE_PERIOD/HF_SAMPLE_PERIOD) * accesses)); // We maintain counters in high-fidelity, so scale
    }
  } else if (sampling_mode == HIGH_FIDELITY) {
    for (uint8_t i = 0; i < WINDOW_SIZE; i++) {
      page->w[i] = (1. - w_ewma_alpha[i]) * page->w[i] + (w_ewma_alpha[i] * accesses);
    }
  }
}

static inline float compute_score(const struct arms_page *page, const float *bias) {
  // Update the score (average of the window)
  float score = 0;
  for (int i = 0; i < WINDOW_SIZE; i++) {
    score += page->w[i] * bias[i];
  }
  return score;
}

static inline float _moving_avg_add(float avg, float new_val, uint32_t count) {
  return ((count * avg) + new_val) / (count + 1);
}
static inline void moving_avg_add(float* avg, struct arms_page* page, uint32_t* count) {
  avg[DRAMREAD] = _moving_avg_add(avg[DRAMREAD], page->accesses[DRAMREAD][prev_access_version], *count);
  avg[NVMREAD] = _moving_avg_add(avg[NVMREAD], page->accesses[NVMREAD][prev_access_version], *count);
  avg[WRITE] = _moving_avg_add(avg[WRITE], page->accesses[WRITE][prev_access_version], *count);
  (*count)++;
}

static inline float _moving_avg_sub(float avg, float old_val, uint32_t count) {
  if ((count - 1) == 0) {
    // no more elements in the moving average -- set the average to 0
    return 0;
  }
  return ((count * avg) - old_val) / (count - 1);
}
static inline void moving_avg_sub(float* avg, struct arms_page* page, uint32_t* count) {
  avg[DRAMREAD] = _moving_avg_sub(avg[DRAMREAD], page->accesses[DRAMREAD][prev_access_version], *count);
  avg[NVMREAD] = _moving_avg_sub(avg[NVMREAD], page->accesses[NVMREAD][prev_access_version], *count);
  avg[WRITE] = _moving_avg_sub(avg[WRITE], page->accesses[WRITE][prev_access_version], *count);
  (*count)--;
}

#ifdef SPATIAL_SMOOTHING
static size_t calculate_scores_tree(struct score_entry *scores_out, const float *bias)
{
  struct ptimer window_timer, spatial_smooth_timer;
  ptimer_init(&window_timer, "Scores (window)");
  ptimer_init(&spatial_smooth_timer, "Scores (spatial smooth)");

  struct arms_page *page;
  kbitr_t itr, n_itr;

  size_t idx = 0;
  size_t s_idx = 0;

  page_tree_entry_t *entry_ptr;
  struct arms_page *p;
  page_tree_entry_t *n_entry_ptr;
  size_t n_idx;
  uint64_t n_va;

  float smooth_avg_v[NPBUFTYPES];
  uint32_t smooth_avg_cnt = 0;
  memset(smooth_avg_v, 0.0, sizeof(smooth_avg_v));

  // Clear ring buffers
  ring_buf_reset(l_neighbours);
  ring_buf_reset(r_neighbours);

  size_t pages_cnt = kb_size(pages_tree);
  if (pages_cnt == 0) {
    return 0; // no pages to process
  }

  // Init the (right) neightbour iterator
  kb_itr_first(kPagesTree, pages_tree, &n_itr);
  assert(kb_itr_valid(&n_itr));
  kb_itr_next(kPagesTree, pages_tree, &n_itr);

  // Iterate over the pages, in ascending order of VA
  kb_itr_first(kPagesTree, pages_tree, &itr);
  for (;
      kb_itr_valid(&itr);
      kb_itr_next(kPagesTree, pages_tree, &itr), idx++
  ) {
    assert(idx < pages_cnt);

    entry_ptr = &kb_itr_key(page_tree_entry_t, &itr);
    page = entry_ptr->page;
    if (page == NULL || !page->present) {
      continue;
    }

    ptimer_continue(&spatial_smooth_timer);
    LOG_DEBUG("Before smoothing\n");

    // Pop left neighbour(s)
    LOG_DEBUG("-> LEFT NEIGHBOURS\n");
    while(ring_buf_size(l_neighbours) > 0) {
      n_idx = idx - ring_buf_size(l_neighbours);
      p = (struct arms_page*)ring_buf_peek_tail(l_neighbours, 0);
      if (p->va == page->va - ((idx - n_idx) * HUGEPAGE_SIZE)) {
        break;
      }
      // Remove neighbour from left neighbours
      moving_avg_sub(smooth_avg_v, p, &smooth_avg_cnt);
      ring_buf_get(l_neighbours);
    }
    assert(ring_buf_size(l_neighbours) >= 0 && ring_buf_size(l_neighbours) <= NUM_NEIGHBOURS);

    // Append right neighbour(s)
    LOG_DEBUG("-> RIGHT NEIGHBOURS\n");
    n_idx = idx + ring_buf_size(r_neighbours) + 1;
    while(ring_buf_size(r_neighbours) < NUM_NEIGHBOURS) {
      if (!kb_itr_valid(&n_itr)) {
        break; // no more neighbours
      }
      // Check if the next neighbour exists
      n_va = page->va + ((n_idx - idx) * HUGEPAGE_SIZE);
      n_entry_ptr = &kb_itr_key(page_tree_entry_t, &n_itr);
      p = n_entry_ptr->page;
      assert(p != NULL);
      assert(p->va == n_entry_ptr->va);
      if (p->va != n_va) {
        break;
      }
      // Add neighbour to right neighbours
      ring_buf_put(r_neighbours, (uint64_t*)p);
      moving_avg_add(smooth_avg_v, p, &smooth_avg_cnt);
      // Move to the next neighbour
      kb_itr_next(kPagesTree, pages_tree, &n_itr);
      n_idx++;
    }
    assert(ring_buf_size(r_neighbours) >= 0 && ring_buf_size(r_neighbours) <= NUM_NEIGHBOURS);

    // Add this page accesses to the moving average
    moving_avg_add(smooth_avg_v, page, &smooth_avg_cnt);

    // Calculate smoothed access count
    page->s_accesses[DRAMREAD] = smooth_avg_v[DRAMREAD];
    page->s_accesses[NVMREAD] = smooth_avg_v[NVMREAD];
    page->s_accesses[WRITE] = smooth_avg_v[WRITE];

    ptimer_stop(&spatial_smooth_timer);
    LOG_DEBUG("After smoothing\n");

    // Update the window with the smoothed access count
    update_window(page);

    // Calculate the hotness score
    page->score = compute_score(page, bias);
    scores_out[s_idx++] = (struct score_entry){ page, page->score };

    // Append this page to the left neighbours
    ring_buf_put(l_neighbours, (uint64_t*)page);

    // If the left neighbours buffer is full, pop the leftmost neighbour
    if (ring_buf_size(l_neighbours) > NUM_NEIGHBOURS) {
      p = (struct arms_page*)ring_buf_get(l_neighbours);
      moving_avg_sub(smooth_avg_v, p, &smooth_avg_cnt);
    }
    // Pop the leftmost neighbour in right neighbours buffer
    // This is soon-to-be the next page (i.e., the right neighbour)
    if (ring_buf_size(r_neighbours) > 0) {
      p = (struct arms_page*)ring_buf_get(r_neighbours);
      moving_avg_sub(smooth_avg_v, p, &smooth_avg_cnt);
    }
  }

  // Zero the access counts of all the pages
  for (kb_itr_first(kPagesTree, pages_tree, &itr);
      kb_itr_valid(&itr);
      kb_itr_next(kPagesTree, pages_tree, &itr)
  ) {
    entry_ptr = &kb_itr_key(page_tree_entry_t, &itr);
    page = entry_ptr->page;
    if (page == NULL || !page->present) {
      continue;
    }
    for (int i = 0; i < NPBUFTYPES; i++) {
      page->accesses[i][prev_access_version] = 0;
    }
  }
  ptimer_print(&spatial_smooth_timer);

  return s_idx;
}
#endif

static size_t calculate_scores_map(struct score_entry *scores_out, const float *bias)
{
  struct ptimer window_timer;
  ptimer_init(&window_timer, "Scores (window)");

  struct arms_page *page;
  khiter_t key;
  size_t s_idx = 0;

  size_t pages_cnt = kh_size(pages_map);
  if (pages_cnt == 0) {
    return 0; // no pages to process
  }

  // Iterate over the pages
  for (key = kh_begin(pages_map); key != kh_end(pages_map); ++key) {
    if (!kh_exist(pages_map, key)) {
      continue;
    }
    page = kh_val(pages_map, key);
    if (page == NULL || !page->present) {
      continue;
    }

    #ifdef SPATIAL_SMOOTHING
    LOG_DEBUG("%lu,%f|", page->va, page->s_accesses[DRAMREAD] + page->s_accesses[NVMREAD]); //+ page->s_accesses[WRITE]);
    #endif

    // Update the window values
    update_window(page);

    // Reset the access counts
    page->accesses[DRAMREAD][prev_access_version] = 0;
    page->accesses[NVMREAD][prev_access_version] = 0;
    page->accesses[WRITE][prev_access_version] = 0;

    // Calculate the hotness score
    page->prev_score = page->score;
    page->score = compute_score(page, bias);
    scores_out[s_idx++] = (struct score_entry){ page, page->score };

  }
  ptimer_print(&window_timer);

  return s_idx;
}

static inline int continue_migration(struct arms_page *hp, struct arms_page *cp)
{
 // Compare the min of hot page and max of cold page
 // A hot page should hav all EWMAs greater than the max EWMA of a cold page
 float hot_page_min_avg = hp->w[0];
 float cold_page_max_avg = cp->w[WINDOW_SIZE-1];

 for (int i = 1; i < WINDOW_SIZE; i++) {
   if (hp->w[i] < hot_page_min_avg) {
     hot_page_min_avg = hp->w[i];
   }
   if (cp->w[i] > cold_page_max_avg) {
     cold_page_max_avg = cp->w[i];
   }
  }

  if (hot_page_min_avg < cold_page_max_avg) {
    LOG_INFO("Stopping migration of 0x%lx (score: %.3f (%.3f %.3f)) and 0x%lx (score: %.3f (%.3f %.3f)) cause of min/max\n",
              hp->va, hp->score, hp->w[0], hp->w[1],
              cp->va, cp->score, cp->w[0], cp->w[1]);
    return 0;
  }

  // Cost-benefit analysis
  float cost = CB_MULTIPLIER * (promotion_cost_avg + demotion_cost_avg);
  float benefit =(hp->score - cp->score) * hp->hot_age * HF_SAMPLE_PERIOD * latency_diff;

  if (benefit < cost) {
    LOG_INFO("Stopping migration of 0x%lx (score: %.3f (%.3f %.3f)) and 0x%lx (score: %.3f (%.3f %.3f)) cause of cost-benefit\n",
              hp->va, hp->score, hp->w[0], hp->w[1],
              cp->va, cp->score, cp->w[0], cp->w[1]);
    return 0;
  }

  return 1;
}

void promote_to_free_dram_page(struct arms_page *p, struct arms_page *np)
{
  uint64_t old_offset;

  // There could be a possible race with pebs_remove_page()
  // So acquire lock to ensure page is not removed while being migrated
  pthread_mutex_lock(&(p->page_lock));
  if (!p->present) {
    // Don't migrate as this page is being removed
    // Put np back on the dram_free_list because we are not going to migrate
    enqueue_fifo(&dram_free_list, np);
    pthread_mutex_unlock(&(p->page_lock));
    return;
  }

  old_offset = p->devdax_offset;
  pebs_migrate_up(p, np->devdax_offset);
  // We can release the lock now that migration is complete
  pthread_mutex_unlock(&(p->page_lock));

  // Reset the page fields
  np->devdax_offset = old_offset;
  np->in_dram = false;
  np->present = false;
  reset_page_access_fields(np);

  enqueue_fifo(&nvm_free_list, np);
}

bool demote_to_free_nvm_page(struct arms_page *cp, struct arms_page *np)
{
  uint64_t old_offset;

  // There could be a possible race with pebs_remove_page()
  // So acquire lock to ensure page is not removed while being migrated
  pthread_mutex_lock(&(cp->page_lock));
  if (!cp->present) {
    // Don't migrate as this page is being removed
    pthread_mutex_unlock(&(cp->page_lock));
    return false;
  }

  old_offset = cp->devdax_offset;
  pebs_migrate_down(cp, np->devdax_offset);

  pthread_mutex_unlock(&(cp->page_lock));

  // Reset the page fields
  np->devdax_offset = old_offset;
  np->in_dram = true;
  np->present = false;
  reset_page_access_fields(np);

  // Don't add the page to the free list because
  // it will be used immediately after
  //enqueue_fifo(&dram_free_list, np);
  return true;
}

void *pebs_migration_thread()
{
  struct migration_req *req;
  struct ptimer migrate_timer;

  ptimer_init(&migrate_timer, "Migrate");

  while(true) {
    sem_wait(&submission_sem);

    while(true) {
      req = dequeue_fifo_m(&migration_queue);
      if (req == NULL) {
        break;
      }

      // Demote a page if necessary
      if (req->need_demotion) {
        ptimer_start(&migrate_timer);
        if (!demote_to_free_nvm_page(req->dram_page, req->free_page)) {
          enqueue_fifo(&nvm_free_list, req->free_page);
          sem_post(&completion_sem);
          free(req);
          continue;
        }
        ptimer_stop(&migrate_timer);
        demotion_cost_avg = (MIGRATION_COST_ALPHA * migrate_timer.elapsed_us) + ((1 - MIGRATION_COST_ALPHA) * demotion_cost_avg);
      }

      // Promote the hot NVM page
      ptimer_start(&migrate_timer);
      promote_to_free_dram_page(req->nvm_page, req->free_page);
      ptimer_stop(&migrate_timer);
      promotion_cost_avg = (MIGRATION_COST_ALPHA * migrate_timer.elapsed_us) + ((1 - MIGRATION_COST_ALPHA) * promotion_cost_avg);

      sem_post(&completion_sem);
      free(req);
    }
  }
}

void *pebs_policy_thread()
{
  struct ptimer loop_timer, tree_timer, score_timer, sort_timer, id_timer;
  struct ptimer remaining_timer;
  ptimer_init(&loop_timer, "Loop");
  ptimer_init(&tree_timer, "Tree");
  ptimer_init(&score_timer, "Score");
  ptimer_init(&sort_timer, "Sort");
  ptimer_init(&id_timer, "Identify");
  ptimer_init(&remaining_timer, "Remaining");

  cpu_set_t cpuset;
  pthread_t thread;
  //int tries;
  struct arms_page *p;
  struct arms_page *cp;
  struct arms_page *np;
  uint64_t migrated_bytes;
  //uint64_t old_offset;
  double migrate_time_us;
  struct arms_page* page = NULL;

  #ifdef SPATIAL_SMOOTHING
  page_tree_entry_t entry;
  #endif

  size_t s_pages_cnt;

  struct migration_req *m_req;

  int64_t promote_idx = 0;
  int64_t demote_idx = 0;
  size_t migrated_pages = 0;
  size_t num_migration_jobs = 0;
  float batch_size = NUM_MIGRATION_THREADS;

  float    cur_dram_bw = 0;
  float    cur_nvm_bw = 0;
  float    cusum      = 0;
  uint32_t time_since_recn = 0;

  uint32_t max_migrations_cur_interval = (policy_thread_period) / (promotion_cost_avg+demotion_cost_avg);

  // Use a dedicated CPU core for the policy thread
  thread = pthread_self();
  CPU_ZERO(&cpuset);
  CPU_SET(MIGRATION_THREAD_CPU, &cpuset);
  int s = pthread_setaffinity_np(thread, sizeof(cpu_set_t), &cpuset);
  if (s != 0) {
    perror("pthread_setaffinity_np");
    assert(0);
  }

  // Initialize memory controller BW counters
  setup_imc_bw_counters();

  // Sleep first to allow the scanning thread to start
  usleep((uint64_t)((1.0 * policy_thread_period)));

  for (;;) {
    ptimer_start(&loop_timer);
    ptimer_start(&remaining_timer);

    LOG_REPORT("\n========================================\n");
    LOG_REPORT("Starting new interval\n");
    LOG_REPORT("========================================\n");

    // Update the window index (circular buffer)
    curr_window_index = global_version % WINDOW_SIZE;
    // "Bump" the global version to indicate that we are starting a new interval
    global_version++;
    prev_access_version = curr_access_version;
    curr_access_version = 1 - curr_access_version;
    __sync_synchronize();

    // Compute peak-to-average ratio every 1 second
    if (global_version % (1000000 / policy_thread_period) == 0) {
      cur_dram_bw = ((float)(measure_bw(0)) * (CACHELINE_SIZE)) / (1024ULL * 1024ULL * 1024ULL);
      cur_nvm_bw = ((float)(measure_bw(1)) * (CACHELINE_SIZE)) / (1024ULL * 1024ULL * 1024ULL);

      // --- Migration Effectiveness Guardrail ---
      float dram_bw_delta = cur_dram_bw - prev_dram_bw;

      if (prev_dram_bw > 0) {  // Skip the very first measurement (no previous to compare)
        if (mig_eff_migrations_since_bw_check == 0) {
          // No migrations: learn the noise floor
          mig_eff_baseline_bw_var = (1 - MIG_EFF_BW_VAR_ALPHA) * mig_eff_baseline_bw_var
                                   + MIG_EFF_BW_VAR_ALPHA * fabsf(dram_bw_delta);
        } else if (mig_eff_migrations_since_bw_check >= MIG_EFF_MIN_MIGRATIONS) {
          // Migrations happened: check effectiveness
          if (mig_eff_calibrated && mig_eff_baseline_bw_var > 0) {
            float expected_gain = mig_eff_gain_per_migration * mig_eff_migrations_since_bw_check;
            float shortfall = expected_gain - dram_bw_delta;

            if (shortfall > MIG_EFF_THRESHOLD * mig_eff_baseline_bw_var) {
              mig_eff_violations++;
              LOG_REPORT("MIG_EFF VIOLATION #%lu: %lu migrations, expected %.3f GB/s gain, actual %.3f GB/s (baseline var: %.3f)\n",
                         mig_eff_violations, mig_eff_migrations_since_bw_check,
                         expected_gain, dram_bw_delta, mig_eff_baseline_bw_var);
            }
            mig_eff_checks++;
          }

          // Learn from this interval: update gain-per-migration model if BW improved
          if (dram_bw_delta > 0) {
            float observed_gain = dram_bw_delta / mig_eff_migrations_since_bw_check;
            mig_eff_gain_per_migration = (1 - MIG_EFF_GAIN_ALPHA) * mig_eff_gain_per_migration
                                        + MIG_EFF_GAIN_ALPHA * observed_gain;
            mig_eff_calibrated = true;
          }
        }
      }

      prev_dram_bw = cur_dram_bw;
      prev_nvm_bw = cur_nvm_bw;
      mig_eff_migrations_since_bw_check = 0;
      // --- End Migration Effectiveness Guardrail ---

      // update the BW
      dram_bw_ewma = (1 - HCD_EWMA_ALPHA) * dram_bw_ewma + HCD_EWMA_ALPHA * cur_dram_bw;
      nvm_bw_ewma = (1 - HCD_EWMA_ALPHA) * nvm_bw_ewma + HCD_EWMA_ALPHA * cur_nvm_bw;
      nvm_bw_std  = ((1 - HCD_STD_ALPHA) * nvm_bw_std * nvm_bw_std) + HCD_STD_ALPHA * (cur_nvm_bw - nvm_bw_ewma) * (cur_nvm_bw - nvm_bw_ewma);
      nvm_bw_std = sqrtf(fmaxf(nvm_bw_std, 1e-12f)); // avoid stddev of 0

      // Scale drift and threshold based on stddev
      // This allows the algorithm to adapt to different levels of noise in the measurements
      float drift = HCD_PH_DRIFT * nvm_bw_std;
      float threshold = HCD_PH_THRESHOLD * nvm_bw_std;

      // Page-Hinkley test
      cusum += ((cur_nvm_bw - nvm_bw_ewma) - drift);
      cusum = fmaxf(cusum, 0.0f); // We are only interested in positive deviations
      if (cusum > threshold) {
        if (bias == hist_bias && cur_nvm_bw > HCD_RECN_MIN_NVM_BW) {
          bias = recn_bias;
          LOG_REPORT("Switching to RECN bias\n");
          time_since_recn = 0;
        }
        cusum = 0;
      } else if (bias == recn_bias) {
          time_since_recn++;
          if (time_since_recn >= HCD_RECN_MAX_PERIODS && cusum <= 0) {
          bias = hist_bias;
          LOG_REPORT("Switching back to HIST bias\n");
          time_since_recn = 0;
        }
      }

      batch_size = ((NVM_WR_BW_KNEE - cur_nvm_bw) / NVM_WR_BW_KNEE) * NUM_MIGRATION_THREADS;
      batch_size = floor(batch_size);
      if (batch_size < 1) {
        batch_size = 1;
      }

      LOG_REPORT("NVM bw: %f, NVM bw EWMA: %f, NVM bw stddev: %f, cusum: %f\n",
                 cur_nvm_bw, nvm_bw_ewma, nvm_bw_std, cusum);

      // Calculate the latency diff between DRAM and NVM
      float dram_lat = UNLOADED_DRAM_LAT;
      float nvm_lat = UNLOADED_NVM_LAT;
      if (dram_bw_ewma > DRAM_BW_KNEE) {
        dram_lat += (dram_bw_ewma - DRAM_BW_KNEE) * DRAM_BW_SLOPE;
      }
      if (nvm_bw_ewma > NVM_RD_BW_KNEE) {
        nvm_lat += (nvm_bw_ewma - NVM_RD_BW_KNEE) * NVM_BW_SLOPE;
      }
      latency_diff = nvm_lat - dram_lat;
      LOG_REPORT("Estimated latency diff: %.2f us\n", latency_diff);
    }

    // free pages using free page ring buffer
    ptimer_start(&tree_timer);
    while (true) {
      mod_page_t* mp;
      pthread_mutex_lock(&mod_page_dq_lock);
      if (kdq_size(mod_page_dq) == 0) {
        pthread_mutex_unlock(&mod_page_dq_lock);
        break;
      }
      mp = kdq_shift(mod_page_t, mod_page_dq);
      pthread_mutex_unlock(&mod_page_dq_lock);

      page = mp->page;
      LOG_DEBUG("Processing page %p [va: %lu]\n", page, page->va);

      #ifdef SPATIAL_SMOOTHING
      entry.page = page;
      entry.va = page->va;

      if (mp->free) {
        kb_del(kPagesTree, pages_tree, entry);

        // Add page to correct free list
        if (page->in_dram) {
          enqueue_fifo(&dram_free_list, page);
        } else {
          enqueue_fifo(&nvm_free_list, page);
        }
        reset_page_access_fields(page);
      } else {
        kb_put(kPagesTree, pages_tree, entry);
      }
      #else
      khiter_t k = kh_get(kPagesMap, pages_map, page->va);
      if (mp->free) {
        if (k != kh_end(pages_map)) {
          kh_del(kPagesMap, pages_map, k);

          // Add page to correct free list
          if (page->in_dram) {
            enqueue_fifo(&dram_free_list, page);
          } else {
            enqueue_fifo(&nvm_free_list, page);
          }
          reset_page_access_fields(page);
        } else {
          LOG_ERROR("WARNING: Page not found in map\n");
        }
      }
      else {
        int absent;
        k = kh_put(kPagesMap, pages_map, page->va, &absent);
        assert(absent);
        kh_value(pages_map, k) = page;
      }

      #endif
    }
    ptimer_stop_and_print(&tree_timer);

    // Calculate the scores
    ptimer_start(&score_timer);

    #ifdef SPATIAL_SMOOTHING
    s_pages_cnt = calculate_scores_tree(scores, bias);
    #else
    s_pages_cnt = calculate_scores_map(scores, bias);
    #endif

    ptimer_stop_and_print(&score_timer);

    // Sort the scores (in descending order)
    ptimer_start(&sort_timer);
    qsort(scores, s_pages_cnt, sizeof(struct score_entry), sort_entry_cmp);
    ptimer_stop_and_print(&sort_timer);

    // Set the top_since_iter for the top pages
    for (int k = 0; k < dramsize/PAGE_SIZE && k < s_pages_cnt; k++) {
      struct arms_page* top_page = scores[k].page;
      if (scores[k].score != 0) {
        top_page->hot_age++;
        if (top_page->hot_age > 1 && (top_page->score >= top_page->prev_score)) {
          // Page has continued to stay hot, so can be promoted
          top_page->can_promote = true;
        }
      }
    }
    for (int k = dramsize/PAGE_SIZE; k < s_pages_cnt; k++) {
      scores[k].page->hot_age = 0;
      scores[k].page->can_promote = false;
    }

    if (s_pages_cnt == 0) {
      goto loop_end;
    }
    min_score = scores[s_pages_cnt - 1].score;
    max_score = scores[0].score;

    LOG_REPORT("min_score: %.3f (%.3f %.3f), max_score: %.3f (%.3f %.3f)\n",
               min_score, scores[s_pages_cnt - 1].page->w[0], scores[s_pages_cnt - 1].page->w[1],
               max_score, scores[0].page->w[0], scores[0].page->w[1]);
    LOG_REPORT("Prom cost: %f, Dem cost: %f\n", promotion_cost_avg, demotion_cost_avg);

    // Perform migrations
    ptimer_reset(&id_timer);

    promote_idx = 0;
    demote_idx = s_pages_cnt - 1;
    migrated_pages = 0;

    // Before starting migrations of this interval, check for completion of previous migrations
    while (num_migration_jobs > 0) {
      sem_wait(&completion_sem);
      num_migration_jobs--;
    }

    ptimer_stop(&remaining_timer);

    /*******************/
    /* MIGRATIONs LOOP*/
    migrated_bytes     = 0;
    num_migration_jobs = 0;
    max_migrations_cur_interval = ((policy_thread_period) / (promotion_cost_avg+demotion_cost_avg)) * batch_size;
    while (promote_idx < dramsize/PAGE_SIZE && promote_idx < demote_idx) {
      // If we have scheduled the maximum number of migrations for this interval, stop
      if (num_migration_jobs >= max_migrations_cur_interval) {
        LOG_REPORT("Scheduled %lu migrations\n", num_migration_jobs);
        break;
      }

      if (scores[promote_idx].score == 0)
        break;
      // find the hotest NVM page that needs to be promoted
      ptimer_continue(&id_timer);
      while (promote_idx < demote_idx && scores[promote_idx].page->in_dram) {
        promote_idx++;
      }
      if (promote_idx >= demote_idx) {
        break;
      }
      p = scores[promote_idx].page;

      LOG_INFO("Promoting page %p [idx %lu] with score %f\n", p, promote_idx, scores[promote_idx].score);
      assert(!p->in_dram);

      if (!(p->can_promote)) {
        LOG_DEBUG("Stopping promotion of 0x%lx (score: %.3f (%.3f %.3f))\n",
                 p->va, p->score, p->w[0], p->w[1]);
        promote_idx++;
        continue;
      }

      // try to find a free DRAM page
      np = dequeue_fifo(&dram_free_list);
      if (np != NULL) {
        assert(!(np->present));
        ptimer_stop(&id_timer);

        // Cost-benefit analysis
        float cost = CB_MULTIPLIER * (promotion_cost_avg + demotion_cost_avg);
        float benefit = p->score * p->hot_age * HF_SAMPLE_PERIOD * latency_diff;
        if (benefit < cost) {
          LOG_DEBUG("Stopping promotion of 0x%lx (score: %.3f (%.3f %.3f)) cause of cost-benefit analysis\n",
                   p->va, p->score, p->w[0], p->w[1]);
          enqueue_fifo(&dram_free_list, np);
          break;
        }

        LOG_DEBUG("Promoting freely at %lu: 0x%lx score: %f (%f %f)\n", promote_idx, p->va, p->score, p->w[0], p->w[1]);

        m_req = malloc(sizeof(struct migration_req));
        memset(m_req, 0, sizeof(struct migration_req));
        m_req->nvm_page      = p;
        m_req->free_page     = np;
        m_req->need_demotion = false;

        enqueue_fifo_m(&migration_queue, m_req);

        num_migration_jobs++;
        migrated_bytes += pt_to_pagesize(p->pt);
        migrated_pages++;

        if (num_migration_jobs <= batch_size) {
          // Wake up only as many threads as the batch size
          // This is to avoid waking up all threads and then blocking them
          sem_post(&submission_sem);
        }

        promote_idx++;
        continue;
      }

      // Find the coldest DRAM page that needs to be demoted
      while (demote_idx > promote_idx && !scores[demote_idx].page->in_dram) {
        demote_idx--;
      }
      if (demote_idx <= promote_idx || demote_idx <= (dramsize/PAGE_SIZE)) {
        break;
      }

      cp = scores[demote_idx].page;
      assert(cp->in_dram && cp->va > 0);

      if (!continue_migration(p, cp)) {
        LOG_INFO("Stopping migration at promote_idx %ld\n", promote_idx);
        break;
      }

      // try to find a free NVM page
      np = dequeue_fifo(&nvm_free_list);
      assert(np != NULL);
      ptimer_stop(&id_timer);

      LOG_REPORT("Demoting at %ld: 0x%lx score: %f (%f %f)\n", demote_idx, cp->va, cp->score, cp->w[0], cp->w[1]);
      LOG_REPORT("Promoting at %ld: 0x%lx score: %f (%f %f)\n", promote_idx, p->va, p->score, p->w[0], p->w[1]);

      // move the cold DRAM page to NVM
      m_req = malloc(sizeof(struct migration_req));
      memset(m_req, 0, sizeof(struct migration_req));
      m_req->dram_page     = cp;
      m_req->nvm_page      = p;
      m_req->free_page = np;
      m_req->need_demotion = true;

      enqueue_fifo_m(&migration_queue, m_req);

      num_migration_jobs++;
      migrated_bytes += (2 * pt_to_pagesize(cp->pt));
      migrated_pages += 2;
      promote_idx++;
      demote_idx--;

      if (num_migration_jobs <= batch_size) {
        // Wake up only as many threads as the batch size
        // This is to avoid waking up all threads and then blocking them
        sem_post(&submission_sem);
      }
    }

loop_end:
    ptimer_print(&id_timer);
    ptimer_stop_and_print(&loop_timer);
    ptimer_stop(&remaining_timer);

    LOG_REPORT("Migrated %lu pages (%lu bytes) in this interval\n", migrated_pages, migrated_bytes);
    mig_eff_migrations_since_bw_check += num_migration_jobs;
    if (migrated_pages == 0) {
      // Reset the migration cost averages
      // TOOD: Think about the best way to reset migration costs
      //promotion_cost_avg = promotion_cost_avg * 0.6 + (1-0.6) * MIN_PROMOTION_COST;
      promotion_cost_avg /= MIGRATION_COST_DECAY_RATE;
      demotion_cost_avg  /= MIGRATION_COST_DECAY_RATE;
      if (promotion_cost_avg < MIN_PROMOTION_COST) {
        promotion_cost_avg = MIN_PROMOTION_COST;
      }
      if (demotion_cost_avg < MIN_DEMOTION_COST) {
        demotion_cost_avg = MIN_DEMOTION_COST;
      }
    }

    // Update sampling frequency if there a hot-set change detected
    if (bias == recn_bias && sampling_mode != HIGH_FIDELITY) {
      update_sampling_frequency();
      sampling_mode = HIGH_FIDELITY;
      LOG_REPORT("Switching to HIGH_FIDELITY sampling mode\n");
    } else if (bias == hist_bias && sampling_mode != DEFAULT_SAMPLING) {
      update_sampling_frequency();
      sampling_mode = DEFAULT_SAMPLING;
      LOG_REPORT("Switching to DEFAULT sampling mode\n");
    }

    migrate_time_us = loop_timer.elapsed_us;
    if (migrate_time_us < (1.0 * policy_thread_period)) {
      LOG_INFO("Sleeping for %lu", ((uint64_t)((1.0 * policy_thread_period) - migrate_time_us)));
      usleep((uint64_t)((1.0 * policy_thread_period) - migrate_time_us));
    }
  }

  return NULL;
}

static struct arms_page* pebs_allocate_page()
{
  struct timeval start, end;
  struct arms_page *page;

  gettimeofday(&start, NULL);
  page = dequeue_fifo(&dram_free_list);
  if (page != NULL) {
    assert(page->in_dram);
    assert(!page->present);

    page->present = true;
    //enqueue_fifo(&dram_cold_list, page);

    gettimeofday(&end, NULL);
    LOG_TIME("mem_policy_allocate_page: %f s\n", elapsed(&start, &end));

    return page;
  }

  // DRAM is full, fall back to NVM
  page = dequeue_fifo(&nvm_free_list);
  if (page != NULL) {
    assert(!page->in_dram);
    assert(!page->present);

    page->present = true;
    //enqueue_fifo(&nvm_cold_list, page);

    gettimeofday(&end, NULL);
    LOG_TIME("mem_policy_allocate_page: %f s\n", elapsed(&start, &end));

    return page;
  }

  assert(!"Out of memory");
}

struct arms_page* pebs_pagefault(void)
{
  struct arms_page *page;

  // do the heavy lifting of finding the devdax file offset to place the page
  page = pebs_allocate_page();
  assert(page != NULL);

  return page;
}

void pebs_add_page(struct arms_page *page)
{
  int absent;
  khiter_t key;
  assert(page != NULL);
  LOG_INFO("Adding page %lu to the add_pages_ring [va: %lu]\n", (uint64_t)page, page->va);

  // Add to the hash table
  pthread_mutex_lock(&pages_lock);
  key = kh_put(kPagesMap, pages, page->va, &absent);
  assert(absent);
  kh_value(pages, key) = page;
  pthread_mutex_unlock(&pages_lock);

  // Add to the new pages ring
  pthread_mutex_lock(&mod_page_dq_lock);
  mod_page_t mp = (mod_page_t){ .page = page, .free = false };
  kdq_push(mod_page_t, mod_page_dq, mp);
  pthread_mutex_unlock(&mod_page_dq_lock);
}

struct arms_page* pebs_find_page(uint64_t va)
{
  khiter_t key;
  struct arms_page *page;
  pthread_mutex_lock(&pages_lock);
  key = kh_get(kPagesMap, pages, va);
  page = key == kh_end(pages) ? NULL : kh_value(pages, key);
  pthread_mutex_unlock(&pages_lock);
  return page;
}

void pebs_remove_page(struct arms_page *page)
{
  khiter_t key;
  assert(page != NULL);
  LOG_INFO("Removing page %lu from the add_pages_ring [va: %lu]\n", (uint64_t)page, page->va);

  // Remove page from hash table
  pthread_mutex_lock(&pages_lock);
  key = kh_get(kPagesMap, pages, page->va);
  assert(key != kh_end(pages));
  kh_del(kPagesMap, pages, key);
  pthread_mutex_unlock(&pages_lock);

  pthread_mutex_lock(&mod_page_dq_lock);
  mod_page_t mp = (mod_page_t){ .page = page, .free = true};
  kdq_push(mod_page_t, mod_page_dq, mp);
  pthread_mutex_unlock(&mod_page_dq_lock);

  // We set page->present to false so that
  // the migration thread does not migrate this page
  pthread_mutex_lock(&(page->page_lock));
  page->present = false;
  pthread_mutex_unlock(&(page->page_lock));
}

#ifdef SCAILP
#define L3_LOAD_MISS_LOCAL 0x2d3
#define L3_LOAD_MISS_REMOTE 0x10d3
#elif defined JOSEPM
#define L3_LOAD_MISS_LOCAL 0x1d3
#define L3_LOAD_MISS_REMOTE 0x80d1
#elif defined C220G5
#define L3_LOAD_MISS_LOCAL 0x1d3
#define L3_LOAD_MISS_REMOTE 0x2d3
#endif

void pebs_init(void)
{
  pebs_print_config();

  pthread_t kswapd_thread;
  pthread_t scan_thread;
  pthread_t migration_threads[NUM_MIGRATION_THREADS];

  LOG_INFO("pebs_init: started\n");

  for (int i = 0; i < PEBS_NPROCS; i++) {
#ifdef JOSEPM
    if (i >= 8 && i < 16) {
      continue;
    }
#elif defined C220G5
    if (i >= 10 && i < 20) {
      continue;
    }
#endif
    //perf_page[i][READ] = perf_setup(0x1cd, 0x4, i);  // MEM_TRANS_RETIRED.LOAD_LATENCY_GT_4
    //perf_page[i][READ] = perf_setup(0x81d0, 0, i);   // MEM_INST_RETIRED.ALL_LOADS
    perf_page[i][DRAMREAD] = perf_setup(L3_LOAD_MISS_LOCAL, 0, i, DRAMREAD);      // MEM_LOAD_L3_MISS_RETIRED.LOCAL_DRAM
    perf_page[i][NVMREAD] = perf_setup(L3_LOAD_MISS_REMOTE, 0, i, NVMREAD);     // MEM_LOAD_RETIRED.LOCAL_PMM
    perf_page[i][WRITE] = perf_setup(0x82d0, 0, i, WRITE);    // MEM_INST_RETIRED.ALL_STORES
    //perf_page[i][WRITE] = perf_setup(0x12d0, 0, i);   // MEM_INST_RETIRED.STLB_MISS_STORES
  }

  pthread_mutex_init(&(dram_free_list.list_lock), NULL);
  for (int i = 0; i < dramsize / PAGE_SIZE; i++) {
    struct arms_page *p = calloc(1, sizeof(struct arms_page));
    p->devdax_offset = i * PAGE_SIZE;
    p->present = false;
    p->in_dram = true;
    p->pt = pagesize_to_pt(PAGE_SIZE);
    pthread_mutex_init(&(p->page_lock), NULL);

    enqueue_fifo(&dram_free_list, p);
  }

  pthread_mutex_init(&(nvm_free_list.list_lock), NULL);
  for (int i = 0; i < nvmsize / PAGE_SIZE; i++) {
    struct arms_page *p = calloc(1, sizeof(struct arms_page));
    p->devdax_offset = i * PAGE_SIZE;
    p->present = false;
    p->in_dram = false;
    p->pt = pagesize_to_pt(PAGE_SIZE);
    pthread_mutex_init(&(p->page_lock), NULL);

    enqueue_fifo(&nvm_free_list, p);
  }

  pages = kh_init(kPagesMap);

  #ifdef SPATIAL_SMOOTHING
  pages_tree = kb_init(kPagesTree, KB_DEFAULT_SIZE);
  #else
  pages_map = kh_init(kPagesMap);
  #endif

  scores = (struct score_entry*)malloc((MAX_NVME_PAGES + MAX_DRAM_PAGES) * sizeof(struct score_entry));

  // Initialize the free/add ring buffers
  mod_page_dq = kdq_init(mod_page_t);

  // Initialize the neighbour ring buffers
#ifdef SPATIAL_SMOOTHING
  buffer = (uint64_t**)malloc(sizeof(uint64_t*) * (NUM_NEIGHBOURS + 2));
  assert(buffer);
  l_neighbours = ring_buf_init(buffer, NUM_NEIGHBOURS + 2);
  buffer = (uint64_t**)malloc(sizeof(uint64_t*) * (NUM_NEIGHBOURS + 2));
  assert(buffer);
  r_neighbours = ring_buf_init(buffer, NUM_NEIGHBOURS + 2);
#endif

  // Initialize bias values
  for (int i = 0; i < WINDOW_SIZE; i++) {
    LOG_REPORT("w_ewma_alpha[%d] = %f\n", i, w_ewma_alpha[i]);
  }
  for (int i = 0; i < WINDOW_SIZE; i++) {
    LOG_REPORT("hist_bias[%d] = %f\n", i, hist_bias[i]);
  }
  for (int i = 0; i < WINDOW_SIZE; i++) {
    LOG_REPORT("recn_bias[%d] = %f\n", i, recn_bias[i]);
  }

  // Start the policy and scan threads
  int r = pthread_create(&scan_thread, NULL, pebs_scan_thread, NULL);
  assert(r == 0);

  r = pthread_create(&kswapd_thread, NULL, pebs_policy_thread, NULL);
  assert(r == 0);

  for (int i = 0; i < NUM_MIGRATION_THREADS; i++) {
    r = pthread_create(&migration_threads[i], NULL, pebs_migration_thread, NULL);
    assert(r == 0);
  }
  sem_init(&submission_sem, 0, 0);
  sem_init(&completion_sem, 0, 0);
  pthread_mutex_init(&migration_queue.list_lock, NULL);

  if ((dramsize+nvmsize) < (32*1024*1024*1024UL)) {
    policy_thread_period = PEBS_KSWAPD_INTERVAL_SMALL;
  } else {
    policy_thread_period = PEBS_KSWAPD_INTERVAL_BIG;
  }

  LOG_INFO("Memory management policy is PEBS\n");
  LOG_INFO("pebs_init: finished\n");
}

void pebs_shutdown()
{
  for (int i = 0; i < PEBS_NPROCS; i++) {
    for (int j = 0; j < NPBUFTYPES; j++) {
      ioctl(pfd[i][j], PERF_EVENT_IOC_DISABLE, 0);
      //munmap(perf_page[i][j], sysconf(_SC_PAGESIZE) * PERF_PAGES);
    }
  }
}

void pebs_stats()
{
  //LOG_STATS("dram_hot_list:[%ld] dram_cold_list:[%ld] nvm_hot_list:[%ld] nvm_cold_list:[%ld] samples:[%ld/%ld] throttle/unthrottle_cnt:[%ld/%ld] cools:[%ld]\n",
  LOG_STATS("samples:[%ld/%ld] throttle/unthrottle_cnt:[%ld/%ld] cools:[%ld]\n",
          //dram_hot_list.numentries,
          //dram_cold_list.numentries,
          //nvm_hot_list.numentries,
          //nvm_cold_list.numentries,
          arms_pages_cnt,
          total_pages_cnt,
          throttle_cnt,
          unthrottle_cnt,
          cools);
  LOG_STATS("mig_eff: violations:[%lu/%lu] baseline_var:[%.3f] gain_per_mig:[%.3f] calibrated:[%d]\n",
          mig_eff_violations, mig_eff_checks,
          mig_eff_baseline_bw_var, mig_eff_gain_per_migration, mig_eff_calibrated);
  // arms_pages_cnt = total_pages_cnt =  throttle_cnt = unthrottle_cnt = 0;
}

void pebs_print_config()
{
  LOG_REPORT("PEBS configuration:\n");
  LOG_REPORT("  =========================================\n");
  LOG_REPORT("  NUM_MIGRATION_THREADS: %d\n", NUM_MIGRATION_THREADS);
  LOG_REPORT("  PEBS_NPROCS: %d\n", PEBS_NPROCS);
  LOG_REPORT("  NVM_RD_BW_KNEE: %d\n", NVM_RD_BW_KNEE);
  LOG_REPORT("  NVM_WR_BW_KNEE: %d\n", NVM_WR_BW_KNEE);
  LOG_REPORT("  NVM_BW_SLOPE: %f\n", NVM_BW_SLOPE);
  LOG_REPORT("  NVM_WRITES_WEIGHT: %d\n", NVM_WRITES_WEIGHT);
  LOG_REPORT("  MIN_PROMOTION_COST: %ld\n", MIN_PROMOTION_COST);
  LOG_REPORT("  MIN_DEMOTION_COST: %ld\n", MIN_DEMOTION_COST);
  LOG_REPORT("  =========================================\n");
  LOG_REPORT("  PEBS_KSWAPD_INTERVAL_BIG: %d\n", PEBS_KSWAPD_INTERVAL_BIG);
  LOG_REPORT("  PEBS_KSWAPD_INTERVAL_SMALL: %d\n", PEBS_KSWAPD_INTERVAL_SMALL);
  LOG_REPORT("  =========================================\n");
  LOG_REPORT("  WINDOW_SIZE: %d\n", WINDOW_SIZE);
  LOG_REPORT("  HIST_BIAS: {%f, %f}\n", hist_bias[0], hist_bias[1]);
  LOG_REPORT("  RECN_BIAS: {%f, %f}\n", recn_bias[0], recn_bias[1]);
  LOG_REPORT("  SHORT_TERM_WND_PERIOD_MS: %d\n", SHORT_TERM_WND_PERIOD_MS);
  LOG_REPORT("  LONG_TERM_WND_PERIOD_MS: %d\n", LONG_TERM_WND_PERIOD_MS);
  LOG_REPORT("  W_EWMA_ALPHA: {%f, %f}\n", w_ewma_alpha[0], w_ewma_alpha[1]);
  LOG_REPORT("  =========================================\n");
  LOG_REPORT("  HCD_EWMA_ALPHA: %f\n", HCD_EWMA_ALPHA);
  LOG_REPORT("  HCD_STD_ALPHA: %f\n", HCD_STD_ALPHA);
  LOG_REPORT("  HCD_RECN_MAX_PERIODS: %d\n", HCD_RECN_MAX_PERIODS);
  LOG_REPORT("  HCD_RECN_MIN_NVM_BW: %f\n", HCD_RECN_MIN_NVM_BW);
  LOG_REPORT("  HCD_PH_DRIFT: %f\n", HCD_PH_DRIFT);
  LOG_REPORT("  HCD_PH_THRESHOLD: %f\n", HCD_PH_THRESHOLD);
  LOG_REPORT("  =========================================\n");
  LOG_REPORT("  CB_MULTIPLIER: %f\n", CB_MULTIPLIER);
  LOG_REPORT("  MIGRATION_COST_DECAY_RATE: %f\n", MIGRATION_COST_DECAY_RATE);
  LOG_REPORT("  MIGRATION_WINDOW_SIZE: %d\n", MIGRATION_WINDOW_SIZE);
  LOG_REPORT("  MIGRATION_COST_ALPHA: %f\n", MIGRATION_COST_ALPHA);
  LOG_REPORT("  =========================================\n");
  LOG_REPORT("  DEFAULT_SAMPLE_PERIOD: %d\n", DEFAULT_SAMPLE_PERIOD);
  LOG_REPORT("  HF_SAMPLE_PERIOD: %d\n", HF_SAMPLE_PERIOD);
  LOG_REPORT("  =========================================\n");
  LOG_REPORT("  MIG_EFF_BW_VAR_ALPHA: %f\n", MIG_EFF_BW_VAR_ALPHA);
  LOG_REPORT("  MIG_EFF_GAIN_ALPHA: %f\n", MIG_EFF_GAIN_ALPHA);
  LOG_REPORT("  MIG_EFF_THRESHOLD: %f\n", MIG_EFF_THRESHOLD);
  LOG_REPORT("  MIG_EFF_MIN_MIGRATIONS: %d\n", MIG_EFF_MIN_MIGRATIONS);
  LOG_REPORT("  =========================================\n");
}