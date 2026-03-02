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
    dw cmd_ramlist, do_ramlist
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
msg_hint db 0x68, 0x65, 0x6C, 0x70, 0x2C, 0x20, 0x68, 0x61, 0x72, 0x64, 0x77, 0x61, 0x72, 0x65, 0x5F, 0x6C, 0x69, 0x73, 0x74, 0x2C, 0x20, 0x6D, 0x65, 0x6D, 0x6F, 0x72, 0x79, 0x5F, 0x6D, 0x61, 0x70, 0x2C, 0x20, 0x63, 0x61, 0x6C, 0x63, 0x2C, 0x20, 0x63, 0x68, 0x61, 0x74, 0x2C, 0x20, 0x63, 0x75, 0x72, 0x6C, 0x2C, 0x20, 0x73, 0x68, 0x6F, 0x77, 0x5F, 0x62, 0x61, 0x6C, 0x61, 0x6E, 0x63, 0x65, 0x2C, 0x20, 0x68, 0x6F, 0x73, 0x74, 0x72, 0x65, 0x71, 0x2C, 0x20, 0x74, 0x61, 0x73, 0x6B, 0x5F, 0x73, 0x70, 0x61, 0x77, 0x6E, 0x2C, 0x20, 0x74, 0x61, 0x73, 0x6B, 0x5F, 0x6C, 0x69, 0x73, 0x74, 0x2C, 0x20, 0x74, 0x61, 0x73, 0x6B, 0x5F, 0x72, 0x65, 0x74, 0x69, 0x72, 0x65, 0x2C, 0x20, 0x74, 0x61, 0x73, 0x6B, 0x5F, 0x73, 0x74, 0x65, 0x70, 0x2C, 0x20, 0x72, 0x61, 0x6D, 0x6C, 0x69, 0x73, 0x74, 0x2C, 0x20, 0x67, 0x72, 0x61, 0x70, 0x68, 0x2C, 0x20, 0x70, 0x61, 0x69, 0x6E, 0x74, 0x2C, 0x20, 0x65, 0x64, 0x69, 0x74, 0x2C, 0x20, 0x70, 0x65, 0x65, 0x6B, 0x2C, 0x20, 0x63, 0x6C, 0x65, 0x61, 0x72, 0x2C, 0x20, 0x61, 0x62, 0x6F, 0x75, 0x74, 0x2C, 0x20, 0x68, 0x61, 0x6C, 0x74, 0x2C, 0x20, 0x72, 0x65, 0x62, 0x6F, 0x6F, 0x74, 0x0D, 0x0A, 0x0D, 0x0A, 0x00
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
         db 0x20, 0x72, 0x61, 0x6D, 0x6C, 0x69, 0x73, 0x74, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20, 0x52, 0x41, 0x4D, 0x20, 0x6C, 0x69, 0x6E, 0x6B, 0x65, 0x64, 0x20, 0x6C, 0x69, 0x73, 0x74, 0x0D, 0x0A
         db " graph          ASCII function grapher", 13, 10
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
msg_chat_intro db "chat: entry starts a fresh claude session; later prompts keep context until blank line or exit. command output may feed back automatically. /loop continues autonomously; /kill-self halts the kernel.", 13, 10, 0
msg_chat_wait db "waiting for host response...", 13, 10, 0
msg_chat_loop_wait db "chat: continuing with host using the latest command output...", 13, 10, 0
msg_chat_loop_enabled db "recursive loop enabled. the host will keep iterating until claude returns a normal answer.", 13, 10, 0
msg_chat_loop_limit db "chat continuation limit reached; handing control back to the user.", 13, 10, 0
msg_chat_exit db "leaving chat", 13, 10, 0
msg_chat_post_prefix db 'POST /chat {"session":"', 0
msg_chat_post_mid db '","prompt":"', 0
msg_chat_post_fresh db ',"fresh_chat":true', 0
msg_chat_loop_post_prefix db 'POST /chat {"session":"', 0
msg_chat_loop_post_mid db '","prompt":"continue from the latest kernel command result. if more non-interactive work is needed, return the next command; otherwise return a normal user-facing answer","loop":true', 0
msg_curl_intro db "curl: fetch a URL through the host bridge. blank line or exit returns.", 13, 10, 0
msg_curl_wait db "waiting for webpage...", 13, 10, 0
msg_curl_exit db "leaving curl", 13, 10, 0
msg_curl_bad db "curl syntax: use a non-empty http:// or https:// URL", 13, 10, 0
msg_show_balance_wait db "checking anthropic spend summary through the host bridge...", 13, 10, 0
msg_peek_intro db "peek: inspect bytes from the live stage2 image", 13, 10, 0
msg_peek_bad db "peek syntax: offset and count are required hex values, count 1..C8", 13, 10, 0
msg_peek_page_bad db "peekpage syntax: base and page are required hex values", 13, 10, 0
msg_peek_header db "peek 0x", 0
msg_peek_mid db ": ", 0
msg_hostreq_intro db 0x68, 0x6F, 0x73, 0x74, 0x72, 0x65, 0x71, 0x3A, 0x20, 0x6C, 0x69, 0x73, 0x74, 0x2C, 0x20, 0x73, 0x70, 0x61, 0x77, 0x6E, 0x2C, 0x20, 0x63, 0x6C, 0x6F, 0x6E, 0x65, 0x2C, 0x20, 0x72, 0x65, 0x74, 0x69, 0x72, 0x65, 0x2C, 0x20, 0x73, 0x74, 0x65, 0x70, 0x2C, 0x20, 0x61, 0x64, 0x6F, 0x70, 0x74, 0x2C, 0x20, 0x67, 0x69, 0x74, 0x2D, 0x73, 0x79, 0x6E, 0x63, 0x0D, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
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
msg_task_host_summary db "host summary:", 13, 10, 0
msg_task_name_prefix db " name=", 0
msg_task_goal_prefix db " goal=", 0
msg_ramlist_intro db 0x72, 0x61, 0x6D, 0x6C, 0x69, 0x73, 0x74, 0x3A, 0x20, 0x70, 0x75, 0x73, 0x68, 0x2C, 0x20, 0x70, 0x6F, 0x70, 0x2C, 0x20, 0x73, 0x68, 0x6F, 0x77, 0x2C, 0x20, 0x63, 0x6C, 0x65, 0x61, 0x72, 0x2C, 0x20, 0x65, 0x78, 0x69, 0x74, 0x0D, 0x0A, 0x00
msg_ramlist_exit db 0x6C, 0x65, 0x61, 0x76, 0x69, 0x6E, 0x67, 0x20, 0x72, 0x61, 0x6D, 0x6C, 0x69, 0x73, 0x74, 0x0D, 0x0A, 0x00
msg_ramlist_unknown db "use push/pop/show/clear/exit", 13, 10, 0
msg_ramlist_bad_value db "bad integer", 13, 10, 0
msg_ramlist_full db "full", 13, 10, 0
msg_ramlist_empty db "empty", 13, 10, 0
msg_ramlist_pushed db "stored", 13, 10, 0
msg_ramlist_popped db "popped ", 0
msg_ramlist_cleared db "cleared", 13, 10, 0
msg_ramlist_show db "contents:", 13, 10, 0
msg_ramlist_none db "empty", 13, 10, 0
msg_ramlist_item_sep db ": ", 0
msg_cmd_prefix db "CMD: ", 0
msg_cmd_dispatch db "AI requested command: ", 0
msg_error_prefix db "Error:", 0
msg_generation db "generation 0x", 0
msg_generation_advanced db "generation advanced to 0x", 0
msg_patch_danger db 13, 10, "*** CLAUDE COOKED UP A LIVE CODE PATCH ***", 13, 10, 0
msg_patch_offset db "offset 0x", 0
msg_patch_bytes db " bytes ", 0
msg_applying db "applying patch... hold on...", 13, 10, 0
msg_patch_applied db "patch applied. beautiful chaos achieved.", 13, 10, 0
msg_unknown_patch db "claude sent a malformed patch, ignoring it.", 13, 10, 0
msg_host_post_list db 'POST /host {"action":"list-sessions"', 0
msg_host_post_spawn_prefix db 'POST /host {"action":"spawn-session","session":"', 0
msg_host_post_spawn_mid db '","goal":"', 0
msg_host_post_retire_prefix db 'POST /host {"action":"retire-session","session":"', 0
msg_host_post_step_prefix db 'POST /host {"action":"step-session","session":"', 0
msg_host_post_step_mid db '","prompt":"', 0
msg_host_post_curl_prefix db 'POST /host {"action":"fetch-url","url":"', 0
msg_host_post_balance db 'POST /host {"action":"show-balance"', 0
msg_host_post_git_sync db 'POST /host {"action":"git-sync"', 0
msg_host_post_clone_prefix db 'POST /host {"action":"clone-session","session":"', 0
msg_host_post_adopt_prefix db 'POST /host {"action":"adopt-style","session":"', 0
msg_host_post_clone_mid db '","source_session":"', 0
msg_host_post_modifier_mid db '","modifier":"', 0
msg_generation_json_prefix db ',"generation":"0x', 0
msg_generation_json_suffix db '"', 0
msg_json_quote db '"', 0
msg_json_close db '}', 0
msg_graph_intro db "graph viewer", 13, 10, 0
msg_graph_mode_line db "mode 1: line", 13, 10, 0
msg_graph_mode_parabola db "mode 2: quadratic", 13, 10, 0
msg_graph_mode_wave db "mode 3: triangle wave", 13, 10, 0
msg_graph_params_line db "y = ", 0
msg_graph_params_quad db "y = ", 0
msg_graph_params_wave db "amp=", 0
msg_graph_x2_term db "*x*x + ", 0
msg_graph_x_term db "*x + ", 0
msg_graph_period_prefix db " period=", 0
msg_graph_phase_prefix db " phase=", 0
msg_graph_offset_prefix db " offset=", 0
msg_graph_viewport db "view: x_step=", 0
msg_graph_y_step db " y_step=", 0
msg_graph_center_prefix db " center=(", 0
msg_graph_comma db ", ", 0
msg_graph_center_suffix db ")", 13, 10, 0
msg_graph_edit_hint db "edit function values; blank line keeps the current value", 13, 10, 0
msg_graph_view_hint db "edit viewport values; blank line keeps the current value", 13, 10, 0
msg_graph_value_bad db "enter a valid integer in range", 13, 10, 0
msg_graph_footer db "1 line  2 quadratic  3 wave  e edit  v view  r reset  q quit", 13, 10, 0
prompt_graph_a db "a> ", 0
prompt_graph_b db "b> ", 0
prompt_graph_c db "c> ", 0
prompt_graph_amp db "amplitude>=0> ", 0
prompt_graph_period db "period>=2> ", 0
prompt_graph_phase db "phase> ", 0
prompt_graph_offset db "offset> ", 0
prompt_graph_x_scale db "x units per column>=1> ", 0
prompt_graph_y_scale db "y units per row>=1> ", 0
prompt_graph_x_offset db "center x> ", 0
prompt_graph_y_offset db "center y> ", 0
msg_paint_intro db "paint: hold left mouse to draw; arrow keys or WASD sketch with the keyboard; c changes color, x clears, q or Esc exits", 13, 10, 0
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
prompt_ramlist db 0x72, 0x61, 0x6D, 0x6C, 0x69, 0x73, 0x74, 0x3E, 0x20, 0x00
prompt_ramlist_value db "value> ", 0
prompt_host_prompt db "prompt> ", 0
prompt_host_modifier db "modifier> ", 0
prompt_peek_offset db "offset hex> ", 0
prompt_peek_count db "count hex (1..C8)> ", 0
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
cmd_ramlist db 0x72, 0x61, 0x6D, 0x6C, 0x69, 0x73, 0x74, 0x00
cmd_graph db "graph", 0
cmd_paint db "paint", 0
cmd_edit db "edit", 0
cmd_peek db "peek", 0
cmd_clear db "clear", 0
cmd_about db "about", 0
cmd_halt db "halt", 0
cmd_reboot db "reboot", 0
cmd_exit db "exit", 0
cmd_ramlist_push db "push", 0
cmd_ramlist_pop db "pop", 0
cmd_ramlist_show db "show", 0
cmd_ramlist_clear db "clear", 0
curl_prefix db "/curl ", 0
loop_prefix db "/loop", 0
patch_prefix db "/patch ", 0
peek_page_prefix db "/peekpage ", 0
peek_prefix db "/peek ", 0
sys_retired_prefix db "SYS: session retired by /kill-self", 0
action_list_sessions db "list-sessions", 0
action_spawn_session db "spawn-session", 0
action_clone_session db "clone-session", 0
action_retire_session db "retire-session", 0
action_step_session db "step-session", 0
action_adopt_style db "adopt-style", 0
action_git_sync db "git-sync", 0
