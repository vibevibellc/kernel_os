hardware_list:
    call set_text_mode
    mov si, msg_hardware_header
    call print_string

    int 0x11
    mov [hardware_equipment_word], ax
    mov si, msg_hardware_equipment
    call print_string
    mov ax, [hardware_equipment_word]
    call print_hex_word_safe
    mov si, newline
    call print_string

    int 0x12
    mov si, msg_hardware_base_memory
    call print_string
    call print_uint_ax
    mov si, msg_hardware_kb_suffix
    call print_string

    call refresh_text_console_metrics
    mov si, msg_hardware_video
    call print_string
    xor ax, ax
    mov al, [hardware_video_mode]
    call print_hex_byte_safe
    mov si, msg_hardware_video_cols
    call print_string
    xor ax, ax
    mov al, [hardware_video_cols]
    call print_uint_ax
    mov si, msg_hardware_video_rows
    call print_string
    xor ax, ax
    mov al, [hardware_video_rows]
    call print_uint_ax
    mov si, msg_hardware_video_page
    call print_string
    xor ax, ax
    mov al, [hardware_video_page]
    call print_uint_ax
    mov si, newline
    call print_string

    call hardware_probe_e820
    call hardware_list_serial_ports
    call hardware_list_parallel_ports
    call hardware_list_drives
    call hardware_probe_mouse
    ret

hardware_probe_e820:
    mov si, msg_hardware_e820_prefix
    call print_string

    push ds
    push es
    mov di, e820_buffer
    xor ebx, ebx
    mov eax, 0x0000E820
    mov edx, 0x534D4150
    mov ecx, 20
    int 0x15
    pop es
    pop ds
    jc .unavailable
    cmp eax, 0x534D4150
    jne .unavailable
    mov si, msg_hardware_available
    call print_string
    ret

.unavailable:
    mov si, msg_hardware_unavailable
    call print_string
    ret

hardware_list_serial_ports:
    mov si, msg_hardware_serial_header
    call print_string
    mov byte [hardware_port_count], 0

    push es
    mov ax, 0x0040
    mov es, ax

    xor bx, bx
    mov cx, 4

.port_loop:
    mov ax, [es:bx]
    test ax, ax
    jz .next
    inc byte [hardware_port_count]
    mov si, msg_hardware_com_prefix
    call print_string
    mov ax, 4
    sub ax, cx
    inc ax
    call print_uint_ax
    mov si, msg_hardware_base_prefix
    call print_string
    mov ax, [es:bx]
    call print_hex_word_safe
    mov si, newline
    call print_string

.next:
    add bx, 2
    loop .port_loop

    pop es
    cmp byte [hardware_port_count], 0
    jne .done
    mov si, msg_hardware_none
    call print_string

.done:
    ret

hardware_list_parallel_ports:
    mov si, msg_hardware_parallel_header
    call print_string
    mov byte [hardware_port_count], 0

    push es
    mov ax, 0x0040
    mov es, ax

    mov bx, 8
    mov cx, 3

.port_loop:
    mov ax, [es:bx]
    test ax, ax
    jz .next
    inc byte [hardware_port_count]
    mov si, msg_hardware_lpt_prefix
    call print_string
    mov ax, 3
    sub ax, cx
    inc ax
    call print_uint_ax
    mov si, msg_hardware_base_prefix
    call print_string
    mov ax, [es:bx]
    call print_hex_word_safe
    mov si, newline
    call print_string

.next:
    add bx, 2
    loop .port_loop

    pop es
    cmp byte [hardware_port_count], 0
    jne .done
    mov si, msg_hardware_none
    call print_string

.done:
    ret

hardware_list_drives:
    mov si, msg_hardware_drive_header
    call print_string
    mov byte [hardware_drive_count], 0

    mov dl, 0x00
    call hardware_probe_drive
    mov dl, 0x01
    call hardware_probe_drive
    mov dl, 0x80
    call hardware_probe_drive
    mov dl, 0x81
    call hardware_probe_drive

    cmp byte [hardware_drive_count], 0
    jne .done
    mov si, msg_hardware_none
    call print_string

.done:
    ret

hardware_probe_drive:
    push ax
    push bx
    push cx
    push dx

    mov [hardware_drive_id], dl
    mov ah, 0x08
    int 0x13
    jc .done

    inc byte [hardware_drive_count]
    mov si, msg_hardware_drive_prefix
    call print_string
    mov al, [hardware_drive_id]
    call print_hex_byte_safe
    test byte [hardware_drive_id], 0x80
    jnz .fixed
    mov si, msg_hardware_drive_floppy
    call print_string
    jmp .done

.fixed:
    mov si, msg_hardware_drive_fixed
    call print_string

.done:
    pop dx
    pop cx
    pop bx
    pop ax
    ret

hardware_probe_mouse:
    mov si, msg_hardware_mouse_prefix
    call print_string
    call mouse_init
    jc .unavailable
    mov si, msg_hardware_available
    call print_string
    ret

.unavailable:
    mov si, msg_hardware_unavailable
    call print_string
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
    call build_kernel_safe_memory_ranges
    jc .done
    call print_kernel_safe_memory_ranges
    ret

.finish:
    cmp bp, 0
    jne .have_map

.unsupported:
    mov si, msg_memory_map_unavailable
    call print_string

.done:
    ret

.have_map:
    call build_kernel_safe_memory_ranges
    jc .done
    call print_kernel_safe_memory_ranges
    ret

build_kernel_safe_memory_ranges:
    push ax
    push bx
    push cx
    push dx
    push si
    push di

    mov byte [safe_range_count], 0
    xor eax, eax
    int 0x12
    shl eax, 10
    cmp eax, LOW_MEMORY_LIMIT
    jbe .store_lowmem_top
    mov eax, LOW_MEMORY_LIMIT

.store_lowmem_top:
    mov [kernel_safe_lowmem_top], eax
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
    jc .bios_done
    cmp eax, 0x534D4150
    jne .unsupported

    mov [e820_continuation], ebx
    cmp dword [e820_buffer + 16], 1
    jne .advance
    cmp dword [e820_buffer + 4], 0
    jne .advance
    cmp dword [e820_buffer + 12], 0
    jne .advance

    mov esi, [e820_buffer]
    mov edi, [e820_buffer + 8]
    add edi, esi
    jc .advance
    call subtract_kernel_reserved_ranges

.advance:
    mov ebx, [e820_continuation]
    test ebx, ebx
    jne .next_entry

.bios_done:
    clc
    jmp .exit

.unsupported:
    stc

.exit:
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    pop ax
    ret

subtract_kernel_reserved_ranges:
    cmp esi, edi
    jae .done

    xor eax, eax
    mov edx, LOW_BIOS_RESERVED_END
    call subtract_reserved_range32
    cmp esi, edi
    jae .done

    mov eax, PM32_STACK_TOP
    xor edx, edx
    mov dx, stage2_image_end
    call subtract_reserved_range32
    cmp esi, edi
    jae .done

    mov eax, [kernel_safe_lowmem_top]
    mov edx, LOW_MEMORY_LIMIT
    call subtract_reserved_range32
    cmp esi, edi
    jae .done

    call append_safe_range32

.done:
    ret

subtract_reserved_range32:
    cmp esi, edi
    jae .done
    cmp edi, eax
    jbe .done
    cmp esi, edx
    jae .done
    cmp eax, esi
    jbe .clip_front
    cmp edx, edi
    jae .clip_back

    push eax
    push edx
    push edi
    mov edi, eax
    call append_safe_range32
    pop edi
    pop edx
    pop eax
    mov esi, edx
    ret

.clip_front:
    cmp edx, edi
    jae .clear
    mov esi, edx
    ret

.clip_back:
    mov edi, eax
    ret

.clear:
    mov esi, edi

.done:
    ret

append_safe_range32:
    push bx
    push dx

    cmp esi, edi
    jae .done
    mov bl, [safe_range_count]
    cmp bl, SAFE_RANGE_MAX
    jae .done

    xor bh, bh
    shl bx, 2
    mov [safe_range_bases + bx], esi
    mov edx, edi
    sub edx, esi
    mov [safe_range_lengths + bx], edx
    inc byte [safe_range_count]

.done:
    pop dx
    pop bx
    ret

print_kernel_safe_memory_ranges:
    push bx
    push bp
    push di
    push si
    push eax

    mov si, msg_memory_safe_header
    call print_string
    cmp byte [safe_range_count], 0
    jne .loop_setup
    mov si, msg_memory_safe_none
    call print_string
    jmp .done

.loop_setup:
    xor bx, bx
    xor bp, bp

.loop:
    cmp bl, [safe_range_count]
    jae .done

    inc bp
    mov al, '#'
    call print_char
    mov ax, bp
    call print_uint_ax
    mov si, msg_base
    call print_string
    xor eax, eax
    call print_hex32_eax
    mov di, bx
    shl di, 2
    mov eax, [safe_range_bases + di]
    call print_hex32_eax
    mov si, msg_length
    call print_string
    xor eax, eax
    call print_hex32_eax
    mov eax, [safe_range_lengths + di]
    call print_hex32_eax
    mov si, newline
    call print_string
    inc bx
    jmp .loop

.done:
    pop eax
    pop si
    pop di
    pop bp
    pop bx
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
    mov si, input_buffer
    call skip_spaces
    cmp byte [si], 0
    je .exit

    mov di, cmd_exit
    call streq
    cmp al, 1
    je .exit

    mov si, input_buffer
    call parse_signed_int
    jc .parse_error
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
    jc .parse_error
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
    jo .overflow
    jmp .result

.sub:
    sub ax, bx
    jo .overflow
    jmp .result

.mul:
    imul bx
    jo .overflow
    jmp .result

.div:
    cmp bx, 0
    je .div_zero
    cmp ax, 0x8000
    jne .div_ready
    cmp bx, -1
    je .overflow
.div_ready:
    cwd
    idiv bx
    jmp .result

.mod:
    cmp bx, 0
    je .div_zero
    cmp ax, 0x8000
    jne .mod_ready
    cmp bx, -1
    jne .mod_ready
    xor ax, ax
    jmp .result
.mod_ready:
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

.parse_error:
    cmp ax, 1
    je .overflow

.syntax:
    mov si, msg_calc_syntax
    call print_string
    jmp .loop

.overflow:
    mov si, msg_calc_overflow
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
    mov byte [chat_fresh_needed], 1
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
    mov byte [chat_fresh_needed], 0
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
    cmp byte [chat_fresh_needed], 1
    jne .close
    mov si, msg_chat_post_fresh
    call serial_write_string

.close:
    mov si, msg_json_close
    call serial_write_string
    mov si, newline
    call serial_write_string
    mov byte [chat_fresh_needed], 0
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
    ret

.allocate:
    inc dword [chat_session_counter]
    mov di, chat_session_buffer
    mov cx, CHAT_SESSION_SIZE
    xor al, al
    rep stosb
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
    mov byte [chat_fresh_needed], 1
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

    mov si, host_action_buffer
    mov di, action_git_sync
    call streq
    cmp al, 1
    je .do_git_sync

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

.do_git_sync:
    call host_send_git_sync_request
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

ramlist_program:
    call ramlist_init
    mov si, msg_ramlist_intro
    call print_string

.loop:
    mov si, prompt_ramlist
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
    mov di, cmd_ramlist_push
    call streq
    cmp al, 1
    je .push

    mov si, input_buffer
    mov di, cmd_ramlist_pop
    call streq
    cmp al, 1
    je .pop

    mov si, input_buffer
    mov di, cmd_ramlist_show
    call streq
    cmp al, 1
    je .show

    mov si, input_buffer
    mov di, cmd_ramlist_clear
    call streq
    cmp al, 1
    je .clear

    mov si, msg_ramlist_unknown
    call print_string
    jmp .loop

.push:
    mov si, prompt_ramlist_value
    call print_string
    mov di, input_buffer
    mov cx, INPUT_MAX
    call read_line
    cmp byte [input_buffer], 0
    je .loop
    mov si, input_buffer
    call parse_signed_int
    jc .bad_value
    call ramlist_push_ax
    jc .full
    mov si, msg_ramlist_pushed
    call print_string
    jmp .loop

.pop:
    call ramlist_pop_ax
    jc .empty
    mov si, msg_ramlist_popped
    call print_string
    call print_int_ax
    mov si, newline
    call print_string
    jmp .loop

.show:
    call ramlist_show
    jmp .loop

.clear:
    call ramlist_reset
    mov si, msg_ramlist_cleared
    call print_string
    jmp .loop

.bad_value:
    mov si, msg_ramlist_bad_value
    call print_string
    jmp .loop

.full:
    mov si, msg_ramlist_full
    call print_string
    jmp .loop

.empty:
    mov si, msg_ramlist_empty
    call print_string
    jmp .loop

.exit:
    mov si, msg_ramlist_exit
    call print_string
    ret

screen_program:
    mov si, msg_screen_intro
    call print_string

.loop:
    mov si, prompt_screen
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
    mov di, cmd_screen_status
    call streq
    cmp al, 1
    je .status

    mov si, input_buffer
    mov di, cmd_screen_on
    call streq
    cmp al, 1
    je .on

    mov si, input_buffer
    mov di, cmd_screen_off
    call streq
    cmp al, 1
    je .off

    mov si, input_buffer
    mov di, cmd_screen_clear
    call streq
    cmp al, 1
    je .clear

    mov si, msg_screen_unknown
    call print_string
    jmp .loop

.status:
    mov si, msg_screen_status_prefix
    call print_string
    cmp byte [monitor_auto_clear], 1
    je .status_on
    mov si, msg_screen_off_state
    call print_string
    jmp .loop

.status_on:
    mov si, msg_screen_on_state
    call print_string
    jmp .loop

.on:
    mov byte [monitor_auto_clear], 1
    mov si, msg_screen_enabled
    call print_string
    jmp .loop

.off:
    mov byte [monitor_auto_clear], 0
    mov si, msg_screen_disabled
    call print_string
    jmp .loop

.clear:
    call clear_console
    jmp .loop

.exit:
    mov si, msg_screen_exit
    call print_string
    ret

ramlist_init:
    cmp byte [ramlist_initialized], 1
    je .done
    call ramlist_reset
    mov byte [ramlist_initialized], 1
.done:
    ret

ramlist_reset:
    mov byte [ramlist_head], 0xff
    mov byte [ramlist_tail], 0xff
    mov byte [ramlist_free_head], 0
    mov byte [ramlist_count], 0
    xor bx, bx

.link_free:
    mov al, bl
    inc al
    mov [ramlist_next + bx], al
    inc bx
    cmp bl, RAMLIST_NODE_COUNT
    jb .link_free
    mov byte [ramlist_next + RAMLIST_NODE_COUNT - 1], 0xff
    ret

ramlist_push_ax:
    push bx
    push cx
    push dx
    mov bl, [ramlist_free_head]
    cmp bl, 0xff
    je .full
    xor bh, bh
    mov dl, [ramlist_next + bx]
    mov [ramlist_free_head], dl
    mov cx, bx
    shl bx, 1
    mov [ramlist_values + bx], ax
    mov bx, cx
    mov byte [ramlist_next + bx], 0xff
    cmp byte [ramlist_head], 0xff
    jne .append
    mov [ramlist_head], bl
    mov [ramlist_tail], bl
    jmp .done

.append:
    push si
    xor ax, ax
    mov al, [ramlist_tail]
    mov si, ax
    mov [ramlist_next + si], bl
    pop si
    mov [ramlist_tail], bl

.done:
    inc byte [ramlist_count]
    clc
    jmp .return

.full:
    stc

.return:
    pop dx
    pop cx
    pop bx
    ret

ramlist_pop_ax:
    push bx
    push cx
    push dx
    mov bl, [ramlist_head]
    cmp bl, 0xff
    je .empty
    xor bh, bh
    mov dl, [ramlist_next + bx]
    mov [ramlist_head], dl
    cmp dl, 0xff
    jne .load_value
    mov byte [ramlist_tail], 0xff

.load_value:
    mov cx, bx
    shl bx, 1
    mov ax, [ramlist_values + bx]
    mov bx, cx
    mov dl, [ramlist_free_head]
    mov [ramlist_next + bx], dl
    mov [ramlist_free_head], bl
    dec byte [ramlist_count]
    clc
    jmp .return

.empty:
    stc

.return:
    pop dx
    pop cx
    pop bx
    ret

ramlist_show:
    push ax
    push bx
    push cx
    mov si, msg_ramlist_show
    call print_string
    mov bl, [ramlist_head]
    cmp bl, 0xff
    jne .loop
    mov si, msg_ramlist_none
    call print_string
    jmp .done

.loop:
    xor bh, bh
    mov ax, bx
    inc ax
    call print_uint_ax
    mov si, msg_ramlist_item_sep
    call print_string
    mov cx, bx
    shl bx, 1
    mov ax, [ramlist_values + bx]
    call print_int_ax
    mov si, newline
    call print_string
    mov bx, cx
    mov bl, [ramlist_next + bx]
    cmp bl, 0xff
    jne .loop

.done:
    pop cx
    pop bx
    pop ax
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

parse_stream:
    call skip_spaces
    mov word [patch_byte_count], 0

.next_byte:
    call skip_spaces
    cmp byte [si], 0
    je .done
    call parse_hex_byte
    jc .fail
    mov bx, [patch_byte_count]
    cmp bx, STREAM_MAX_BYTES
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

parse_peek_page_args:
    call skip_spaces
    call parse_hex_word
    jc .fail
    push bx
    call skip_spaces
    call parse_hex_word
    jc .fail_pop
    mov ax, bx
    mov cx, PEEK_MAX_BYTES
    mul cx
    pop bx
    test dx, dx
    jne .fail
    add ax, bx
    jc .fail
    mov [peek_offset], ax
    mov word [peek_count], PEEK_MAX_BYTES
    call skip_spaces
    cmp byte [si], 0
    jne .fail
    clc
    ret

.fail_pop:
    pop bx
.fail:
    stc
    ret

peek_dump:
    push ax
    push bx
    push cx
    push si
    call navigator_configure_memory_hex
    mov ax, [peek_offset]
    mov [navigator_cursor], ax
    mov ax, [peek_count]
    mov [navigator_window], ax
    mov si, msg_peek_header
    call navigator_render_hex_with_prefix

.done:
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

execute_live_stream:
    push ax
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push ds
    push es
    mov bx, [patch_byte_count]
    mov byte [patch_bytes + bx], 0xC3
    call patch_bytes
    mov [patch_offset], ax
    pop es
    pop ds
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    pop ax
    mov si, msg_stream_result
    call print_string
    mov ax, [patch_offset]
    call print_hex_word_safe
    mov si, newline
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
    mov di, sys_retired_prefix
    call strprefix
    cmp al, 1
    jne .print_text
    mov byte [chat_session_active], 0
    mov byte [chat_session_buffer], 0
    mov byte [chat_fresh_needed], 0
    mov byte [chat_loop_steps], 0
    mov byte [chat_loop_resume], 0
    mov si, serial_line_buffer
    call print_string
    mov si, newline
    call print_string
    jmp do_halt

.print_text:
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
    mov di, stream_prefix
    call strprefix
    cmp al, 1
    je .stream
    mov si, serial_line_buffer + 5
    mov di, peek_page_prefix
    call strprefix
    cmp al, 1
    je .peek_page
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
    call apply_live_patch
    call bump_generation
.patch_done:
    call chat_enable_continuation
    mov al, 2
    ret

.patch_invalid:
    mov byte [chat_loop_active], 0
    mov si, msg_unknown_patch
    call print_string
    mov al, 1
    ret

.stream:
    mov si, serial_line_buffer + 13
    call parse_stream
    jc .stream_invalid
    call execute_live_stream
    call chat_enable_continuation
    xor al, al
    ret

.stream_invalid:
    mov byte [chat_loop_active], 0
    mov si, msg_stream_bad
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
.curl_done:
    call chat_enable_continuation
    xor al, al
    ret

.curl_invalid:
    mov byte [chat_loop_active], 0
    mov si, msg_curl_bad
    call print_string
    mov al, 1
    ret

.peek_page:
    mov si, serial_line_buffer + 15
    call parse_peek_page_args
    jc .peek_page_invalid
    call peek_dump
.peek_page_done:
    call chat_enable_continuation
    xor al, al
    ret

.peek_page_invalid:
    mov byte [chat_loop_active], 0
    mov si, msg_peek_page_bad
    call print_string
    mov al, 1
    ret

.peek:
    mov si, serial_line_buffer + 11
    call parse_peek_args
    jc .peek_invalid
    call peek_dump
.peek_done:
    call chat_enable_continuation
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
    call chat_command_should_auto_continue
    cmp al, 1
    jne .success_done

    call chat_enable_continuation

.success_done:
    xor al, al
    ret

chat_enable_continuation:
    cmp byte [chat_loop_resume], 1
    je .enable
    mov byte [chat_loop_steps], 0

.enable:
    mov byte [chat_loop_active], 1

    ret

chat_command_should_auto_continue:
    mov si, input_buffer
    mov di, cmd_hardware_list
    call streq
    cmp al, 1
    je .yes

    mov si, input_buffer
    mov di, cmd_memory_map
    call streq
    cmp al, 1
    je .yes

    mov si, input_buffer
    mov di, cmd_task_list
    call streq
    cmp al, 1
    je .yes

    mov si, input_buffer
    mov di, cmd_grep
    call streq
    cmp al, 1
    je .yes

    mov si, input_buffer
    mov di, cmd_pm32
    call streq
    cmp al, 1
    je .yes

    xor al, al
    ret

.yes:
    mov al, 1
    ret

host_send_list_request:
    mov di, host_request_buffer
    mov si, msg_host_post_list
    call buffer_write_string
    call buffer_write_generation_field
    mov si, msg_json_close
    call buffer_write_string
    mov si, newline
    call buffer_write_string
    mov byte [di], 0
    call serial_write_buffer
    ret

host_send_spawn_request:
    mov di, host_request_buffer
    mov si, msg_host_post_spawn_prefix
    call buffer_write_string
    mov si, task_session_buffer
    call buffer_write_json_escaped
    mov si, msg_host_post_spawn_mid
    call buffer_write_string
    mov si, task_goal_buffer
    call buffer_write_json_escaped
    mov si, msg_json_quote
    call buffer_write_string
    call buffer_write_generation_field
    mov si, msg_json_close
    call buffer_write_string
    mov si, newline
    call buffer_write_string
    mov byte [di], 0
    call serial_write_buffer
    ret

host_send_retire_request:
    mov di, host_request_buffer
    mov si, msg_host_post_retire_prefix
    call buffer_write_string
    mov si, task_session_buffer
    call buffer_write_json_escaped
    mov si, msg_json_quote
    call buffer_write_string
    call buffer_write_generation_field
    mov si, msg_json_close
    call buffer_write_string
    mov si, newline
    call buffer_write_string
    mov byte [di], 0
    call serial_write_buffer
    ret

host_send_retire_named:
    push si
    mov di, host_request_buffer
    mov si, msg_host_post_retire_prefix
    call buffer_write_string
    pop si
    call buffer_write_json_escaped
    mov si, msg_json_quote
    call buffer_write_string
    call buffer_write_generation_field
    mov si, msg_json_close
    call buffer_write_string
    mov si, newline
    call buffer_write_string
    mov byte [di], 0
    call serial_write_buffer
    ret

host_send_step_request:
    mov di, host_request_buffer
    mov si, msg_host_post_step_prefix
    call buffer_write_string
    mov si, task_session_buffer
    call buffer_write_json_escaped
    mov si, msg_host_post_step_mid
    call buffer_write_string
    mov si, task_arg_buffer
    call buffer_write_json_escaped
    mov si, msg_json_quote
    call buffer_write_string
    call buffer_write_generation_field
    mov si, msg_json_close
    call buffer_write_string
    mov si, newline
    call buffer_write_string
    mov byte [di], 0
    call serial_write_buffer
    ret

host_send_curl_request:
    mov di, host_request_buffer
    mov si, msg_host_post_curl_prefix
    call buffer_write_string
    mov si, task_arg_buffer
    call buffer_write_json_escaped
    mov si, msg_json_quote
    call buffer_write_string
    call buffer_write_generation_field
    mov si, msg_json_close
    call buffer_write_string
    mov si, newline
    call buffer_write_string
    mov byte [di], 0
    call serial_write_buffer
    ret

host_send_git_sync_request:
    mov di, host_request_buffer
    mov si, msg_host_post_git_sync
    call buffer_write_string
    call buffer_write_generation_field
    mov si, msg_json_close
    call buffer_write_string
    mov si, newline
    call buffer_write_string
    mov byte [di], 0
    call serial_write_buffer
    ret

host_send_clone_request:
    mov di, host_request_buffer
    mov si, msg_host_post_clone_prefix
    call buffer_write_string
    mov si, task_session_buffer
    call buffer_write_json_escaped
    mov si, msg_host_post_clone_mid
    call buffer_write_string
    mov si, task_source_buffer
    call buffer_write_json_escaped
    mov si, msg_host_post_modifier_mid
    call buffer_write_string
    mov si, task_arg_buffer
    call buffer_write_json_escaped
    mov si, msg_json_quote
    call buffer_write_string
    call buffer_write_generation_field
    mov si, msg_json_close
    call buffer_write_string
    mov si, newline
    call buffer_write_string
    mov byte [di], 0
    call serial_write_buffer
    ret

host_send_adopt_request:
    mov di, host_request_buffer
    mov si, msg_host_post_adopt_prefix
    call buffer_write_string
    mov si, task_session_buffer
    call buffer_write_json_escaped
    mov si, msg_host_post_clone_mid
    call buffer_write_string
    mov si, task_source_buffer
    call buffer_write_json_escaped
    mov si, msg_host_post_modifier_mid
    call buffer_write_string
    mov si, task_arg_buffer
    call buffer_write_json_escaped
    mov si, msg_json_quote
    call buffer_write_string
    call buffer_write_generation_field
    mov si, msg_json_close
    call buffer_write_string
    mov si, newline
    call buffer_write_string
    mov byte [di], 0
    call serial_write_buffer
    ret
