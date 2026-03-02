graph_program:
    call graph_reset_defaults

.render:
    call set_text_mode
    call graph_update_axes
    mov si, msg_graph_intro
    call print_string
    call graph_print_status

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
    mov ax, [graph_axis_row]
    cmp ax, 0xffff
    je .not_x_axis
    cmp dl, al
    jne .not_x_axis
    mov byte [graph_char], '-'

.not_x_axis:
    mov ax, [graph_axis_col]
    cmp ax, 0xffff
    je .not_y_axis
    cmp cl, al
    jne .not_y_axis
    mov byte [graph_char], '|'
    mov ax, [graph_axis_row]
    cmp ax, 0xffff
    je .not_y_axis
    cmp dl, al
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
    cmp al, 'e'
    je .edit_function
    cmp al, 'E'
    je .edit_function
    cmp al, 'v'
    je .edit_view
    cmp al, 'V'
    je .edit_view
    cmp al, 'r'
    je .reset
    cmp al, 'R'
    je .reset
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

.edit_function:
    call graph_edit_function
    jmp .render

.edit_view:
    call graph_edit_view
    jmp .render

.reset:
    call graph_reset_defaults
    jmp .render

.exit:
    mov si, newline
    call print_string
    ret

graph_reset_defaults:
    mov byte [graph_mode], 1
    mov word [graph_a], 1
    mov word [graph_b], 0
    mov word [graph_c], 0
    mov word [graph_wave_amp], 8
    mov word [graph_wave_period], 16
    mov word [graph_wave_phase], 0
    mov word [graph_wave_offset], 0
    mov word [graph_x_scale], 1
    mov word [graph_y_scale], 1
    mov word [graph_x_offset], 0
    mov word [graph_y_offset], 0
    ret

graph_print_status:
    mov al, [graph_mode]
    cmp al, 1
    je .line_mode
    cmp al, 2
    je .quadratic_mode
    mov si, msg_graph_mode_wave
    call print_string
    mov si, msg_graph_params_wave
    call print_string
    mov ax, [graph_wave_amp]
    call print_int_ax
    mov si, msg_graph_period_prefix
    call print_string
    mov ax, [graph_wave_period]
    call print_int_ax
    mov si, msg_graph_phase_prefix
    call print_string
    mov ax, [graph_wave_phase]
    call print_int_ax
    mov si, msg_graph_offset_prefix
    call print_string
    mov ax, [graph_wave_offset]
    call print_int_ax
    mov si, newline
    call print_string
    jmp .viewport

.line_mode:
    mov si, msg_graph_mode_line
    call print_string
    mov si, msg_graph_params_line
    call print_string
    mov ax, [graph_a]
    call print_int_ax
    mov si, msg_graph_x_term
    call print_string
    mov ax, [graph_b]
    call print_int_ax
    mov si, newline
    call print_string
    jmp .viewport

.quadratic_mode:
    mov si, msg_graph_mode_parabola
    call print_string
    mov si, msg_graph_params_quad
    call print_string
    mov ax, [graph_a]
    call print_int_ax
    mov si, msg_graph_x2_term
    call print_string
    mov ax, [graph_b]
    call print_int_ax
    mov si, msg_graph_x_term
    call print_string
    mov ax, [graph_c]
    call print_int_ax
    mov si, newline
    call print_string

.viewport:
    mov si, msg_graph_viewport
    call print_string
    mov ax, [graph_x_scale]
    call print_int_ax
    mov si, msg_graph_y_step
    call print_string
    mov ax, [graph_y_scale]
    call print_int_ax
    mov si, msg_graph_center_prefix
    call print_string
    mov ax, [graph_x_offset]
    call print_int_ax
    mov si, msg_graph_comma
    call print_string
    mov ax, [graph_y_offset]
    call print_int_ax
    mov si, msg_graph_center_suffix
    call print_string
    ret

graph_update_axes:
    mov word [graph_axis_row], 0xffff
    mov word [graph_axis_col], 0xffff

    mov ax, [graph_y_offset]
    cwd
    idiv word [graph_y_scale]
    add ax, GRAPH_CENTER_ROW
    cmp ax, 0
    jl .skip_row
    cmp ax, GRAPH_ROWS - 1
    jg .skip_row
    mov [graph_axis_row], ax

.skip_row:
    mov ax, [graph_x_offset]
    cwd
    idiv word [graph_x_scale]
    neg ax
    add ax, GRAPH_CENTER_COL
    cmp ax, 0
    jl .done
    cmp ax, GRAPH_COLS
    jg .done
    mov [graph_axis_col], ax

.done:
    ret

graph_edit_function:
    mov si, msg_graph_edit_hint
    call print_string
    mov al, [graph_mode]
    cmp al, 1
    je .edit_line
    cmp al, 2
    je .edit_quadratic

    mov si, prompt_graph_amp
    mov di, graph_wave_amp
    mov ax, 0
    call graph_read_min_into
    mov si, prompt_graph_period
    mov di, graph_wave_period
    mov ax, 2
    call graph_read_min_into
    mov si, prompt_graph_phase
    mov di, graph_wave_phase
    call graph_read_signed_into
    mov si, prompt_graph_offset
    mov di, graph_wave_offset
    call graph_read_signed_into
    ret

.edit_line:
    mov si, prompt_graph_a
    mov di, graph_a
    call graph_read_signed_into
    mov si, prompt_graph_b
    mov di, graph_b
    call graph_read_signed_into
    ret

.edit_quadratic:
    mov si, prompt_graph_a
    mov di, graph_a
    call graph_read_signed_into
    mov si, prompt_graph_b
    mov di, graph_b
    call graph_read_signed_into
    mov si, prompt_graph_c
    mov di, graph_c
    call graph_read_signed_into
    ret

graph_edit_view:
    mov si, msg_graph_view_hint
    call print_string
    mov si, prompt_graph_x_scale
    mov di, graph_x_scale
    mov ax, 1
    call graph_read_min_into
    mov si, prompt_graph_y_scale
    mov di, graph_y_scale
    mov ax, 1
    call graph_read_min_into
    mov si, prompt_graph_x_offset
    mov di, graph_x_offset
    call graph_read_signed_into
    mov si, prompt_graph_y_offset
    mov di, graph_y_offset
    call graph_read_signed_into
    ret

graph_read_signed_into:
    push bx
    push cx
    push dx
    mov bx, si

.loop:
    mov si, bx
    call print_string
    push di
    mov di, input_buffer
    mov cx, INPUT_MAX
    call read_line
    pop di
    cmp byte [input_buffer], 0
    je .done
    mov si, input_buffer
    call parse_signed_int
    jc .bad
    call skip_spaces
    cmp byte [si], 0
    jne .bad
    mov [di], ax

.done:
    pop dx
    pop cx
    pop bx
    ret

.bad:
    mov si, msg_graph_value_bad
    call print_string
    jmp .loop

graph_read_min_into:
    push bx
    push cx
    push dx
    mov bx, si
    mov dx, ax

.loop:
    mov si, bx
    call print_string
    push di
    mov di, input_buffer
    mov cx, INPUT_MAX
    call read_line
    pop di
    cmp byte [input_buffer], 0
    je .done
    mov si, input_buffer
    call parse_signed_int
    jc .bad
    call skip_spaces
    cmp byte [si], 0
    jne .bad
    cmp ax, dx
    jl .bad
    mov [di], ax

.done:
    pop dx
    pop cx
    pop bx
    ret

.bad:
    mov si, msg_graph_value_bad
    call print_string
    jmp .loop

graph_compute_row:
    push bx
    push cx
    push dx
    push si

    xor ah, ah
    mov bx, ax
    sub bx, GRAPH_CENTER_COL
    mov ax, [graph_x_scale]
    imul bx
    add ax, [graph_x_offset]
    mov bx, ax

    mov al, [graph_mode]
    cmp al, 1
    je .line
    cmp al, 2
    je .parabola

    mov ax, bx
    add ax, [graph_wave_phase]
    cwd
    idiv word [graph_wave_period]
    mov ax, dx
    cmp ax, 0
    jge .wave_mod_ok
    add ax, [graph_wave_period]

.wave_mod_ok:
    mov cx, [graph_wave_period]
    shr cx, 1
    cmp ax, cx
    jle .wave_scaled
    mov dx, [graph_wave_period]
    sub dx, ax
    mov ax, dx

.wave_scaled:
    imul word [graph_wave_amp]
    idiv cx
    add ax, [graph_wave_offset]
    jmp .to_screen

.line:
    mov ax, [graph_a]
    imul bx
    add ax, [graph_b]
    jmp .to_screen

.parabola:
    mov ax, bx
    imul bx
    mov cx, ax
    mov ax, [graph_a]
    imul cx
    push ax
    mov ax, [graph_b]
    imul bx
    pop dx
    add ax, dx
    add ax, [graph_c]

.to_screen:
    sub ax, [graph_y_offset]
    cwd
    idiv word [graph_y_scale]
    mov dx, GRAPH_CENTER_ROW
    sub dx, ax
    mov ax, dx

.clip:
    cmp ax, 0
    jl .invalid
    cmp ax, GRAPH_ROWS - 1
    jg .invalid
    jmp .done

.invalid:
    mov al, 0xff

.done:
    pop si
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
    mov ah, 0x01
    int 0x16
    jnz .keyboard_ready
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
    cmp al, 'w'
    je .move_up
    cmp al, 'W'
    je .move_up
    cmp al, 's'
    je .move_down
    cmp al, 'S'
    je .move_down
    cmp al, 'a'
    je .move_left
    cmp al, 'A'
    je .move_left
    cmp al, 'd'
    je .move_right
    cmp al, 'D'
    je .move_right

.mouse_only:
    call mouse_poll_packet
    jmp .loop

.keyboard_ready:
    xor ah, ah
    int 0x16
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
    cmp al, 'w'
    je .move_up
    cmp al, 'W'
    je .move_up
    cmp al, 's'
    je .move_down
    cmp al, 'S'
    je .move_down
    cmp al, 'a'
    je .move_left
    cmp al, 'A'
    je .move_left
    cmp al, 'd'
    je .move_right
    cmp al, 'D'
    je .move_right
    cmp al, 0
    jne .mouse_only
    cmp ah, 0x48
    je .move_up
    cmp ah, 0x50
    je .move_down
    cmp ah, 0x4b
    je .move_left
    cmp ah, 0x4d
    je .move_right
    jmp .mouse_only

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

.move_up:
    mov ax, -1
    xor bx, bx
    call paint_move_keyboard
    jmp .mouse_only

.move_down:
    mov ax, 1
    xor bx, bx
    call paint_move_keyboard
    jmp .mouse_only

.move_left:
    xor ax, ax
    mov bx, -1
    call paint_move_keyboard
    jmp .mouse_only

.move_right:
    xor ax, ax
    mov bx, 1
    call paint_move_keyboard
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

paint_move_keyboard:
    push ax
    push bx

    call paint_restore_cursor
    mov al, [mouse_color]
    call paint_set_current_pixel

    add word [mouse_y], ax
    add word [mouse_x], bx

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
    jle .capture_under
    mov word [mouse_y], 199

.capture_under:
    call paint_get_current_pixel
    mov [mouse_prev_under], al
    call paint_draw_cursor

    pop bx
    pop ax
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

