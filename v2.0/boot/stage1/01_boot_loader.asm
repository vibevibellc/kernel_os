%ifndef STAGE2_SECTORS
%define STAGE2_SECTORS 32
%endif

%define STAGE2_ADDR    0x8000
%define STAGE2_SEGMENT 0x0800

    jmp short boot_start
    nop
    db "KV2BOOT "
    times 59 - ($ - $$) db 0

boot_start:
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7c00
    sti

    mov [boot_drive], dl

    mov si, msg_loading
    call print_string

    mov ah, 0x42
    mov dl, [boot_drive]
    mov si, disk_packet
    int 0x13
    jc disk_error

    mov si, msg_jump
    call print_string
    jmp 0x0000:STAGE2_ADDR

disk_error:
    mov si, msg_disk_error
    call print_string
    cli
    hlt
    jmp $

print_string:
    lodsb
    test al, al
    jz .done
    call print_char
    jmp print_string
.done:
    ret

print_char:
    push ax
    push bx
    mov ah, 0x0e
    mov bh, 0x00
    mov bl, 0x07
    int 0x10
    pop bx
    pop ax
    ret

msg_loading db "v2 stage1: loading stage2", 13, 10, 0
msg_jump db "v2 stage1: jumping", 13, 10, 0
msg_disk_error db "v2 stage1: disk read failed", 13, 10, 0

boot_drive db 0

disk_packet:
    db 0x10, 0x00
    dw STAGE2_SECTORS
    dw 0x0000
    dw STAGE2_SEGMENT
    dd 0x00000001
    dd 0x00000000

times 510 - ($ - $$) db 0
dw 0xaa55
