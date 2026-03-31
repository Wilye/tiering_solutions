CC = gcc
CFLAGS = -g -Wall -O3 -fPIC
#CFLAGS = -g3 -Wall -O0 -fPIC
LDFLAGS = -shared
INCLUDES = -I../linux/usr/include/
LIBS = -lm -lpthread
ARMS_LIBS = $(LIBS) -ldl -lsyscall_intercept -L../Hoard/src -lhoard

default: libarms.so

all: arms-libs

arms-libs: libarms-lru.so libarms-simple.so libarms-lru-swap.so libarms.so

libarms.so: arms.o pebs.o timer.o interpose.o fifo.o spsc-ring.o
	$(CC) $(LDFLAGS) -o libarms.so arms.o timer.o interpose.o pebs.o fifo.o spsc-ring.o $(ARMS_LIBS)

libarms-lru.so: policies/arms-lru.o policies/lru.o timer.o interpose.o policies/paging.o fifo.o spsc-ring.o
	$(CC) $(LDFLAGS) -o libarms-lru.so policies/arms-lru.o timer.o policies/lru.o interpose.o policies/paging.o fifo.o spsc-ring.o $(ARMS_LIBS)

libarms-simple.so: policies/arms-simple.o policies/simple.o timer.o interpose.o policies/paging.o fifo.o spsc-ring.o
	$(CC) $(LDFLAGS) -o libarms-simple.so policies/arms-simple.o timer.o policies/simple.o interpose.o policies/paging.o fifo.o spsc-ring.o $(ARMS_LIBS)

libarms-lru-swap.so: policies/arms-lru-swap.o policies/lru_swap.o timer.o interpose.o policies/paging.o fifo.o spsc-ring.o
	$(CC) $(LDFLAGS) -o libarms-lru-swap.so policies/arms-lru-swap.o timer.o policies/lru_swap.o interpose.o policies/paging.o fifo.o spsc-ring.o $(ARMS_LIBS)

arms.o: arms.c arms.h pebs.h interpose.h fifo.h spsc-ring.h
	$(CC) $(CFLAGS) $(INCLUDES) -D ALLOC_ARMS -c arms.c -o arms.o
	
policies/arms-lru.o: arms.c arms.h policies/lru.h interpose.h policies/paging.h fifo.h spsc-ring.h
	$(CC) $(CFLAGS) $(INCLUDES) -D ALLOC_LRU -c arms.c -o policies/arms-lru.o

policies/arms-simple.o: arms.c arms.h policies/simple.h interpose.h policies/paging.h fifo.h spsc-ring.h
	$(CC) $(CFLAGS) $(INCLUDES) -D ALLOC_SIMPLE -c arms.c -o policies/arms-simple.o

policies/arms-lru-swap.o: arms.c arms.h policies/lru.h interpose.h policies/paging.h fifo.h spsc-ring.h
	$(CC) $(CFLAGS) $(INCLUDES) -D ALLOC_LRU -D LRU_SWAP -c arms.c -o policies/arms-lru-swap.o

interpose.o: interpose.c interpose.h arms.h
	$(CC) $(CFLAGS) $(INCLUDES) -c interpose.c

timer.o: timer.c timer.h
	$(CC) $(CFLAGS) $(INCLUDES) -c timer.c

policies/lru.o: policies/lru.c policies/lru.h arms.h fifo.h spsc-ring.h
	$(CC) $(CFLAGS) $(INCLUDES) -D ALLOC_LRU -c policies/lru.c -o policies/lru.o

policies/simple.o: policies/simple.c policies/simple.h arms.h spsc-ring.h
	$(CC) $(CFLAGS) $(INCLUDES) -c policies/simple.c -o policies/simple.o

policies/lru_swap.o: policies/lru.c policies/lru.h arms.h fifo.h spsc-ring.h
	$(CC) $(CFLAGS) $(INCLUDES) -D LRU_SWAP -D ALLOC_LRU -c policies/lru.c -o policies/lru_swap.o

policies/paging.o: policies/paging.c policies/paging.h
	$(CC) $(CFLAGS) $(INCLUDES) -c policies/paging.c -o policies/paging.o

pebs.o: pebs.c pebs.h arms.h fifo.h
	$(CC) $(CFLAGS) $(INCLUDES) -c pebs.c

fifo.o: fifo.c fifo.h arms.h
	$(CC) $(CFLAGS) $(INCLUDES) -c fifo.c

spsc-ring.o: spsc-ring.c spsc-ring.h
	$(CC) $(CFLAGS) $(INCLUDES) -c spsc-ring.c

no-guardrails: clean
	$(MAKE) CFLAGS="$(CFLAGS) -DDISABLE_MIG_EFF_GUARDRAIL -DDISABLE_HOTNESS_SCORE_GUARDRAIL"

no-cba: clean
	$(MAKE) CFLAGS="$(CFLAGS) -DDISABLE_COST_BENEFIT"

clean:
	$(RM) *.o *.so policies/*.o
