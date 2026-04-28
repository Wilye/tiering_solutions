# Tiering Solutions - ARMS Branch

This branch contains the source of Linux and the shim library of ARMS (Adaptive and Robust Memory Tiering System). The paper is currently on ArXiv (https://www.arxiv.org/abs/2508.04417).


## Building Linux and the userspace library

If you are running ARMS on c220g5 (Cloudlab) using the ARMS profile, then skip the building instructions below and jump right into the running instructions at the end.

# Building Linux

Start by cloning the repo and its submodules.

```bash
git clone https://github.com/SujayYadalam94/tiering_solutions.git
git checkout arms_c220g5
git submodule update --init --recursive
```

You could follow your own approach to build Linux kernel or use the steps below:

Install dependencies required to build Linux.

```bash
sudo apt update
sudo apt-get install -y git fakeroot build-essential ncurses-dev xz-utils libssl-dev bc flex libelf-dev bison numactl htop tree cgroup-tools libtraceevent-dev pkg-config msr-tools ndctl
```

TODO: Applying patch.

We enable kernel flags to reserve memory during bootup and expose them as `/dev/dax` files which ARMS uses to allocate pages to applications. 

```bash
cd linux

cp /boot/config-$(uname -r) .config
scripts/config --disable SYSTEM_REVOCATION_KEYS

echo 'CONFIG_MEMORY_HOTPLUG=y' >> .config
echo 'CONFIG_BLK_DEV_PMEM=m' >> .config
echo 'CONFIG_NVDIMM_PFN=y' >> .config
echo 'CONFIG_NVDIMM_DAX=y' >> .config
echo 'CONFIG_FS_DAX=y' >> .config
echo 'CONFIG_DAX=y' >> .config
echo 'CONFIG_DEV_DAX=y' >> .config
echo 'CONFIG_DEV_DAX_PMEM=y' >> .config
echo 'CONFIG_DEV_DAX_KMEM=y' >> .config
echo 'CONFIG_X86_MSR=y' >> .config
```

Build Linux.

```bash
yes '' | make localmodconfig
make -j$(nproc)
sudo make modules_install -j$(nproc)
sudo make install
```

Reboot the system into the desired kernel:

```bash
sudo grub-reboot "Advanced options for Ubuntu>Ubuntu, with Linux 5.1.0-rc4+"
```

# Building the userspace shim library

```bash
cd src
make
```

## Setting up the dax devices

Similar to HeMem, ARMS uses `/dev/dax` files to represent fast tier (DRAM) and slow tier (NVM/CXL). We emulate CXL using remote NUMA memory.

To set up the `/dev/dax` files, follow the instructions [here](https://pmem.io/blog/2016/02/how-to-emulate-persistent-memory/) in order to reserve a block of DRAM at machine startup. If you are using remote NUMA memory to emulate CXL, then make sure to reserve a block of memory from the remote node as well.

On the c220g5 in Cloudlab, we use:
```bash
memmap=64G!4G,64G!104G
```
 Do not follow the last set of instructions from pmem.io on setting up a file system on the reserved DRAM. Instead, set up a /dev/dax file to represent it:

1. First, determine the name of the namespace representing the reserved DRAM:

ndctl list --human

2. You should see your reserved DRAM. If multiple namespaces are listed, some represent NVM namespaces (described below). You should be able to differentiate the DRAM namespace based on size. Your DRAM namespace is likely in fsdax mode. Change the namespace over to devdax mode using the following command (in this example, the DRAM namespace is called namespace0.0):

```bash
sudo ndctl create-namespace -f -e namespace0.0 --mode=devdax --align 2M
```

3. Make note of the chardev name of the DRAM /dev/dax file. This will be used to tell HeMem which /dev/dax file represents DRAM. If this is different from dax0.0, then you will need to set the environment variable DRAMPATH to your actual DRAM /dev/dax file.

If you are using NUMA as the slow tier, you will need to change the mode of the remote memory to devdax as well.

```bash
sudo ndctl create-namespace -f -e namespace1.0 --mode=devdax --align 2M
```

Otherwise, if you are using NVM as the slow tier, ensure that your machine has NVM in App Direct mode. If you do not already have namespaces representing NVM, then you will need to create them. Follow these steps:

1. List the regions available on your machine:

```bash
ndctl list --regions --human
```

2. Note which regions represent NVM. You can differentiate them from the reserved DRAM region based on size or via the persistence_domain field, which, for NVM, will read memory_controller. Pick the region that is on the same NUMA node as your reserved DRAM. In this example, this is "region1". Create a namespace over this region:

```bash
ndctl create-namespace --region=1 --mode=devdax
```

3. Make note of the chardev name of the NVM /dev/dax file. This will be used to tell HeMem which /dev/dax file represents NVM. If this is different from dax1.0, then you will need to set the environment variable NVMPATH to your actual DRAM /dev/dax file.



## Running

If you want to increase/decrease the remote NUMA memory access latency, you can change the offcore frequency:

```bash
sudo modprobe msr
sudo wrmsr --processor 10 0x620 0x707
```

Running applications with ARMS is as simple as this:

```bash
sudo LD_PRELOAD=/path/to/arms/src/libarms.so -- ./app
```

If you want to restrict the size of fast tier and slow tier, use `DRAMSIZE` and `NVMSIZE` environment variables.

```bash
sudo LD_PRELOAD=/path/to/arms/src/libarms.so DRAMSIZE=$((32*1024*1024*1024)) NVMSIZE=$((32*1024*1024*1024)) -- ./app
```

Further, make sure your application is running on the correct NUMA node if you are using NUMA to emulate CXL:

```bash
numactl -N0 sudo LD_PRELOAD=/path/to/arms/src/libarms.so DRAMSIZE=$((32*1024*1024*1024)) NVMSIZE=$((32*1024*1024*1024)) -- ./app
```


