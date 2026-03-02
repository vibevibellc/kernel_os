generation dd 1
chat_session_counter dd 0
chat_session_active db 0
chat_session_buffer times CHAT_SESSION_SIZE db 0
chat_fresh_needed db 0
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
ramlist_initialized db 0
ramlist_head db 0xff
ramlist_tail db 0xff
ramlist_free_head db 0
ramlist_count db 0
ramlist_next times RAMLIST_NODE_COUNT db 0
ramlist_values times RAMLIST_NODE_COUNT dw 0
calc_op db 0
calc_left dw 0
calc_right dw 0
calc_result dw 0
graph_mode db 1
graph_char db 0
graph_a dw 1
graph_b dw 0
graph_c dw 0
graph_wave_amp dw 8
graph_wave_period dw 16
graph_wave_phase dw 0
graph_wave_offset dw 0
graph_x_scale dw 1
graph_y_scale dw 1
graph_x_offset dw 0
graph_y_offset dw 0
graph_axis_row dw 0xffff
graph_axis_col dw 0xffff
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
