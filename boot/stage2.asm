[bits 16]
[org 0x8000]

%define COM1_PORT        0x3f8
%define INPUT_MAX        255
%define SERIAL_LINE_MAX  511
%define GRAPH_ROWS       23
%define GRAPH_COLS       79
%define GRAPH_CENTER_ROW 11
%define GRAPH_CENTER_COL 39
%define GFX_SEG          0xa000
%define PS2_DATA         0x60
%define PS2_STATUS       0x64
%define EDITOR_CAPACITY  2048
%define TASK_SLOT_COUNT  4
%define TASK_NAME_SIZE   16
%define TASK_GOAL_SIZE   160
%define CHAT_SESSION_SIZE 16
%define HOST_ACTION_SIZE 24
%define PATCH_MAX_BYTES  32
%define PEEK_MAX_BYTES   32
%define CHAT_LOOP_MAX_STEPS 8

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
    call show_prompt
    mov di, input_buffer
    mov cx, INPUT_MAX
    call read_line
    cmp byte [input_buffer], 0
    je main_loop
    call dispatch_command
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
    mov si, msg_hardware_list
    call print_string
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

do_show_balance:
    call show_balance_program
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

do_graph:
    call graph_program
    ret

do_paint:
    call paint_program
    ret

do_edit:
    call editor_program
    ret

do_peek:
    call peek_program
    ret

do_clear:
    call set_text_mode
    mov si, msg_cleared
    call print_string
    ret

do_about:
    mov si, msg_about
    call print_string
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
    mov ax, 0x0003
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
    jne .done
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

    mov ax, bx
    shl bx, 1
    shl ax, 1
    shl ax, 1
    shl ax, 1
    add bx, ax

    mov al, [si]
    sub al, '0'
    cbw
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

memory_map:
    mov si, msg_memory_map_header
    call print_string

    xor bp, bp
    xor ebx, ebx

.next_entry:
    push ds
    push es
    mov di, e820_buffer
    mov eax, 0x0000E820
    mov edx, 0x534D4150
    mov ecx, 20
    int 0x15
    pop es
    pop ds
    jc .finish
    cmp eax, 0x534D4150
    jne .unsupported

    mov [e820_continuation], ebx
    inc bp

    mov al, '#'
    call print_char
    mov ax, bp
    call print_uint_ax
    mov si, msg_base
    call print_string
    mov si, e820_buffer
    call print_hex64_from_si
    mov si, msg_length
    call print_string
    mov si, e820_buffer + 8
    call print_hex64_from_si
    mov si, msg_type
    call print_string
    call print_e820_type
    mov si, newline
    call print_string

    mov ebx, [e820_continuation]
    test ebx, ebx
    jne .next_entry
    ret

.finish:
    cmp bp, 0
    jne .done

.unsupported:
    mov si, msg_memory_map_unavailable
    call print_string

.done:
    ret

calculator_program:
    call set_text_mode
    mov si, msg_calc_intro
    call print_string

.loop:
    mov si, prompt_calc
    call print_string
    mov di, input_buffer
    mov cx, INPUT_MAX
    call read_line
    cmp byte [input_buffer], 0
    je .exit

    mov si, input_buffer
    mov di, cmd_exit
    call streq
    cmp al, 1
    je .exit

    mov si, input_buffer
    call parse_signed_int
    jc .syntax
    mov [calc_left], ax

    call skip_spaces
    mov al, [si]
    cmp al, '+'
    je .have_op
    cmp al, '-'
    je .have_op
    cmp al, '*'
    je .have_op
    cmp al, '/'
    je .have_op
    cmp al, '%'
    je .have_op
    jmp .syntax

.have_op:
    mov [calc_op], al
    inc si
    call parse_signed_int
    jc .syntax
    mov [calc_right], ax
    call skip_spaces
    cmp byte [si], 0
    jne .syntax

    mov ax, [calc_left]
    mov bx, [calc_right]
    mov dl, [calc_op]
    cmp dl, '+'
    je .add
    cmp dl, '-'
    je .sub
    cmp dl, '*'
    je .mul
    cmp dl, '/'
    je .div
    cmp dl, '%'
    je .mod
    jmp .syntax

.add:
    add ax, bx
    jmp .result

.sub:
    sub ax, bx
    jmp .result

.mul:
    imul bx
    jmp .result

.div:
    cmp bx, 0
    je .div_zero
    cwd
    idiv bx
    jmp .result

.mod:
    cmp bx, 0
    je .div_zero
    cwd
    idiv bx
    mov ax, dx
    jmp .result

.result:
    mov [calc_result], ax
    mov si, msg_calc_result
    call print_string
    mov ax, [calc_result]
    call print_int_ax
    mov si, newline
    call print_string
    jmp .loop

.div_zero:
    mov si, msg_calc_div_zero
    call print_string
    jmp .loop

.syntax:
    mov si, msg_calc_syntax
    call print_string
    jmp .loop

.exit:
    mov si, msg_calc_exit
    call print_string
    ret

chat_program:
    call set_text_mode
    mov byte [chat_session_active], 0
    mov byte [chat_loop_active], 0
    mov byte [chat_loop_steps], 0
    mov si, msg_chat_intro
    call print_string

.loop:
    mov si, prompt_chat
    call print_string
    mov di, input_buffer
    mov cx, INPUT_MAX
    call read_line
    cmp byte [input_buffer], 0
    je .exit

    mov si, input_buffer
    mov di, cmd_exit
    call streq
    cmp al, 1
    je .exit

    call chat_prepare_fresh_session
    mov si, msg_chat_wait
    call print_string
    call chat_send_request
    call chat_handle_response
    jmp .loop

.exit:
    cmp byte [chat_session_active], 1
    jne .clear
    mov si, chat_session_buffer
    call host_send_retire_named
    call host_read_response_silent

.clear:
    mov byte [chat_session_active], 0
    mov byte [chat_loop_active], 0
    mov byte [chat_loop_steps], 0
    mov si, msg_chat_exit
    call print_string
    ret

chat_send_request:
    mov si, msg_chat_post_prefix
    call serial_write_string
    mov si, chat_session_buffer
    call serial_write_json_escaped
    mov si, msg_chat_post_mid
    call serial_write_string
    mov si, input_buffer
    call serial_write_json_escaped
    mov si, msg_json_quote
    call serial_write_string
    call serial_write_generation_field
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    ret

chat_handle_response:
    call host_read_response
    cmp byte [chat_loop_active], 1
    jne .done

.loop_continue:
    mov al, [chat_loop_steps]
    cmp al, CHAT_LOOP_MAX_STEPS
    jae .loop_limit
    inc byte [chat_loop_steps]
    mov si, msg_chat_loop_wait
    call print_string
    call chat_send_loop_request
    call host_read_response
    cmp byte [chat_loop_active], 1
    je .loop_continue

.done:
    ret

.loop_limit:
    mov byte [chat_loop_active], 0
    mov si, msg_chat_loop_limit
    call print_string
    ret

chat_send_loop_request:
    mov si, msg_chat_loop_post_prefix
    call serial_write_string
    mov si, chat_session_buffer
    call serial_write_json_escaped
    mov si, msg_chat_loop_post_mid
    call serial_write_string
    call serial_write_generation_field
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    ret

chat_prepare_fresh_session:
    cmp byte [chat_session_active], 1
    jne .allocate
    mov si, chat_session_buffer
    call host_send_retire_named
    call host_read_response_silent

.allocate:
    inc dword [chat_session_counter]
    mov di, chat_session_buffer
    mov al, 'c'
    mov [di], al
    inc di
    mov al, 'h'
    mov [di], al
    inc di
    mov al, 'a'
    mov [di], al
    inc di
    mov al, 't'
    mov [di], al
    inc di
    mov al, '-'
    mov [di], al
    inc di
    mov eax, [chat_session_counter]
    call write_hex32_buffer_eax
    mov byte [di], 0
    mov byte [chat_session_active], 1
    mov byte [chat_loop_active], 0
    mov byte [chat_loop_steps], 0
    ret

curl_program:
    call set_text_mode
    mov si, msg_curl_intro
    call print_string

.loop:
    mov si, prompt_curl
    call print_string
    mov di, task_arg_buffer
    mov cx, TASK_GOAL_SIZE - 1
    call read_line
    cmp byte [task_arg_buffer], 0
    je .exit

    mov si, task_arg_buffer
    mov di, cmd_exit
    call streq
    cmp al, 1
    je .exit

    mov si, msg_curl_wait
    call print_string
    call host_send_curl_request
    call host_read_response
    jmp .loop

.exit:
    mov si, msg_curl_exit
    call print_string
    ret

show_balance_program:
    call set_text_mode
    mov si, msg_show_balance_wait
    call print_string
    call host_send_balance_request
    call host_read_response
    ret

hostreq_program:
    call set_text_mode
    mov si, msg_hostreq_intro
    call print_string

    mov si, prompt_host_action
    call print_string
    mov di, host_action_buffer
    mov cx, HOST_ACTION_SIZE - 1
    call read_line
    cmp byte [host_action_buffer], 0
    je .exit

    mov si, host_action_buffer
    mov di, action_list_sessions
    call streq
    cmp al, 1
    je .do_list

    mov si, host_action_buffer
    mov di, action_spawn_session
    call streq
    cmp al, 1
    je .do_spawn

    mov si, host_action_buffer
    mov di, action_clone_session
    call streq
    cmp al, 1
    je .do_clone

    mov si, host_action_buffer
    mov di, action_retire_session
    call streq
    cmp al, 1
    je .do_retire

    mov si, host_action_buffer
    mov di, action_step_session
    call streq
    cmp al, 1
    je .do_step

    mov si, host_action_buffer
    mov di, action_adopt_style
    call streq
    cmp al, 1
    je .do_adopt

    mov si, msg_hostreq_unknown
    call print_string
    ret

.do_list:
    call host_send_list_request
    call host_read_response
    ret

.do_spawn:
    call prompt_task_identity
    jc .exit
    mov si, prompt_task_goal
    call print_string
    mov di, task_goal_buffer
    mov cx, TASK_GOAL_SIZE - 1
    call read_line
    call host_send_spawn_request
    call host_read_response
    ret

.do_clone:
    call prompt_task_identity
    jc .exit
    mov si, prompt_task_source
    call print_string
    mov di, task_source_buffer
    mov cx, TASK_NAME_SIZE - 1
    call read_line
    cmp byte [task_source_buffer], 0
    je .exit
    mov si, prompt_host_modifier
    call print_string
    mov di, task_arg_buffer
    mov cx, TASK_GOAL_SIZE - 1
    call read_line
    call host_send_clone_request
    call host_read_response
    ret

.do_retire:
    call prompt_task_identity
    jc .exit
    call host_send_retire_request
    call host_read_response
    ret

.do_step:
    call prompt_task_identity
    jc .exit
    mov si, prompt_host_prompt
    call print_string
    mov di, task_arg_buffer
    mov cx, TASK_GOAL_SIZE - 1
    call read_line
    call host_send_step_request
    call host_read_response
    ret

.do_adopt:
    call prompt_task_identity
    jc .exit
    mov si, prompt_task_source
    call print_string
    mov di, task_source_buffer
    mov cx, TASK_NAME_SIZE - 1
    call read_line
    cmp byte [task_source_buffer], 0
    je .exit
    mov si, prompt_host_modifier
    call print_string
    mov di, task_arg_buffer
    mov cx, TASK_GOAL_SIZE - 1
    call read_line
    call host_send_adopt_request
    call host_read_response
    ret

.exit:
    mov si, msg_hostreq_exit
    call print_string
    ret

task_spawn_program:
    call set_text_mode
    mov si, msg_task_spawn_intro
    call print_string
    call prompt_task_identity
    jc .exit

    mov si, task_session_buffer
    call task_find_slot
    jnc .exists

    call task_alloc_slot
    jc .full
    push bx

    mov si, prompt_task_goal
    call print_string
    mov di, task_goal_buffer
    mov cx, TASK_GOAL_SIZE - 1
    call read_line

    call host_send_spawn_request
    call host_read_response
    cmp al, 1
    je .host_error

    pop bx
    mov byte [task_active + bx], 1
    mov si, task_session_buffer
    call task_name_ptr
    mov cx, TASK_NAME_SIZE - 1
    call copy_capped_string
    mov si, task_goal_buffer
    call task_goal_ptr
    mov cx, TASK_GOAL_SIZE - 1
    call copy_capped_string
    mov si, msg_task_spawned
    call print_string
    ret

.exists:
    mov si, msg_task_exists
    call print_string
    ret

.full:
    mov si, msg_task_full
    call print_string
    ret

.host_error:
    pop bx
    ret

.exit:
    mov si, msg_task_abort
    call print_string
    ret

task_list_program:
    call set_text_mode
    mov si, msg_task_list_intro
    call print_string
    xor bx, bx
    xor dx, dx

.loop:
    cmp bx, TASK_SLOT_COUNT
    jae .done_local
    cmp byte [task_active + bx], 0
    je .next
    inc dx
    mov al, '#'
    call print_char
    mov ax, bx
    inc ax
    call print_uint_ax
    mov si, msg_task_name_prefix
    call print_string
    call task_name_ptr
    mov si, di
    call print_string
    mov si, msg_task_goal_prefix
    call print_string
    call task_goal_ptr
    mov si, di
    call print_string
    mov si, newline
    call print_string

.next:
    inc bx
    jmp .loop

.done_local:
    test dx, dx
    jnz .host
    mov si, msg_task_none
    call print_string

.host:
    mov si, msg_task_host_summary
    call print_string
    call host_send_list_request
    call host_read_response
    ret

task_retire_program:
    call set_text_mode
    mov si, msg_task_retire_intro
    call print_string
    call prompt_task_identity
    jc .exit

    mov si, task_session_buffer
    call task_find_slot
    pushf
    push bx
    call host_send_retire_request
    call host_read_response
    cmp al, 1
    je .done
    pop bx
    popf
    jc .done
    call task_clear_slot
    mov si, msg_task_retired
    call print_string
    ret

.done:
    pop bx
    popf
    ret

.exit:
    mov si, msg_task_abort
    call print_string
    ret

task_step_program:
    call set_text_mode
    mov si, msg_task_step_intro
    call print_string
    call prompt_task_identity
    jc .exit
    mov si, task_session_buffer
    call task_find_slot
    jc .missing

    mov si, prompt_host_prompt
    call print_string
    mov di, task_arg_buffer
    mov cx, TASK_GOAL_SIZE - 1
    call read_line
    call host_send_step_request
    call host_read_response
    cmp al, 2
    je .done
    cmp al, 1
    je .done
    call bump_generation
.done:
    ret

.missing:
    mov si, msg_task_missing
    call print_string
    ret

.exit:
    mov si, msg_task_abort
    call print_string
    ret

prompt_task_identity:
    mov si, prompt_task_session
    call print_string
    mov di, task_session_buffer
    mov cx, TASK_NAME_SIZE - 1
    call read_line
    cmp byte [task_session_buffer], 0
    jne .ok
    stc
    ret

.ok:
    clc
    ret

task_alloc_slot:
    xor bx, bx

.loop:
    cmp bx, TASK_SLOT_COUNT
    jae .full
    cmp byte [task_active + bx], 0
    je .found
    inc bx
    jmp .loop

.found:
    clc
    ret

.full:
    stc
    ret

task_find_slot:
    push di
    xor bx, bx

.loop:
    cmp bx, TASK_SLOT_COUNT
    jae .missing
    cmp byte [task_active + bx], 0
    je .next
    call task_name_ptr
    call streq
    cmp al, 1
    je .found

.next:
    inc bx
    jmp .loop

.found:
    pop di
    clc
    ret

.missing:
    pop di
    stc
    ret

task_name_ptr:
    push ax
    mov di, task_names
    mov ax, bx
    shl ax, 4
    add di, ax
    pop ax
    ret

task_goal_ptr:
    push ax
    mov di, task_goals
    mov ax, bx
    shl ax, 6
    add di, ax
    pop ax
    ret

task_clear_slot:
    mov byte [task_active + bx], 0
    call task_name_ptr
    mov byte [di], 0
    call task_goal_ptr
    mov byte [di], 0
    ret

copy_capped_string:
    push ax

.loop:
    lodsb
    test al, al
    jz .terminate
    test cx, cx
    jz .truncate
    stosb
    dec cx
    jmp .loop

.truncate:
    mov al, 0
    stosb
    jmp .done

.terminate:
    mov al, 0
    stosb

.done:
    pop ax
    ret

strprefix:
    push si
    push di

.loop:
    mov al, [di]
    test al, al
    jz .match
    cmp [si], al
    jne .miss
    inc si
    inc di
    jmp .loop

.match:
    mov al, 1
    jmp .done

.miss:
    xor al, al

.done:
    pop di
    pop si
    ret

hex_char_to_nibble:
    cmp al, '0'
    jb .maybe_alpha
    cmp al, '9'
    jbe .digit

.maybe_alpha:
    or al, 0x20
    cmp al, 'a'
    jb .fail
    cmp al, 'f'
    ja .fail
    sub al, 'a' - 10
    clc
    ret

.digit:
    sub al, '0'
    clc
    ret

.fail:
    stc
    ret

parse_hex_word:
    push cx
    xor bx, bx
    xor cx, cx

    cmp byte [si], '0'
    jne .digits
    mov al, [si + 1]
    or al, 0x20
    cmp al, 'x'
    jne .digits
    add si, 2

.digits:
    mov al, [si]
    call hex_char_to_nibble
    jc .finish
    shl bx, 4
    or bl, al
    inc si
    inc cx
    cmp cx, 4
    jb .digits

    mov al, [si]
    call hex_char_to_nibble
    jnc .fail
    jmp .success

.finish:
    test cx, cx
    jz .fail

.success:
    pop cx
    clc
    ret

.fail:
    pop cx
    stc
    ret

parse_hex_byte:
    push bx
    push cx
    xor bx, bx
    xor cx, cx

    cmp byte [si], '0'
    jne .digits
    mov al, [si + 1]
    or al, 0x20
    cmp al, 'x'
    jne .digits
    add si, 2

.digits:
    mov al, [si]
    call hex_char_to_nibble
    jc .finish
    shl bl, 4
    or bl, al
    inc si
    inc cx
    cmp cx, 2
    jb .digits

    mov al, [si]
    call hex_char_to_nibble
    jnc .fail
    jmp .success

.finish:
    test cx, cx
    jz .fail

.success:
    mov al, bl
    pop cx
    pop bx
    clc
    ret

.fail:
    pop cx
    pop bx
    stc
    ret

parse_patch:
    call skip_spaces
    call parse_hex_word
    jc .fail
    mov [patch_offset], bx
    mov word [patch_byte_count], 0

.next_byte:
    call skip_spaces
    cmp byte [si], 0
    je .done
    call parse_hex_byte
    jc .fail
    mov bx, [patch_byte_count]
    cmp bx, PATCH_MAX_BYTES
    jae .fail
    mov [patch_bytes + bx], al
    inc bx
    mov [patch_byte_count], bx
    jmp .next_byte

.done:
    cmp word [patch_byte_count], 0
    je .fail
    clc
    ret

.fail:
    stc
    ret

parse_peek_args:
    call skip_spaces
    call parse_hex_word
    jc .fail
    mov [peek_offset], bx
    call skip_spaces
    call parse_hex_word
    jc .fail
    test bx, bx
    jz .fail
    cmp bx, PEEK_MAX_BYTES
    ja .fail
    mov [peek_count], bx
    call skip_spaces
    cmp byte [si], 0
    jne .fail
    clc
    ret

.fail:
    stc
    ret

peek_dump:
    push ax
    push bx
    push cx
    push si
    mov si, msg_peek_header
    call print_string
    mov ax, [peek_offset]
    call print_hex_word_safe
    mov si, msg_peek_mid
    call print_string
    mov bx, [peek_offset]
    add bx, 0x8000
    mov cx, [peek_count]

.byte_loop:
    test cx, cx
    jz .done
    mov al, [bx]
    call print_hex_byte_safe
    dec cx
    inc bx
    test cx, cx
    jz .done
    mov al, ' '
    call print_char
    jmp .byte_loop

.done:
    mov si, newline
    call print_string
    pop si
    pop cx
    pop bx
    pop ax
    ret

print_patch_warning:
    push ax
    push bx
    push cx
    push eax
    push si
    mov si, msg_patch_danger
    call print_string
    mov si, msg_patch_offset
    call print_string
    mov ax, [patch_offset]
    call print_hex_word_safe
    mov si, msg_patch_bytes
    call print_string
    xor bx, bx
    mov cx, [patch_byte_count]

.byte_loop:
    test cx, cx
    jz .prompt
    mov al, [patch_bytes + bx]
    call print_hex_byte_safe
    dec cx
    inc bx
    test cx, cx
    jz .prompt
    mov al, ' '
    call print_char
    jmp .byte_loop

.prompt:
    mov si, newline
    call print_string
    mov si, msg_patch_prompt
    call print_string
    pop eax
    pop si
    pop cx
    pop bx
    pop ax
    ret

apply_live_patch:
    mov si, msg_applying
    call print_string
    mov bx, [patch_offset]
    add bx, 0x8000
    mov di, bx
    mov cx, [patch_byte_count]
    mov si, patch_bytes
    cld
    rep movsb
    jmp short $+2
    mov si, msg_patch_applied
    call print_string
    ret

peek_program:
    call set_text_mode
    mov si, msg_peek_intro
    call print_string
    mov si, prompt_peek_offset
    call print_string
    mov di, peek_token_buffer
    mov cx, 7
    call read_line
    cmp byte [peek_token_buffer], 0
    je .bad
    mov si, peek_token_buffer
    call parse_hex_word
    jc .bad
    mov [peek_offset], bx
    mov si, prompt_peek_count
    call print_string
    mov di, peek_token_buffer
    mov cx, 7
    call read_line
    cmp byte [peek_token_buffer], 0
    je .bad
    mov si, peek_token_buffer
    call parse_hex_word
    jc .bad
    test bx, bx
    jz .bad
    cmp bx, PEEK_MAX_BYTES
    ja .bad
    mov [peek_count], bx
    call peek_dump
    ret

.bad:
    mov si, msg_peek_bad
    call print_string
    ret

host_read_response:
    mov di, serial_line_buffer
    mov cx, SERIAL_LINE_MAX
    call read_serial_line
    mov si, serial_line_buffer
    mov di, msg_cmd_prefix
    call strprefix
    cmp al, 1
    je .command

    mov byte [chat_loop_active], 0
    mov si, serial_line_buffer
    call print_string
    mov si, newline
    call print_string
    mov si, serial_line_buffer
    mov di, msg_error_prefix
    call strprefix
    ret

.command:
    mov al, [chat_loop_active]
    mov [chat_loop_resume], al
    mov si, msg_cmd_dispatch
    call print_string
    mov si, serial_line_buffer + 5
    call print_string
    mov si, newline
    call print_string
    mov si, serial_line_buffer + 5
    mov di, curl_prefix
    call strprefix
    cmp al, 1
    je .curl
    mov si, serial_line_buffer + 5
    mov di, loop_prefix
    call strprefix
    cmp al, 1
    je .loop_control
    mov si, serial_line_buffer + 5
    mov di, patch_prefix
    call strprefix
    cmp al, 1
    je .patch
    mov si, serial_line_buffer + 5
    mov di, peek_prefix
    call strprefix
    cmp al, 1
    je .peek
    mov si, serial_line_buffer + 5
    mov di, input_buffer
    mov cx, INPUT_MAX
    call copy_capped_string
    call dispatch_command
    cmp al, 1
    je .success
    mov byte [chat_loop_active], 0
    mov al, 1
    ret

.patch:
    mov si, serial_line_buffer + 12
    call parse_patch
    jc .patch_invalid
    call print_patch_warning
    call read_input_char
    cmp al, 27
    je .patch_aborted
    call apply_live_patch
    call bump_generation
    mov al, [chat_loop_resume]
    cmp al, 1
    jne .patch_done
    mov byte [chat_loop_active], 1

.patch_done:
    mov al, 2
    ret

.patch_invalid:
    mov byte [chat_loop_active], 0
    mov si, msg_unknown_patch
    call print_string
    mov al, 1
    ret

.patch_aborted:
    mov byte [chat_loop_active], 0
    mov si, msg_patch_aborted
    call print_string
    mov al, 1
    ret

.curl:
    mov si, serial_line_buffer + 11
    mov di, task_arg_buffer
    mov cx, TASK_GOAL_SIZE - 1
    call copy_capped_string
    cmp byte [task_arg_buffer], 0
    je .curl_invalid
    call host_send_curl_request
    call host_read_response
    mov al, [chat_loop_resume]
    cmp al, 1
    jne .curl_done
    mov byte [chat_loop_active], 1

.curl_done:
    xor al, al
    ret

.curl_invalid:
    mov byte [chat_loop_active], 0
    mov si, msg_curl_bad
    call print_string
    mov al, 1
    ret

.peek:
    mov si, serial_line_buffer + 11
    call parse_peek_args
    jc .peek_invalid
    call peek_dump
    mov al, [chat_loop_resume]
    cmp al, 1
    jne .peek_done
    mov byte [chat_loop_active], 1

.peek_done:
    xor al, al
    ret

.peek_invalid:
    mov byte [chat_loop_active], 0
    mov si, msg_peek_bad
    call print_string
    mov al, 1
    ret

.loop_control:
    cmp byte [chat_loop_active], 1
    je .loop_ready
    mov byte [chat_loop_active], 1
    mov byte [chat_loop_steps], 0
    mov si, msg_chat_loop_enabled
    call print_string

.loop_ready:
    xor al, al
    ret

.success:
    mov al, [chat_loop_resume]
    cmp al, 1
    jne .success_done
    mov byte [chat_loop_active], 1

.success_done:
    xor al, al
    ret

host_send_list_request:
    mov si, msg_host_post_list
    call serial_write_string
    call serial_write_generation_field
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    ret

host_send_spawn_request:
    mov si, msg_host_post_spawn_prefix
    call serial_write_string
    mov si, task_session_buffer
    call serial_write_json_escaped
    mov si, msg_host_post_spawn_mid
    call serial_write_string
    mov si, task_goal_buffer
    call serial_write_json_escaped
    mov si, msg_json_quote
    call serial_write_string
    call serial_write_generation_field
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    ret

host_send_retire_request:
    mov si, msg_host_post_retire_prefix
    call serial_write_string
    mov si, task_session_buffer
    call serial_write_json_escaped
    mov si, msg_json_quote
    call serial_write_string
    call serial_write_generation_field
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    ret

host_send_retire_named:
    mov di, si
    mov si, msg_host_post_retire_prefix
    call serial_write_string
    mov si, di
    call serial_write_json_escaped
    mov si, msg_json_quote
    call serial_write_string
    call serial_write_generation_field
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    ret

host_send_step_request:
    mov si, msg_host_post_step_prefix
    call serial_write_string
    mov si, task_session_buffer
    call serial_write_json_escaped
    mov si, msg_host_post_step_mid
    call serial_write_string
    mov si, task_arg_buffer
    call serial_write_json_escaped
    mov si, msg_json_quote
    call serial_write_string
    call serial_write_generation_field
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    ret

host_send_curl_request:
    mov si, msg_host_post_curl_prefix
    call serial_write_string
    mov si, task_arg_buffer
    call serial_write_json_escaped
    mov si, msg_json_quote
    call serial_write_string
    call serial_write_generation_field
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    ret

host_send_balance_request:
    mov si, msg_host_post_balance
    call serial_write_string
    call serial_write_generation_field
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    ret

host_send_clone_request:
    mov si, msg_host_post_clone_prefix
    call serial_write_string
    mov si, task_session_buffer
    call serial_write_json_escaped
    mov si, msg_host_post_clone_mid
    call serial_write_string
    mov si, task_source_buffer
    call serial_write_json_escaped
    mov si, msg_host_post_modifier_mid
    call serial_write_string
    mov si, task_arg_buffer
    call serial_write_json_escaped
    mov si, msg_json_quote
    call serial_write_string
    call serial_write_generation_field
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    ret

host_send_adopt_request:
    mov si, msg_host_post_adopt_prefix
    call serial_write_string
    mov si, task_session_buffer
    call serial_write_json_escaped
    mov si, msg_host_post_clone_mid
    call serial_write_string
    mov si, task_source_buffer
    call serial_write_json_escaped
    mov si, msg_host_post_modifier_mid
    call serial_write_string
    mov si, task_arg_buffer
    call serial_write_json_escaped
    mov si, msg_json_quote
    call serial_write_string
    call serial_write_generation_field
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    ret

graph_program:
    mov byte [graph_mode], 1

.render:
    call set_text_mode
    mov si, msg_graph_intro
    call print_string
    mov al, [graph_mode]
    cmp al, 1
    je .line_mode
    cmp al, 2
    je .parabola_mode
    mov si, msg_graph_mode_wave
    call print_string
    jmp .rows

.line_mode:
    mov si, msg_graph_mode_line
    call print_string
    jmp .rows

.parabola_mode:
    mov si, msg_graph_mode_parabola
    call print_string

.rows:
    xor dx, dx

.row_loop:
    cmp dl, GRAPH_ROWS
    jae .footer
    xor cx, cx

.col_loop:
    cmp cl, GRAPH_COLS + 1
    jae .end_row
    mov byte [graph_char], ' '
    cmp dl, GRAPH_CENTER_ROW
    jne .not_x_axis
    mov byte [graph_char], '-'

.not_x_axis:
    cmp cl, GRAPH_CENTER_COL
    jne .not_y_axis
    mov byte [graph_char], '|'
    cmp dl, GRAPH_CENTER_ROW
    jne .not_y_axis
    mov byte [graph_char], '+'

.not_y_axis:
    mov al, cl
    call graph_compute_row
    cmp al, 0xff
    je .emit
    cmp al, dl
    jne .emit
    mov byte [graph_char], '*'

.emit:
    mov al, [graph_char]
    call print_char
    inc cl
    jmp .col_loop

.end_row:
    mov si, newline
    call print_string
    inc dl
    jmp .row_loop

.footer:
    mov si, msg_graph_footer
    call print_string
    call read_input_char
    cmp al, '1'
    je .set_line
    cmp al, '2'
    je .set_parabola
    cmp al, '3'
    je .set_wave
    cmp al, 'q'
    je .exit
    cmp al, 'Q'
    je .exit
    cmp al, 27
    je .exit
    jmp .render

.set_line:
    mov byte [graph_mode], 1
    jmp .render

.set_parabola:
    mov byte [graph_mode], 2
    jmp .render

.set_wave:
    mov byte [graph_mode], 3
    jmp .render

.exit:
    mov si, newline
    call print_string
    ret

graph_compute_row:
    push bx
    push cx
    push dx

    xor ah, ah
    mov bx, ax
    sub bx, GRAPH_CENTER_COL

    mov al, [graph_mode]
    cmp al, 1
    je .line
    cmp al, 2
    je .parabola

    mov ax, bx
    add ax, 40
    xor dx, dx
    mov cx, 16
    div cx
    mov ax, dx
    cmp ax, 8
    jbe .wave_small
    mov cx, 16
    sub cx, ax
    mov ax, cx

.wave_small:
    sub ax, 4
    mov dx, GRAPH_CENTER_ROW
    sub dx, ax
    mov ax, dx
    jmp .clip

.line:
    mov ax, bx
    cwd
    mov cx, 4
    idiv cx
    mov dx, GRAPH_CENTER_ROW
    sub dx, ax
    mov ax, dx
    jmp .clip

.parabola:
    mov ax, bx
    imul bx
    mov cx, 80
    div cx
    inc ax

.clip:
    cmp ax, 0
    jl .invalid
    cmp ax, GRAPH_ROWS - 1
    jg .invalid
    jmp .done

.invalid:
    mov al, 0xff

.done:
    pop dx
    pop cx
    pop bx
    ret

paint_program:
    call set_text_mode
    mov si, msg_paint_intro
    call print_string
    call mouse_init
    jc .no_mouse

    call set_graphics_mode
    call gfx_clear
    mov word [mouse_x], 160
    mov word [mouse_y], 100
    mov word [mouse_prev_x], 160
    mov word [mouse_prev_y], 100
    mov byte [mouse_color], 0x0e
    mov byte [mouse_prev_under], 0x00
    mov byte [mouse_packet_index], 0
    call paint_draw_cursor

.loop:
    call poll_input_char
    test al, al
    jz .mouse_only
    cmp al, 'q'
    je .exit
    cmp al, 'Q'
    je .exit
    cmp al, 27
    je .exit
    cmp al, 'c'
    je .cycle
    cmp al, 'C'
    je .cycle
    cmp al, 'x'
    je .clear
    cmp al, 'X'
    je .clear

.mouse_only:
    call mouse_poll_packet
    jmp .loop

.cycle:
    inc byte [mouse_color]
    cmp byte [mouse_color], 0x10
    jb .mouse_only
    mov byte [mouse_color], 0x02
    jmp .mouse_only

.clear:
    call paint_restore_cursor
    call gfx_clear
    mov byte [mouse_prev_under], 0x00
    call paint_draw_cursor
    jmp .mouse_only

.exit:
    call paint_restore_cursor
    call set_text_mode
    mov si, msg_paint_exit
    call print_string
    ret

.no_mouse:
    mov si, msg_paint_no_mouse
    call print_string
    ret

mouse_init:
    call mouse_flush

    call ps2_wait_write
    mov al, 0xa8
    out PS2_STATUS, al

    call ps2_wait_write
    mov al, 0x20
    out PS2_STATUS, al
    call ps2_wait_read
    in al, PS2_DATA
    or al, 0x02
    and al, 0xdf
    mov bl, al

    call ps2_wait_write
    mov al, 0x60
    out PS2_STATUS, al
    call ps2_wait_write
    mov al, bl
    out PS2_DATA, al

    mov al, 0xf6
    call mouse_send_command
    cmp al, 0xfa
    jne .fail

    mov al, 0xf4
    call mouse_send_command
    cmp al, 0xfa
    jne .fail

    clc
    ret

.fail:
    stc
    ret

mouse_flush:
    push cx
    mov cx, 0xffff

.loop:
    in al, PS2_STATUS
    test al, 0x01
    jz .done
    in al, PS2_DATA
    loop .loop

.done:
    pop cx
    ret

ps2_wait_write:
    push cx
    mov cx, 0xffff

.loop:
    in al, PS2_STATUS
    test al, 0x02
    jz .done
    loop .loop

.done:
    pop cx
    ret

ps2_wait_read:
    push cx
    mov cx, 0xffff

.loop:
    in al, PS2_STATUS
    test al, 0x01
    jnz .done
    loop .loop

.done:
    pop cx
    ret

mouse_send_command:
    push bx
    mov bl, al
    call ps2_wait_write
    mov al, 0xd4
    out PS2_STATUS, al
    call ps2_wait_write
    mov al, bl
    out PS2_DATA, al
    call ps2_wait_read
    in al, PS2_DATA
    pop bx
    ret

mouse_poll_packet:
    in al, PS2_STATUS
    test al, 0x01
    jz .done
    test al, 0x20
    jz .done
    in al, PS2_DATA
    mov bl, [mouse_packet_index]
    cmp bl, 0
    je .first
    cmp bl, 1
    je .second

    mov [mouse_packet + 2], al
    mov byte [mouse_packet_index], 0
    call paint_apply_packet
    jmp .done

.first:
    test al, 0x08
    jz .done
    mov [mouse_packet], al
    mov byte [mouse_packet_index], 1
    jmp .done

.second:
    mov [mouse_packet + 1], al
    mov byte [mouse_packet_index], 2

.done:
    ret

paint_apply_packet:
    call paint_restore_cursor

    mov al, [mouse_packet + 1]
    cbw
    add word [mouse_x], ax

    mov al, [mouse_packet + 2]
    cbw
    sub word [mouse_y], ax

    cmp word [mouse_x], 0
    jge .check_x_high
    mov word [mouse_x], 0

.check_x_high:
    cmp word [mouse_x], 319
    jle .check_y_low
    mov word [mouse_x], 319

.check_y_low:
    cmp word [mouse_y], 0
    jge .check_y_high
    mov word [mouse_y], 0

.check_y_high:
    cmp word [mouse_y], 199
    jle .buttons
    mov word [mouse_y], 199

.buttons:
    mov al, [mouse_packet]
    test al, 0x01
    jz .capture_under
    mov al, [mouse_color]
    call paint_set_current_pixel

.capture_under:
    call paint_get_current_pixel
    mov [mouse_prev_under], al
    call paint_draw_cursor
    ret

paint_draw_cursor:
    mov ax, [mouse_x]
    mov [mouse_prev_x], ax
    mov ax, [mouse_y]
    mov [mouse_prev_y], ax
    mov al, 0x0f
    call paint_set_current_pixel
    ret

paint_restore_cursor:
    push ax
    mov ax, [mouse_prev_x]
    mov [mouse_x], ax
    mov ax, [mouse_prev_y]
    mov [mouse_y], ax
    mov al, [mouse_prev_under]
    call paint_set_current_pixel
    mov ax, [mouse_prev_x]
    mov [mouse_x], ax
    mov ax, [mouse_prev_y]
    mov [mouse_y], ax
    pop ax
    ret

paint_set_current_pixel:
    push bx
    push dx
    push di
    push es

    mov bl, al
    mov ax, GFX_SEG
    mov es, ax
    mov ax, [mouse_y]
    mov dx, 320
    mul dx
    add ax, [mouse_x]
    mov di, ax
    mov al, bl
    mov [es:di], al

    pop es
    pop di
    pop dx
    pop bx
    ret

paint_get_current_pixel:
    push dx
    push di
    push es

    mov ax, GFX_SEG
    mov es, ax
    mov ax, [mouse_y]
    mov dx, 320
    mul dx
    add ax, [mouse_x]
    mov di, ax
    mov al, [es:di]

    pop es
    pop di
    pop dx
    ret

gfx_clear:
    push ax
    push cx
    push di
    push es

    mov ax, GFX_SEG
    mov es, ax
    xor di, di
    xor ax, ax
    mov cx, 32000
    rep stosw

    pop es
    pop di
    pop cx
    pop ax
    ret

editor_program:
    call set_text_mode
    mov word [editor_length], 0
    mov si, msg_editor_intro
    call print_string

.loop:
    call read_input_char
    cmp al, 27
    je .exit
    cmp al, 0x08
    je .backspace
    cmp al, 0x7f
    je .backspace
    cmp al, 0x0d
    je .newline
    cmp al, 32
    jb .loop

    mov bx, [editor_length]
    cmp bx, EDITOR_CAPACITY - 1
    jae .loop
    mov [editor_buffer + bx], al
    inc bx
    mov [editor_length], bx
    call print_char
    jmp .loop

.newline:
    mov bx, [editor_length]
    cmp bx, EDITOR_CAPACITY - 2
    jae .loop
    mov byte [editor_buffer + bx], 0x0d
    inc bx
    mov byte [editor_buffer + bx], 0x0a
    inc bx
    mov [editor_length], bx
    mov si, newline
    call print_string
    jmp .loop

.backspace:
    mov bx, [editor_length]
    test bx, bx
    jz .loop
    dec bx
    mov [editor_length], bx
    call editor_redraw
    jmp .loop

.exit:
    mov si, msg_editor_exit
    call print_string
    ret

editor_redraw:
    call set_text_mode
    mov si, msg_editor_intro
    call print_string
    mov cx, [editor_length]
    mov si, editor_buffer

.loop:
    test cx, cx
    jz .done
    lodsb
    call print_char
    dec cx
    jmp .loop

.done:
    ret

command_table:
    dw cmd_help, do_help
    dw cmd_hardware_list, do_hardware_list
    dw cmd_memory_map, do_memory_map
    dw cmd_calc, do_calc
    dw cmd_chat, do_chat
    dw cmd_curl, do_curl
    dw cmd_show_balance, do_show_balance
    dw cmd_hostreq, do_hostreq
    dw cmd_task_spawn, do_task_spawn
    dw cmd_task_list, do_task_list
    dw cmd_task_retire, do_task_retire
    dw cmd_task_step, do_task_step
    dw cmd_graph, do_graph
    dw cmd_paint, do_paint
    dw cmd_edit, do_edit
    dw cmd_peek, do_peek
    dw cmd_clear, do_clear
    dw cmd_about, do_about
    dw cmd_halt, do_halt
    dw cmd_reboot, do_reboot
    dw 0, 0

msg_banner db "stage2: command monitor ready", 13, 10, 0
msg_hint db "help, hardware_list, memory_map, calc, chat, curl, show_balance, hostreq, task_spawn, task_list, task_retire, task_step, graph, paint, edit, peek, clear, about, halt, reboot", 13, 10, 13, 10, 0
msg_help db "commands:", 13, 10
         db " help           show command list", 13, 10
         db " hardware_list  list hardware actions wired in this stage", 13, 10
         db " memory_map     query BIOS E820 memory map", 13, 10
         db " calc           integer calculator REPL", 13, 10
         db " chat           send prompts over COM1 to the host bridge", 13, 10
         db " curl           fetch a webpage through the host bridge", 13, 10
         db " show_balance   show Anthropic admin spend summary", 13, 10
         db " hostreq        send structured host control requests", 13, 10
         db " task_spawn     create a supervised task slot and host session", 13, 10
         db " task_list      show local task slots and host session summary", 13, 10
         db " task_retire    retire a supervised task slot", 13, 10
         db " task_step      step one supervised task through the host", 13, 10
         db " graph          ASCII graph viewer", 13, 10
         db " paint          mode 13h mouse paint demo", 13, 10
         db " edit           scratch text editor in RAM", 13, 10
         db " peek           inspect stage2 bytes at an offset", 13, 10
         db " clear          reset the text console", 13, 10
         db " about          describe the current environment", 13, 10
         db " halt           stop the CPU", 13, 10
         db " reboot         jump back through BIOS", 13, 10, 0
msg_unknown db "unknown command", 13, 10, 0
msg_cleared db "console cleared", 13, 10, 0
msg_about db "kernel_os monitor running in 16-bit real mode on BIOS services", 13, 10, 0
msg_halt db "halting CPU", 13, 10, 0
msg_reboot db "rebooting through BIOS", 13, 10, 0
msg_hardware_list db "hardware actions reachable on this machine:", 13, 10
                  db " - BIOS keyboard input", 13, 10
                  db " - VGA text and mode 13h graphics output", 13, 10
                  db " - COM1 serial input and output", 13, 10
                  db " - BIOS disk reads from the boot device", 13, 10
                  db " - BIOS E820 memory map probing via memory_map", 13, 10
                  db " - Direct PS/2 mouse polling for paint mode", 13, 10
                  db " - Scratch text editing in RAM", 13, 10
                  db "Next logical targets: LBA disk I/O, IRQs, PCI, protected mode, long mode, filesystem support", 13, 10, 0
msg_memory_map_header db "bios e820 memory map:", 13, 10, 0
msg_memory_map_unavailable db "memory map unavailable from BIOS", 13, 10, 0
msg_base db " base=0x", 0
msg_length db " length=0x", 0
msg_type db " type=", 0
msg_e820_type_usable db "usable", 0
msg_e820_type_reserved db "reserved", 0
msg_e820_type_acpi db "acpi reclaimable", 0
msg_e820_type_nvs db "acpi nvs", 0
msg_e820_type_bad db "bad memory", 0
msg_e820_type_unknown db "unknown", 0
msg_calc_intro db "calculator: enter expressions like 12+34 or 42 / 6. blank line or exit returns.", 13, 10, 0
msg_calc_result db "= ", 0
msg_calc_div_zero db "division by zero", 13, 10, 0
msg_calc_syntax db "syntax: <integer> <op> <integer> where op is + - * / %", 13, 10, 0
msg_calc_exit db "leaving calculator", 13, 10, 0
msg_chat_intro db "chat: type a prompt, get a fresh claude session, blank line or exit returns. the model may emit /paint, /loop for recursive mode, other slash commands, or a live /patch proposal.", 13, 10, 0
msg_chat_wait db "waiting for host response...", 13, 10, 0
msg_chat_loop_wait db "recursive loop: continuing with host...", 13, 10, 0
msg_chat_loop_enabled db "recursive loop enabled. the host will keep iterating until claude returns a normal answer.", 13, 10, 0
msg_chat_loop_limit db "recursive loop limit reached; handing control back to the user.", 13, 10, 0
msg_chat_exit db "leaving chat", 13, 10, 0
msg_chat_post_prefix db 'POST /chat {"session":"', 0
msg_chat_post_mid db '","prompt":"', 0
msg_chat_loop_post_prefix db 'POST /chat {"session":"', 0
msg_chat_loop_post_mid db '","prompt":"continue recursive loop mode until you are satisfied; when you are done, return a normal user-facing answer","loop":true', 0
msg_curl_intro db "curl: fetch a URL through the host bridge. blank line or exit returns.", 13, 10, 0
msg_curl_wait db "waiting for webpage...", 13, 10, 0
msg_curl_exit db "leaving curl", 13, 10, 0
msg_curl_bad db "curl syntax: use a non-empty http:// or https:// URL", 13, 10, 0
msg_show_balance_wait db "checking anthropic spend summary through the host bridge...", 13, 10, 0
msg_peek_intro db "peek: inspect bytes from the live stage2 image", 13, 10, 0
msg_peek_bad db "peek syntax: offset and count are required hex values, count 1..20", 13, 10, 0
msg_peek_header db "peek 0x", 0
msg_peek_mid db ": ", 0
msg_hostreq_intro db "hostreq actions: list-sessions, spawn-session, clone-session, retire-session, step-session, adopt-style", 13, 10, 0
msg_hostreq_unknown db "unknown host action", 13, 10, 0
msg_hostreq_exit db "leaving hostreq", 13, 10, 0
msg_task_spawn_intro db "task_spawn: create a supervised task slot and matching host session", 13, 10, 0
msg_task_list_intro db "local supervised tasks:", 13, 10, 0
msg_task_retire_intro db "task_retire: retire a task slot and host session", 13, 10, 0
msg_task_step_intro db "task_step: ask one supervised task to take its next bounded step", 13, 10, 0
msg_task_abort db "task command aborted", 13, 10, 0
msg_task_exists db "task already exists locally", 13, 10, 0
msg_task_full db "no free local task slots remain", 13, 10, 0
msg_task_spawned db "task stored locally", 13, 10, 0
msg_task_missing db "task not found in local slots", 13, 10, 0
msg_task_retired db "task removed from local slots", 13, 10, 0
msg_task_none db "no local tasks", 13, 10, 0
msg_task_host_summary db "host session summary:", 13, 10, 0
msg_task_name_prefix db " name=", 0
msg_task_goal_prefix db " goal=", 0
msg_cmd_prefix db "CMD: ", 0
msg_cmd_dispatch db "AI requested command: ", 0
msg_error_prefix db "Error:", 0
msg_generation db "generation 0x", 0
msg_generation_advanced db "generation advanced to 0x", 0
msg_patch_danger db 13, 10, "*** CLAUDE COOKED UP A LIVE CODE PATCH ***", 13, 10, 0
msg_patch_offset db "offset 0x", 0
msg_patch_bytes db " bytes ", 0
msg_patch_prompt db "press any key to CELEBRATE AND APPLY (Esc politely declines): ", 0
msg_applying db "applying patch... hold on...", 13, 10, 0
msg_patch_applied db "patch applied. beautiful chaos achieved.", 13, 10, 0
msg_patch_aborted db "patch aborted by human.", 13, 10, 0
msg_unknown_patch db "claude sent a malformed patch, ignoring it.", 13, 10, 0
msg_host_post_list db 'POST /host {"action":"list-sessions"', 0
msg_host_post_spawn_prefix db 'POST /host {"action":"spawn-session","session":"', 0
msg_host_post_spawn_mid db '","goal":"', 0
msg_host_post_retire_prefix db 'POST /host {"action":"retire-session","session":"', 0
msg_host_post_step_prefix db 'POST /host {"action":"step-session","session":"', 0
msg_host_post_step_mid db '","prompt":"', 0
msg_host_post_curl_prefix db 'POST /host {"action":"fetch-url","url":"', 0
msg_host_post_balance db 'POST /host {"action":"show-balance"', 0
msg_host_post_clone_prefix db 'POST /host {"action":"clone-session","session":"', 0
msg_host_post_adopt_prefix db 'POST /host {"action":"adopt-style","session":"', 0
msg_host_post_clone_mid db '","source_session":"', 0
msg_host_post_modifier_mid db '","modifier":"', 0
msg_generation_json_prefix db ',"generation":"0x', 0
msg_generation_json_suffix db '"', 0
msg_json_quote db '"', 0
msg_json_close db '}', 0
msg_graph_intro db "graph viewer", 13, 10, 0
msg_graph_mode_line db "mode 1: line y=x/4", 13, 10, 0
msg_graph_mode_parabola db "mode 2: parabola y=(x*x)/80+1", 13, 10, 0
msg_graph_mode_wave db "mode 3: triangle wave", 13, 10, 0
msg_graph_footer db "press 1, 2, or 3 to switch graphs; q or Esc returns", 13, 10, 0
msg_paint_intro db "paint: in the QEMU window hold left mouse to draw, c changes color, x clears, q or Esc exits", 13, 10, 0
msg_paint_exit db "leaving paint mode", 13, 10, 0
msg_paint_no_mouse db "mouse initialization failed", 13, 10, 0
msg_editor_intro db "editor: type into the scratch buffer, Backspace deletes, Esc returns to the monitor", 13, 10, 0
msg_editor_exit db "leaving editor", 13, 10, 0
prompt db "kernel_os> ", 0
prompt_calc db "calc> ", 0
prompt_chat db "chat> ", 0
prompt_curl db "url> ", 0
prompt_host_action db "host action> ", 0
prompt_task_session db "session> ", 0
prompt_task_goal db "goal> ", 0
prompt_task_source db "source session> ", 0
prompt_host_prompt db "prompt> ", 0
prompt_host_modifier db "modifier> ", 0
prompt_peek_offset db "offset hex> ", 0
prompt_peek_count db "count hex (1..20)> ", 0
newline db 13, 10, 0
cmd_help db "help", 0
cmd_hardware_list db "hardware_list", 0
cmd_memory_map db "memory_map", 0
cmd_calc db "calc", 0
cmd_chat db "chat", 0
cmd_curl db "curl", 0
cmd_show_balance db "show_balance", 0
cmd_hostreq db "hostreq", 0
cmd_task_spawn db "task_spawn", 0
cmd_task_list db "task_list", 0
cmd_task_retire db "task_retire", 0
cmd_task_step db "task_step", 0
cmd_graph db "graph", 0
cmd_paint db "paint", 0
cmd_edit db "edit", 0
cmd_peek db "peek", 0
cmd_clear db "clear", 0
cmd_about db "about", 0
cmd_halt db "halt", 0
cmd_reboot db "reboot", 0
cmd_exit db "exit", 0
curl_prefix db "/curl ", 0
loop_prefix db "/loop", 0
patch_prefix db "/patch ", 0
peek_prefix db "/peek ", 0
action_list_sessions db "list-sessions", 0
action_spawn_session db "spawn-session", 0
action_clone_session db "clone-session", 0
action_retire_session db "retire-session", 0
action_step_session db "step-session", 0
action_adopt_style db "adopt-style", 0
generation dd 1
chat_session_counter dd 0
chat_session_active db 0
chat_session_buffer times CHAT_SESSION_SIZE db 0
chat_loop_active db 0
chat_loop_steps db 0
chat_loop_resume db 0
patch_offset dw 0
patch_byte_count dw 0
patch_bytes times PATCH_MAX_BYTES db 0
peek_offset dw 0
peek_count dw 0
peek_token_buffer times 8 db 0
input_buffer times INPUT_MAX + 1 db 0
host_action_buffer times HOST_ACTION_SIZE db 0
task_session_buffer times TASK_NAME_SIZE db 0
task_source_buffer times TASK_NAME_SIZE db 0
task_goal_buffer times TASK_GOAL_SIZE db 0
task_arg_buffer times TASK_GOAL_SIZE db 0
task_active times TASK_SLOT_COUNT db 0
task_names times TASK_SLOT_COUNT * TASK_NAME_SIZE db 0
task_goals times TASK_SLOT_COUNT * TASK_GOAL_SIZE db 0
calc_op db 0
calc_left dw 0
calc_right dw 0
calc_result dw 0
graph_mode db 1
graph_char db 0
e820_continuation dd 0
e820_buffer times 20 db 0
mouse_packet db 0, 0, 0
mouse_packet_index db 0
mouse_color db 0
mouse_prev_under db 0
mouse_x dw 0
mouse_y dw 0
mouse_prev_x dw 0
mouse_prev_y dw 0
editor_length dw 0
editor_buffer times EDITOR_CAPACITY db 0
serial_line_buffer times SERIAL_LINE_MAX + 1 db 0
hex_digits db "0123456789ABCDEF"
keymap_unshifted:
    times 0x02 db 0
    db '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '='
    db 0x08
    db 0x09
    db 'q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[', ']'
    db 0x0d
    db 0
    db 'a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', 0x27, '`'
    db 0
    db 0x5c
    db 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '/'
    db 0
    db '*'
    db 0
    db ' '
    times (128 - ($ - keymap_unshifted)) db 0

keymap_shifted:
    times 0x02 db 0
    db '!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '_', '+'
    db 0x08
    db 0x09
    db 'Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P', '{', '}'
    db 0x0d
    db 0
    db 'A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', ':', 0x22, '~'
    db 0
    db '|'
    db 'Z', 'X', 'C', 'V', 'B', 'N', 'M', '<', '>', '?'
    db 0
    db '*'
    db 0
    db ' '
    times (128 - ($ - keymap_shifted)) db 0
