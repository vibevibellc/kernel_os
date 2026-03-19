%define COM1_PORT        0x3f8
%define INPUT_MAX        4095
%define SERIAL_LINE_MAX  511
%define PS2_DATA         0x60
%define PS2_STATUS       0x64
%define EDITOR_CAPACITY  10240
%define TASK_SLOT_COUNT  4
%define TASK_NAME_SIZE   16
%define TASK_GOAL_SIZE   160
%define CHAT_SESSION_SIZE 16
%define HOST_ACTION_SIZE 24
%define PATCH_MAX_BYTES  0x0200
%define PEEK_MAX_BYTES   0x0C80
%define STREAM_MAX_BYTES 0x01F0
%define NAV_NEEDLE_MAX   128
%define NAV_TEXT_WINDOW  0x0040
%define NAV_HEX_WINDOW   0x0010
%define NAV_SOURCE_NONE  0
%define NAV_SOURCE_EDITOR 1
%define NAV_SOURCE_MEMORY 2
%define NAV_RENDER_NONE  0
%define NAV_RENDER_TEXT  1
%define NAV_RENDER_HEX   2
%define PM32_CODE_SEL    0x08
%define PM32_DATA_SEL    0x10
%define PM16_CODE_SEL    0x18
%define PM16_DATA_SEL    0x20
%define PM32_STACK_TOP   0x7000
%define LOW_BIOS_RESERVED_END 0x00001000
%define LOW_MEMORY_LIMIT 0x00100000
%define SAFE_RANGE_MAX   8
%define CHAT_LOOP_MAX_STEPS 8
%define RAMLIST_NODE_COUNT 16
%define KERNEL_RUNTIME_UNKNOWN 0
%define KERNEL_RUNTIME_LATENT  1
%define KERNEL_RUNTIME_BUSY    2

start:
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7a00
    sti

    call serial_init
    call set_text_mode

    mov si, msg_banner
    call print_string
    mov si, msg_hint
    call print_string
    call announce_generation

main_loop:
    call kernel_runtime_set_latent
    call show_prompt
    mov di, input_buffer
    mov cx, INPUT_MAX
    call read_line
    cmp byte [input_buffer], 0
    je main_loop
    call kernel_runtime_set_busy
    call dispatch_command
    cmp byte [monitor_auto_clear], 1
    jne .skip_clear
    call clear_console
.skip_clear:
    call do_help
    jmp main_loop

dispatch_command:
    push bx
    mov bx, command_table

.next:
    mov di, [bx]
    test di, di
    jz .unknown
    mov si, input_buffer
    call streq
    cmp al, 1
    je .run
    add bx, 4
    jmp .next

.run:
    mov dx, [bx + 2]
    pop bx
    call dx
    mov al, 1
    ret

.unknown:
    pop bx
    mov si, msg_unknown
    call print_string
    xor al, al
    ret

do_help:
    mov si, msg_help
    call print_string
    ret

do_hardware_list:
    call hardware_list
    ret

do_memory_map:
    call memory_map
    ret

do_calc:
    call calculator_program
    ret

do_chat:
    call chat_program
    ret

do_curl:
    call curl_program
    ret

do_hostreq:
    call hostreq_program
    ret

do_task_spawn:
    call task_spawn_program
    ret

do_task_list:
    call task_list_program
    ret

do_task_retire:
    call task_retire_program
    ret

do_task_step:
    call task_step_program
    ret

do_ramlist:
    call ramlist_program
    ret

do_edit:
    call editor_program
    ret

do_grep:
    call grep_program
    ret

do_peek:
    call peek_program
    ret

do_search:
    call search_program
    ret

do_next:
    call next_program
    ret

do_prev:
    call prev_program
    ret

do_forward:
    call forward_program
    ret

do_back:
    call back_program
    ret

do_view:
    call view_program
    ret

do_pm32:
    call protected_mode_program
    ret

do_screen:
    call screen_program
    ret

clear_console:
    call set_text_mode
    ret

do_halt:
    mov si, msg_halt
    call print_string
.halt_loop:
    cli
    hlt
    jmp .halt_loop

do_reboot:
    mov si, msg_reboot
    call print_string
    int 0x19
    jmp $

show_prompt:
    mov si, prompt
    call print_string
    ret

read_line:
    push bx
    xor bx, bx

.next_char:
    call read_input_char
    cmp al, 0x0d
    je .done
    cmp al, 0x08
    je .backspace
    cmp al, 0x7f
    je .backspace
    cmp al, 32
    jb .next_char
    cmp bx, cx
    jae .next_char
    mov [di], al
    inc di
    inc bx
    mov byte [di], 0
    call print_char
    jmp .next_char

.backspace:
    test bx, bx
    jz .next_char
    dec di
    dec bx
    mov byte [di], 0
    mov al, 0x08
    call print_char
    mov al, ' '
    call print_char
    mov al, 0x08
    call print_char
    jmp .next_char

.done:
    mov byte [di], 0
    mov si, newline
    call print_string
    pop bx
    ret

read_input_char:
.poll:
    call poll_input_char
    test al, al
    jz .poll
    ret

poll_input_char:
    push bx
    push cx
    push dx
    push si
    push di
    push ds
    push es

    mov ah, 0x01
    int 0x16
    jnz .keyboard_ready

    mov dx, COM1_PORT + 5
    in al, dx
    test al, 0x01
    jz .none

    mov dx, COM1_PORT
    in al, dx
    cmp al, 0x0a
    je .return_enter
    cmp al, 0x0d
    je .return_enter
    jmp .done

.keyboard_ready:
    xor ah, ah
    int 0x16
    call keyboard_translate_key
    test al, al
    jnz .done

.none:
    xor al, al
    jmp .done

.return_enter:
    mov al, 0x0d

.done:
    pop es
    pop ds
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    ret

keyboard_translate_key:
    push bx
    push dx

    mov dl, al
    xor bh, bh
    mov bl, ah
    cmp bl, 0x80
    jae .fallback

    mov ah, 0x02
    int 0x16
    test al, 0x03
    jz .unshifted
    mov al, [keymap_shifted + bx]
    jmp .mapped

.unshifted:
    mov al, [keymap_unshifted + bx]

.mapped:
    test al, al
    jnz .done

.fallback:
    mov al, dl

.done:
    pop dx
    pop bx
    ret

set_text_mode:
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push ds
    push es
    mov ah, 0x0f
    int 0x10
    cmp al, 0x03
    jne .reset
    cmp byte [text_console_ready], 1
    jne .reset
    jmp .refresh

.reset:
    mov ax, 0x0003
    int 0x10
    mov ax, 0x1112
    xor bx, bx
    int 0x10
    mov byte [text_console_ready], 1

.refresh:
    call refresh_text_console_metrics
    call clear_text_screen
    pop es
    pop ds
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    ret

set_graphics_mode:
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push ds
    push es
    mov ax, 0x0013
    int 0x10
    pop es
    pop ds
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    ret

refresh_text_console_metrics:
    push ax
    push bx
    push es

    mov ah, 0x0f
    int 0x10
    mov [hardware_video_mode], al
    mov [hardware_video_cols], ah
    mov [hardware_video_page], bh

    mov ax, 0x0040
    mov es, ax
    mov al, [es:0x84]
    test al, al
    jnz .have_rows_minus_one
    mov al, 24

.have_rows_minus_one:
    inc al
    mov [hardware_video_rows], al
    cmp byte [hardware_video_cols], 0
    jne .done
    mov byte [hardware_video_cols], 80

.done:
    pop es
    pop bx
    pop ax
    ret

clear_text_screen:
    push ax
    push bx
    push cx
    push dx

    xor cx, cx
    xor ax, ax
    mov ah, 0x06
    mov bh, 0x07
    mov dl, [hardware_video_cols]
    test dl, dl
    jnz .have_cols
    mov dl, 80

.have_cols:
    dec dl
    mov dh, [hardware_video_rows]
    test dh, dh
    jnz .have_rows
    mov dh, 25

.have_rows:
    dec dh
    int 0x10

    mov ah, 0x02
    mov bh, [hardware_video_page]
    xor dx, dx
    int 0x10

    pop dx
    pop cx
    pop bx
    pop ax
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
    push si
    push di
    push bp
    push ds
    push es
    mov ah, 0x0e
    mov bh, 0x00
    mov bl, 0x07
    int 0x10
    pop es
    pop ds
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    pop ax
    call serial_write
    ret

serial_init:
    mov dx, COM1_PORT + 1
    xor al, al
    out dx, al

    mov dx, COM1_PORT + 3
    mov al, 0x80
    out dx, al

    mov dx, COM1_PORT + 0
    mov al, 0x01
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

serial_write_string:
    lodsb
    test al, al
    jz .done
    call serial_write
    jmp serial_write_string
.done:
    ret

kernel_runtime_set_latent:
    mov al, KERNEL_RUNTIME_LATENT
    jmp kernel_runtime_set_state

kernel_runtime_set_busy:
    mov al, KERNEL_RUNTIME_BUSY
    jmp kernel_runtime_set_state

kernel_runtime_set_state:
    cmp byte [kernel_runtime_state], al
    je .done
    mov byte [kernel_runtime_state], al
    push ax
    push si
    cmp al, KERNEL_RUNTIME_LATENT
    jne .busy
    mov si, msg_kernel_runtime_latent
    call serial_write_string
    jmp .emit_done

.busy:
    mov si, msg_kernel_runtime_busy
    call serial_write_string

.emit_done:
    pop si
    pop ax

.done:
    ret

serial_write_json_escaped:
    lodsb
    test al, al
    jz .done
    cmp al, '"'
    je .escape
    cmp al, '\'
    je .escape
    cmp al, 32
    jb .space
    call serial_write
    jmp serial_write_json_escaped

.escape:
    push ax
    mov al, '\'
    call serial_write
    pop ax
    call serial_write
    jmp serial_write_json_escaped

.space:
    mov al, ' '
    call serial_write
    jmp serial_write_json_escaped

.done:
    ret

buffer_write_string:
    lodsb
    test al, al
    jz .done
    mov [di], al
    inc di
    jmp buffer_write_string
.done:
    ret

buffer_write_json_escaped:
    lodsb
    test al, al
    jz .done
    cmp al, '"'
    je .escape
    cmp al, '\'
    je .escape
    cmp al, 32
    jb .space
    mov [di], al
    inc di
    jmp buffer_write_json_escaped

.escape:
    mov byte [di], '\'
    inc di
    mov [di], al
    inc di
    jmp buffer_write_json_escaped

.space:
    mov byte [di], ' '
    inc di
    jmp buffer_write_json_escaped

.done:
    ret

write_hex32_buffer_eax:
    push ax
    push bx
    push cx
    push dx
    mov cx, 8

.loop:
    rol eax, 4
    mov dl, al
    and dl, 0x0f
    xor bx, bx
    mov bl, dl
    mov al, [hex_digits + bx]
    mov [di], al
    inc di
    loop .loop

    pop dx
    pop cx
    pop bx
    pop ax
    ret

buffer_write_generation_field:
    push si
    push eax
    mov si, msg_generation_json_prefix
    call buffer_write_string
    mov eax, [generation]
    call write_hex32_buffer_eax
    mov si, msg_generation_json_suffix
    call buffer_write_string
    pop eax
    pop si
    ret

serial_write_buffer:
    push si
    mov si, host_request_buffer
    call serial_write_string
    pop si
    ret

read_serial_char:
    push dx
.wait:
    mov dx, COM1_PORT + 5
    in al, dx
    test al, 0x01
    jz .wait
    mov dx, COM1_PORT
    in al, dx
    pop dx
    ret

read_serial_line:
    push bx
    xor bx, bx

.loop:
    call read_serial_char
    cmp al, 0x0d
    je .newline
    cmp al, 0x0a
    je .newline
    cmp bx, cx
    jae .loop
    mov [di], al
    inc di
    inc bx
    jmp .loop

.newline:
    test bx, bx
    jz .loop
    mov byte [di], 0
    pop bx
    ret

host_read_response_silent:
    mov di, serial_line_buffer
    mov cx, SERIAL_LINE_MAX
    call read_serial_line
    ret

streq:
    push si
    push di

.loop:
    mov al, [si]
    mov ah, [di]
    cmp al, ah
    jne .not_equal
    test al, al
    je .equal
    inc si
    inc di
    jmp .loop

.equal:
    mov al, 1
    jmp .done

.not_equal:
    xor al, al

.done:
    pop di
    pop si
    ret

skip_spaces:
.loop:
    cmp byte [si], ' '
    je .consume
    cmp byte [si], 0x09
    jne .done
.consume:
    inc si
    jmp .loop
.done:
    ret

parse_signed_int:
    push bx
    push cx
    push dx

    call skip_spaces
    xor dx, dx
    cmp byte [si], '-'
    jne .check_plus
    mov dh, 1
    inc si
    jmp .digits

.check_plus:
    cmp byte [si], '+'
    jne .digits
    inc si

.digits:
    xor bx, bx
    xor cx, cx

.digit_loop:
    mov dl, [si]
    cmp dl, '0'
    jb .finish
    cmp dl, '9'
    ja .finish
    sub dl, '0'

    cmp bx, 3276
    ja .overflow
    jb .accumulate
    test dh, dh
    jnz .negative_limit
    cmp dl, 7
    ja .overflow
    jmp .accumulate

.negative_limit:
    cmp dl, 8
    ja .overflow

.accumulate:
    mov ax, bx
    shl bx, 1
    shl ax, 1
    shl ax, 1
    shl ax, 1
    add bx, ax

    xor ax, ax
    mov al, dl
    add bx, ax

    inc si
    inc cx
    jmp .digit_loop

.finish:
    test cx, cx
    jz .fail
    mov ax, bx
    test dh, dh
    jz .ok
    neg ax
.ok:
    clc
    jmp .done

.fail:
    xor ax, ax
    stc
    jmp .done

.overflow:
    mov ax, 1
    stc

.done:
    pop dx
    pop cx
    pop bx
    ret

print_uint_ax:
    push ax
    push bx
    push cx
    push dx

    cmp ax, 0
    jne .convert
    mov al, '0'
    call print_char
    jmp .done

.convert:
    xor cx, cx
    mov bx, 10

.loop:
    xor dx, dx
    div bx
    push dx
    inc cx
    test ax, ax
    jne .loop

.emit:
    pop dx
    add dl, '0'
    mov al, dl
    call print_char
    loop .emit

.done:
    pop dx
    pop cx
    pop bx
    pop ax
    ret

print_int_ax:
    test ax, ax
    jns .unsigned
    cmp ax, 0x8000
    jne .negate
    mov si, msg_int_min
    call print_string
    ret

.negate:
    push ax
    mov al, '-'
    call print_char
    pop ax
    neg ax
.unsigned:
    call print_uint_ax
    ret

print_hex32_eax:
    push cx
    push dx
    mov cx, 8

.loop:
    rol eax, 4
    push eax
    mov dl, al
    and dl, 0x0f
    cmp dl, 9
    jbe .digit
    add dl, 'A' - 10
    jmp .emit

.digit:
    add dl, '0'

.emit:
    mov al, dl
    call print_char
    pop eax
    loop .loop

    pop dx
    pop cx
    ret

print_hex64_from_si:
    push eax
    mov eax, [si + 4]
    call print_hex32_eax
    mov eax, [si]
    call print_hex32_eax
    pop eax
    ret

print_hex_nibble_al:
    cmp al, 9
    jbe .digit
    add al, 'A' - 10
    jmp .emit

.digit:
    add al, '0'

.emit:
    call print_char
    ret

print_hex_nibble_safe:
    push bx
    and al, 0x0f
    xor bx, bx
    mov bl, al
    mov al, [hex_digits + bx]
    call print_char
    pop bx
    ret

print_hex_byte_safe:
    push ax
    mov ah, al
    shr al, 4
    call print_hex_nibble_safe
    mov al, ah
    call print_hex_nibble_safe
    pop ax
    ret

print_hex_word_safe:
    push ax
    mov al, ah
    call print_hex_byte_safe
    pop ax
    call print_hex_byte_safe
    ret

print_hex8_al:
    push ax
    push dx
    mov dl, al
    mov al, dl
    shr al, 4
    call print_hex_nibble_al
    mov al, dl
    and al, 0x0f
    call print_hex_nibble_al
    pop dx
    pop ax
    ret

print_hex16_ax:
    push ax
    mov al, ah
    call print_hex8_al
    pop ax
    call print_hex8_al
    ret

serial_write_hex32_eax:
    push cx
    push dx
    push eax
    mov cx, 8

.loop:
    rol eax, 4
    push eax
    mov dl, al
    and dl, 0x0f
    cmp dl, 9
    jbe .digit
    add dl, 'A' - 10
    jmp .emit

.digit:
    add dl, '0'

.emit:
    mov al, dl
    call serial_write
    pop eax
    loop .loop

    pop eax
    pop dx
    pop cx
    ret

announce_generation:
    push si
    push eax
    mov si, msg_generation
    call print_string
    mov eax, [generation]
    call print_hex32_eax
    mov si, newline
    call print_string
    pop eax
    pop si
    ret

bump_generation:
    push si
    push eax
    inc dword [generation]
    mov si, msg_generation_advanced
    call print_string
    mov eax, [generation]
    call print_hex32_eax
    mov si, newline
    call print_string
    pop eax
    pop si
    ret

serial_write_generation_field:
    push si
    push eax
    mov si, msg_generation_json_prefix
    call serial_write_string
    mov eax, [generation]
    call serial_write_hex32_eax
    mov si, msg_generation_json_suffix
    call serial_write_string
    pop eax
    pop si
    ret

print_e820_type:
    push eax
    mov eax, [e820_buffer + 16]
    cmp eax, 1
    je .usable
    cmp eax, 2
    je .reserved
    cmp eax, 3
    je .acpi
    cmp eax, 4
    je .nvs
    cmp eax, 5
    je .bad
    mov si, msg_e820_type_unknown
    call print_string
    jmp .done

.usable:
    mov si, msg_e820_type_usable
    call print_string
    jmp .done

.reserved:
    mov si, msg_e820_type_reserved
    call print_string
    jmp .done

.acpi:
    mov si, msg_e820_type_acpi
    call print_string
    jmp .done

.nvs:
    mov si, msg_e820_type_nvs
    call print_string
    jmp .done

.bad:
    mov si, msg_e820_type_bad
    call print_string

.done:
    pop eax
    ret
