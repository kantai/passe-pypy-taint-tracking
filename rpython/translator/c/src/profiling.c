#include <stddef.h>
#if defined(__GNUC__) && defined(__linux__)

/* Linux GCC implementation */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#include <sched.h>
#endif

static cpu_set_t base_cpu_set;
static int profiling_setup = 0;

void pypy_setup_profiling()
{
  if (!profiling_setup) {
    cpu_set_t set;
    sched_getaffinity(0, sizeof(cpu_set_t), &base_cpu_set);
    CPU_ZERO(&set);
    CPU_SET(0, &set);   /* restrict to a single cpu */
    sched_setaffinity(0, sizeof(cpu_set_t), &set);
    profiling_setup = 1;
  }
}

void pypy_teardown_profiling()
{
  if (profiling_setup) {
    sched_setaffinity(0, sizeof(cpu_set_t), &base_cpu_set);
    profiling_setup = 0;
  }
}

#elif defined(_WIN32)

/* Windows implementation */

#include <windows.h>

static DWORD_PTR base_affinity_mask;
static int profiling_setup = 0;

void pypy_setup_profiling() { 
    if (!profiling_setup) {
        DWORD_PTR affinity_mask, system_affinity_mask;
        GetProcessAffinityMask(GetCurrentProcess(),
            &base_affinity_mask, &system_affinity_mask);
        affinity_mask = 1;
        /* Pick one cpu allowed by the system */
        if (system_affinity_mask)
            while ((affinity_mask & system_affinity_mask) == 0)
                affinity_mask <<= 1;
        SetProcessAffinityMask(GetCurrentProcess(), affinity_mask);
        profiling_setup = 1;
    }
}

void pypy_teardown_profiling() {
    if (profiling_setup) {
        SetProcessAffinityMask(GetCurrentProcess(), base_affinity_mask);
        profiling_setup = 0;
    }
}

#else

/* Empty implementations for other platforms */
void pypy_setup_profiling() { }
void pypy_teardown_profiling() { }

#endif
