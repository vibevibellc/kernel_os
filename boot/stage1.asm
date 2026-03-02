[bits 16]
[org 0x7c00]

%define STAGE2_ADDR    0x8000
%define STAGE2_SECTORS 62
%define COM1_PORT      0x3f8

    jmp short boot_start
    nop
    db "KERNBOOT"
    times 59 - ($ - $$) db 0

boot_start:
    jmp 0x0000:flush_cs

flush_cs:
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7c00
    sti

    mov [boot_drive], dl

    call serial_init
    mov si, msg_stage1
    call print_string

    mov di, 3

load_stage2:
.retry:
    xor ah, ah
    mov dl, [boot_drive]
    int 0x13
    jc .next_try

    mov ah, 0x02
    mov al, STAGE2_SECTORS
    mov ch, 0x00
    mov cl, 0x02
    mov dh, 0x00
    mov dl, [boot_drive]
    mov bx, STAGE2_ADDR
    int 0x13
    jnc .success

.next_try:
    dec di
    jnz .retry
    jmp disk_error

.success:
    mov si, msg_jump
    call print_string
    jmp 0x0000:STAGE2_ADDR

disk_error:
    mov si, msg_disk_error
    call print_string
    cli
    hlt
    jmp $

serial_init:
    mov dx, COM1_PORT + 1
    xor al, al
    out dx, al

    mov dx, COM1_PORT + 3
    mov al, 0x80
    out dx, al

    mov dx, COM1_PORT + 0
    mov al, 0x03
    out dx, al

    mov dx, COM1_PORT + 1
    xor al, al
    out dx, al

    mov dx, COM1_PORT + 3
    mov al, 0x03
    out dx, al

    mov dx, COM1_PORT + 2
    mov al, 0xc7
    out dx, al

    mov dx, COM1_PORT + 4
    mov al, 0x0b
    out dx, al
    ret

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
    push cx
    push dx
    mov ah, 0x0e
    mov bh, 0x00
    mov bl, 0x07
    int 0x10
    pop dx
    pop cx
    pop bx
    pop ax
    call serial_write
    ret

serial_write:
    push ax
    push dx
.wait:
    mov dx, COM1_PORT + 5
    in al, dx
    test al, 0x20
    jz .wait
    pop dx
    pop ax
    mov dx, COM1_PORT
    out dx, al
    ret

msg_stage1 db "stage1: boot sector running", 13, 10, 0
msg_jump db "stage1: loading stage2", 13, 10, 0
msg_disk_error db "stage1: disk read failed", 13, 10, 0
boot_drive db 0

times 510 - ($ - $$) db 0
dw 0xaa55
