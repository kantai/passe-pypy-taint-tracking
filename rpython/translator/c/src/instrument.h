#ifndef _PYPY_INSTRUMENT_H
#define _PYPY_INSTRUMENT_H

void instrument_setup();

#ifdef PYPY_INSTRUMENT
void instrument_count(long);
#define PYPY_INSTRUMENT_COUNT(label) instrument_count(label)
#else
#define PYPY_INSTRUMENT_COUNT
#endif

#endif  /* _PYPY_INSTRUMENT_H */ 
