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

grep_program:
    call set_text_mode
    mov si, msg_grep_intro
    call print_string
    call navigator_configure_editor_text
    cmp word [editor_length], 0
    jne .search
    mov si, msg_grep_empty
    call print_string
    ret

.search:
    call navigator_prompt_search
    ret

search_program:
    call set_text_mode
    call navigator_prompt_search
    ret

next_program:
    call set_text_mode
    call navigator_next_match
    ret

prev_program:
    call set_text_mode
    call navigator_prev_match
    ret

forward_program:
    call set_text_mode
    call navigator_move_forward
    ret

back_program:
    call set_text_mode
    call navigator_move_back
    ret

view_program:
    call set_text_mode
    call navigator_view_current_window
    ret

navigator_configure_editor_text:
    xor ax, ax
    mov byte [navigator_source], NAV_SOURCE_EDITOR
    mov byte [navigator_render_mode], NAV_RENDER_TEXT
    mov byte [navigator_match_active], 0
    mov [navigator_cursor], ax
    mov word [navigator_window], NAV_TEXT_WINDOW
    mov [navigator_match_offset], ax
    mov [navigator_needle_length], ax
    ret

navigator_configure_memory_hex:
    xor ax, ax
    mov byte [navigator_source], NAV_SOURCE_MEMORY
    mov byte [navigator_render_mode], NAV_RENDER_HEX
    mov byte [navigator_match_active], 0
    mov [navigator_cursor], ax
    mov word [navigator_window], NAV_HEX_WINDOW
    mov [navigator_match_offset], ax
    mov [navigator_needle_length], ax
    ret

navigator_prompt_search:
    call navigator_require_source
    jc .done
    call navigator_get_source_span
    jc .done
    test ax, ax
    jnz .prompt
    mov si, msg_view_empty
    call print_string
    ret

.prompt:
    mov si, prompt_search
    call print_string
    mov di, input_buffer
    mov cx, INPUT_MAX
    call read_line
    cmp byte [input_buffer], 0
    je .done
    call navigator_store_needle_from_input
    jc .done
    call navigator_search_first

.done:
    ret

navigator_store_needle_from_input:
    push ax
    push bx
    push cx
    push dx
    push si
    push di
    mov si, input_buffer
    cmp byte [si], '0'
    jne .find_space
    mov al, [si + 1]
    or al, 0x20
    cmp al, 'x'
    je .hex

.find_space:
    mov di, si

.space_loop:
    mov al, [di]
    test al, al
    jz .literal
    cmp al, ' '
    je .hex
    inc di
    jmp .space_loop

.hex:
    mov si, input_buffer
    xor bx, bx

.hex_loop:
    call skip_spaces
    cmp byte [si], 0
    je .hex_done
    push si
    call parse_hex_byte
    jc .hex_fail
    pop dx
    cmp bx, NAV_NEEDLE_MAX
    jae .too_long
    mov [navigator_needle + bx], al
    inc bx
    jmp .hex_loop

.hex_done:
    test bx, bx
    jz .literal
    mov [navigator_needle_length], bx
    clc
    jmp .done

.hex_fail:
    pop si

.literal:
    mov si, input_buffer
    xor bx, bx

.literal_loop:
    mov al, [si]
    test al, al
    jz .literal_done
    cmp bx, NAV_NEEDLE_MAX
    jae .too_long
    mov [navigator_needle + bx], al
    inc si
    inc bx
    jmp .literal_loop

.literal_done:
    mov [navigator_needle_length], bx
    clc
    jmp .done

.too_long:
    mov si, msg_search_long
    call print_string
    stc

.done:
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    pop ax
    ret

navigator_search_first:
    call navigator_require_source
    jc .done
    call navigator_require_pattern
    jc .done
    call navigator_get_source_span
    jc .done
    test ax, ax
    jnz .search
    mov si, msg_view_empty
    call print_string
    ret

.search:
    xor dx, dx
    call navigator_find_forward_from_dx
    jc .not_found
    call navigator_center_on_match
    call navigator_view_current_window
    ret

.not_found:
    mov si, msg_search_none
    call print_string

.done:
    ret

navigator_next_match:
    call navigator_require_source
    jc .done
    call navigator_require_pattern
    jc .done
    call navigator_get_source_span
    jc .done
    test ax, ax
    jnz .search
    mov si, msg_view_empty
    call print_string
    ret

.search:
    mov dx, [navigator_cursor]
    cmp byte [navigator_match_active], 1
    jne .find
    mov dx, [navigator_match_offset]

.find:
    inc dx
    call navigator_find_forward_from_dx
    jc .not_found
    call navigator_center_on_match
    call navigator_view_current_window
    ret

.not_found:
    mov si, msg_search_none
    call print_string

.done:
    ret

navigator_prev_match:
    call navigator_require_source
    jc .done
    call navigator_require_pattern
    jc .done
    call navigator_get_source_span
    jc .done
    test ax, ax
    jnz .search
    mov si, msg_view_empty
    call print_string
    ret

.search:
    mov dx, [navigator_cursor]
    cmp byte [navigator_match_active], 1
    jne .find
    mov dx, [navigator_match_offset]
    test dx, dx
    jz .not_found
    dec dx

.find:
    call navigator_find_backward_from_dx
    jc .not_found
    call navigator_center_on_match
    call navigator_view_current_window
    ret

.not_found:
    mov si, msg_search_none
    call print_string

.done:
    ret

navigator_move_forward:
    call navigator_require_source
    jc .done
    call navigator_get_source_span
    jc .done
    test ax, ax
    jnz .move
    mov si, msg_view_empty
    call print_string
    ret

.move:
    call navigator_clamp_view_state
    call navigator_get_source_span
    mov dx, [navigator_cursor]
    mov cx, [navigator_window]
    add dx, cx
    mov bx, ax
    sub bx, cx
    cmp dx, bx
    jbe .store
    mov dx, bx

.store:
    mov [navigator_cursor], dx
    mov byte [navigator_match_active], 0
    call navigator_view_current_window

.done:
    ret

navigator_move_back:
    call navigator_require_source
    jc .done
    call navigator_get_source_span
    jc .done
    test ax, ax
    jnz .move
    mov si, msg_view_empty
    call print_string
    ret

.move:
    call navigator_clamp_view_state
    mov dx, [navigator_cursor]
    mov cx, [navigator_window]
    cmp dx, cx
    jae .subtract
    xor dx, dx
    jmp .store

.subtract:
    sub dx, cx

.store:
    mov [navigator_cursor], dx
    mov byte [navigator_match_active], 0
    call navigator_view_current_window

.done:
    ret

navigator_view_current_window:
    call navigator_require_source
    jc .done
    call navigator_get_source_span
    jc .done
    test ax, ax
    jnz .render
    mov si, msg_view_empty
    call print_string
    ret

.render:
    call navigator_clamp_view_state
    cmp byte [navigator_render_mode], NAV_RENDER_TEXT
    je .text
    mov si, msg_view_hex_header
    call navigator_render_hex_with_prefix
    ret

.text:
    call navigator_render_text_window

.done:
    ret

navigator_require_source:
    cmp byte [navigator_source], NAV_SOURCE_NONE
    jne .ok
    mov si, msg_navigator_none
    call print_string
    stc
    ret

.ok:
    clc
    ret

navigator_require_pattern:
    cmp word [navigator_needle_length], 0
    jne .ok
    mov si, msg_search_needed
    call print_string
    stc
    ret

.ok:
    clc
    ret

navigator_get_source_span:
    cmp byte [navigator_source], NAV_SOURCE_EDITOR
    je .editor
    cmp byte [navigator_source], NAV_SOURCE_MEMORY
    je .memory
    stc
    ret

.editor:
    mov bx, editor_buffer
    mov ax, [editor_length]
    clc
    ret

.memory:
    mov bx, 0x8000
    mov ax, stage2_image_end - 0x8000
    clc
    ret

navigator_clamp_view_state:
    push ax
    push bx
    push cx
    push dx
    call navigator_get_source_span
    jc .done
    mov cx, [navigator_window]
    test cx, cx
    jnz .have_window
    cmp byte [navigator_render_mode], NAV_RENDER_TEXT
    jne .hex_default
    mov cx, NAV_TEXT_WINDOW
    jmp .set_window

.hex_default:
    mov cx, NAV_HEX_WINDOW

.set_window:
    mov [navigator_window], cx

.have_window:
    cmp cx, ax
    jbe .window_ok
    mov cx, ax
    mov [navigator_window], cx

.window_ok:
    mov dx, [navigator_cursor]
    mov bx, ax
    sub bx, cx
    cmp dx, bx
    jbe .done
    mov [navigator_cursor], bx

.done:
    pop dx
    pop cx
    pop bx
    pop ax
    ret

navigator_find_forward_from_dx:
    push ax
    push bx
    push cx
    call navigator_get_source_span
    jc .not_found
    mov cx, [navigator_needle_length]
    cmp cx, ax
    ja .not_found
    sub ax, cx
    cmp dx, ax
    ja .not_found

.loop:
    push ax
    call navigator_candidate_matches
    pop ax
    jnc .found
    inc dx
    cmp dx, ax
    jbe .loop

.not_found:
    stc
    jmp .done

.found:
    clc

.done:
    pop cx
    pop bx
    pop ax
    ret

navigator_find_backward_from_dx:
    push ax
    push bx
    push cx
    call navigator_get_source_span
    jc .not_found
    mov cx, [navigator_needle_length]
    cmp cx, ax
    ja .not_found
    sub ax, cx
    cmp dx, ax
    jbe .loop
    mov dx, ax

.loop:
    call navigator_candidate_matches
    jnc .found
    test dx, dx
    jz .not_found
    dec dx
    jmp .loop

.not_found:
    stc
    jmp .done

.found:
    clc

.done:
    pop cx
    pop bx
    pop ax
    ret

navigator_candidate_matches:
    push ax
    push cx
    push si
    push di
    mov si, navigator_needle
    mov di, bx
    add di, dx
    mov cx, [navigator_needle_length]

.loop:
    test cx, cx
    jz .match
    mov al, [si]
    cmp al, [di]
    jne .miss
    inc si
    inc di
    dec cx
    jmp .loop

.match:
    clc
    jmp .done

.miss:
    stc

.done:
    pop di
    pop si
    pop cx
    pop ax
    ret

navigator_center_on_match:
    push ax
    push bx
    push cx
    push si
    mov [navigator_match_offset], dx
    mov byte [navigator_match_active], 1
    call navigator_clamp_view_state
    call navigator_get_source_span
    jc .done
    mov cx, [navigator_window]
    mov bx, ax
    sub bx, cx
    mov ax, dx
    mov si, cx
    shr si, 1
    cmp ax, si
    jae .subtract
    xor ax, ax
    jmp .clip

.subtract:
    sub ax, si

.clip:
    cmp ax, bx
    jbe .store
    mov ax, bx

.store:
    mov [navigator_cursor], ax

.done:
    pop si
    pop cx
    pop bx
    pop ax
    ret

navigator_render_hex_with_prefix:
    push ax
    push bx
    push cx
    push dx
    push di
    mov di, si
    call navigator_clamp_view_state
    call navigator_get_source_span
    jc .done
    mov si, di
    call print_string
    mov ax, [navigator_cursor]
    call print_hex_word_safe
    mov si, msg_peek_mid
    call print_string
    mov dx, [navigator_cursor]
    add bx, dx
    mov cx, [navigator_window]

.byte_loop:
    test cx, cx
    jz .newline
    mov al, [bx]
    call print_hex_byte_safe
    dec cx
    inc bx
    test cx, cx
    jz .newline
    mov al, ' '
    call print_char
    jmp .byte_loop

.newline:
    mov si, newline
    call print_string

.done:
    pop di
    pop dx
    pop cx
    pop bx
    pop ax
    ret

navigator_render_text_window:
    push ax
    push bx
    push cx
    push dx
    push si
    call navigator_clamp_view_state
    call navigator_get_source_span
    jc .done
    mov si, msg_view_text_header
    call print_string
    mov ax, [navigator_cursor]
    call print_hex_word_safe
    mov si, msg_peek_mid
    call print_string
    mov dx, [navigator_cursor]
    add bx, dx
    mov cx, [navigator_window]

.byte_loop:
    test cx, cx
    jz .newline
    mov al, [bx]
    cmp al, 0x0d
    je .skip
    cmp al, 0x0a
    je .line_break
    cmp al, 32
    jb .dot
    cmp al, 126
    ja .dot
    call print_char
    jmp .next

.dot:
    mov al, '.'
    call print_char
    jmp .next

.line_break:
    mov si, newline
    call print_string
    jmp .next

.skip:
    inc bx
    dec cx
    jmp .byte_loop

.next:
    inc bx
    dec cx
    jmp .byte_loop

.newline:
    mov si, newline
    call print_string

.done:
    pop si
    pop dx
    pop cx
    pop bx
    pop ax
    ret

protected_mode_program:
    mov si, msg_pm32_intro
    call print_string
    mov word [pm32_saved_sp], sp
    mov byte [pm32_status], 0
    mov dword [pm32_signature], 0
    mov dword [pm32_observed_cr0], 0
    mov dword [pm32_observed_esp], 0
    cli
    lgdt [pm32_gdt_descriptor]
    mov eax, cr0
    or eax, 1
    mov cr0, eax
    jmp PM32_CODE_SEL:pm32_entry

pm32_real_mode_resume:
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, [pm32_saved_sp]
    sti
    cmp byte [pm32_status], 1
    jne .fail
    mov si, msg_pm32_return_prefix
    call print_string
    mov eax, [pm32_signature]
    call print_hex32_eax
    mov si, msg_pm32_return_cr0
    call print_string
    mov eax, [pm32_observed_cr0]
    call print_hex32_eax
    mov si, msg_pm32_return_esp
    call print_string
    mov eax, [pm32_observed_esp]
    call print_hex32_eax
    mov si, newline
    call print_string
    ret

.fail:
    mov si, msg_pm32_fail
    call print_string
    ret

[bits 32]
pm32_entry:
    mov ax, PM32_DATA_SEL
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    mov esp, PM32_STACK_TOP

    mov eax, cr0
    a16 mov [pm32_observed_cr0], eax
    a16 mov [pm32_observed_esp], esp

    xor esi, esi
    mov si, msg_pm32_serial_entered
    call pm32_serial_write_string

    mov word [0xB8000], 0x1F50
    mov word [0xB8002], 0x1F4D
    mov word [0xB8004], 0x1F33
    mov word [0xB8006], 0x1F32

    mov eax, 0x12345678
    mov ebx, 0x0F0F0F0F
    xor eax, ebx
    a16 mov [pm32_signature], eax
    a16 mov byte [pm32_status], 1

    jmp word PM16_CODE_SEL:pm32_exit16

pm32_serial_write_string:
    lodsb
    test al, al
    jz .done
    call pm32_serial_write_char
    jmp pm32_serial_write_string

.done:
    ret

pm32_serial_write_char:
    push eax
    push edx

.wait:
    mov dx, COM1_PORT + 5
    in al, dx
    test al, 0x20
    jz .wait

    pop edx
    pop eax
    mov dx, COM1_PORT
    out dx, al
    ret

[bits 16]
pm32_exit16:
    mov ax, PM16_DATA_SEL
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    mov eax, cr0
    and eax, 0xFFFFFFFE
    mov cr0, eax
    jmp 0x0000:pm32_real_mode_resume

pm32_gdt:
    dq 0x0000000000000000
    dq 0x00CF9A000000FFFF
    dq 0x00CF92000000FFFF
    dq 0x00009A000000FFFF
    dq 0x000092000000FFFF
pm32_gdt_end:

pm32_gdt_descriptor:
    dw pm32_gdt_end - pm32_gdt - 1
    dw pm32_gdt
    dw 0
