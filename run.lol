mkdir -p vm
test -f vm/os-disk.img || qemu-img create -f raw vm/os-disk.img 8G
dd if=/dev/zero of=vm/os-disk.img bs=512 count=64 conv=notrunc
64+0 records in
64+0 records out
32768 bytes transferred in 0.000233 secs (140635193 bytes/sec)
dd if=build/stage1.bin of=vm/os-disk.img bs=512 count=1 conv=notrunc
1+0 records in
1+0 records out
512 bytes transferred in 0.000038 secs (13473684 bytes/sec)
dd if=build/stage2.bin of=vm/os-disk.img bs=512 seek=1 conv=notrunc
25+1 records in
25+1 records out
13017 bytes transferred in 0.000078 secs (166884615 bytes/sec)
MEMORY=512M QEMU_BIN=qemu-system-x86_64 ./run-vm.sh
stage1: boot sector running
stage1: loading stage2
stage2: command monitor ready
help, hardware_list, memory_map, calc, chat, curl, hostreq, task_spawn, task_list, task_retire, task_step, graph, paint, edit, peek, clear, about, halt, reboot

generation 0x00000001
kernel_os> qemu-system-x86_64: terminating on signal 2 from pid 6247 (<unknown process>)
