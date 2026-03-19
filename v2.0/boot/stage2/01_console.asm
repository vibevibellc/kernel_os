%define INPUT_MAX 63
%define MODEL_MAGIC 0x50414731
%define PAGE_BYTES 512
%define PAGE_NIBBLE_WARN 8
%define DEFAULT_RAM_SCAN_LINEAR_BASE 0x00100000
%define DEFAULT_RAM_SCAN_PAGES 0x2000
%define MAX_RAM_PAGE_INDEX 0x00800000
%ifndef DEFAULT_DISK_SCAN_LBA
%define DEFAULT_DISK_SCAN_LBA 96
%endif
%ifndef DEFAULT_DISK_SCAN_PAGES
%define DEFAULT_DISK_SCAN_PAGES 0x0800
%endif
%ifndef MODEL_STATE_LBA
%define MODEL_STATE_LBA 0x0100
%endif
%define MAX_DISK_PAGE_INDEX 0x00800000
%define DISK_TRANSFER_PAGES 16
%define MAP_TOP_COUNT 64
%define TOP_PAGE_BYTES (MAP_TOP_COUNT + MAP_TOP_COUNT + (MAP_TOP_COUNT * 4))
%define COM1_PORT 0x3F8
%define UNREAL32_CODE_SEL 0x08
%define UNREAL32_DATA_SEL 0x10
%define UNREAL16_CODE_SEL 0x18
%define UNREAL16_DATA_SEL 0x20
%define SOURCE_NONE 0
%define SOURCE_RAM 1
%define SOURCE_DISK 2
%define MODE_IDLE 0
%define MODE_TRAIN 1
%define MODE_CHAT 2
%define MODE_STREAM 3
%define TOP_PAGE_SCORES page_scores
%define TOP_PAGE_SOURCES (page_scores + MAP_TOP_COUNT)
%define TOP_PAGE_LABELS (page_scores + (MAP_TOP_COUNT * 2))

start:
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7a00
    sti

    mov [boot_drive], dl

    call serial_init
    call set_text_mode
    call model_bootstrap

    mov si, msg_banner
    call print_string
    mov si, msg_hint
    call print_string

main_loop:
    call show_prompt
    mov di, input_buffer
    mov cx, INPUT_MAX
    call read_line

    cmp byte [input_buffer], 0
    je main_loop

    mov si, input_buffer
    call dispatch_command_line
    jmp main_loop

dispatch_command_line:
    call skip_spaces
    cmp byte [si], 0
    je .done

    push si
    mov di, cmd_help
    call cmdreq
    cmp al, 1
    je .help

    pop si
    push si
    mov di, cmd_scan
    call cmdreq
    cmp al, 1
    je .scan

    pop si
    push si
    mov di, cmd_map
    call cmdreq
    cmp al, 1
    je .map

    pop si
    push si
    mov di, cmd_train
    call cmdreq
    cmp al, 1
    je .train

    pop si
    push si
    mov di, cmd_chat
    call cmdreq
    cmp al, 1
    je .chat

    pop si
    push si
    mov di, cmd_stream
    call cmdreq
    cmp al, 1
    je .stream

    pop si
    push si
    mov di, cmd_set
    call cmdreq
    cmp al, 1
    je .set

    pop si
    push si
    mov di, cmd_bench
    call cmdreq
    cmp al, 1
    je .bench

    pop si
    push si
    mov di, cmd_halt
    call cmdreq
    cmp al, 1
    je .halt

    pop si
    mov si, msg_unknown
    call print_string
    ret

.done:
    ret

.help:
    pop si
    mov si, msg_help
    call print_string
    ret

.scan:
    pop si
    call scan_program
    ret

.map:
    pop si
    call map_program
    ret

.train:
    pop si
    mov al, MODE_TRAIN
    call enter_mode
    jc .busy
    call train_program
    call leave_mode
    ret

.chat:
    pop si
    mov al, MODE_CHAT
    call enter_mode
    jc .busy
    call chat_program
    call leave_mode
    ret

.stream:
    pop si
    mov al, MODE_STREAM
    call enter_mode
    jc .busy
    call stream_program
    call leave_mode
    ret

.set:
    pop si
    call set_program
    ret

.bench:
    pop si
    call bench_program
    ret

.halt:
    pop si
    mov si, msg_halt
    call print_string
.halt_loop:
    cli
    hlt
    jmp .halt_loop

.busy:
    mov si, msg_busy
    call print_string
    ret

show_prompt:
    mov si, prompt
    call print_string
    ret

enter_mode:
    cmp byte [active_mode], MODE_IDLE
    jne .busy
    mov [active_mode], al
    clc
    ret

.busy:
    stc
    ret

leave_mode:
    mov byte [active_mode], MODE_IDLE
    ret

scan_program:
    mov si, msg_scan_intro
    call print_string
    call print_scan_config
    call model_scan_corpus
    cmp byte [scan_aborted], 1
    je .aborted
    call complete_scan_epoch
    call model_save_state
    call print_scan_summary
    ret

.aborted:
    call model_save_state
    mov si, msg_scan_aborted
    call print_string
    ret

map_program:
    mov si, msg_map_intro
    call print_string
    call print_page_map
    ret

train_program:
    mov si, msg_train_intro
    call print_string

.loop:
    call model_scan_corpus
    cmp byte [scan_aborted], 1
    je .done
    call complete_scan_epoch
    call print_scan_summary
    test byte [scan_epoch], 0x03
    jnz .check_interrupt
    call model_save_state

.check_interrupt:
    call poll_escape
    jnc .loop

.done:
    call model_save_state
    mov si, msg_train_exit
    call print_string
    ret

chat_program:
    mov si, msg_chat_intro
    call print_string
    mov si, prompt_chat
    call print_string
    mov di, input_buffer
    mov cx, INPUT_MAX
    call read_line

    cmp byte [input_buffer], 0
    je .done
    mov si, input_buffer
    mov di, cmd_exit
    call streq
    cmp al, 1
    je .done

    mov si, input_buffer
    call seed_generation_from_buffer

    mov si, msg_chat_prefix
    call print_string

.generate:
    call model_predict_byte
    call print_generated_byte
    call poll_escape
    jnc .generate

    mov si, newline
    call print_string
    ret

.done:
    mov si, msg_chat_done
    call print_string
    ret

stream_program:
    mov si, msg_stream_intro
    call print_string
    mov byte [generation_prev_nibble], 0
    mov byte [stream_column], 0

.loop:
    call model_predict_byte
    call print_generated_byte
    call poll_escape
    jnc .loop

    mov si, newline
    call print_string
    ret

bench_program:
    mov si, msg_bench_intro
    call print_string
    call print_scan_config
    call bios_get_ticks
    mov [bench_tick_start], dx
    call model_scan_corpus
    call bios_get_ticks
    sub dx, [bench_tick_start]
    mov [bench_tick_delta], dx
    cmp byte [scan_aborted], 1
    je .aborted
    call complete_scan_epoch
    call model_save_state
    call print_scan_summary
    mov si, msg_bench_ticks
    call print_string
    mov ax, [bench_tick_delta]
    call print_decimal16_ax
    mov si, msg_bench_ticks_suffix
    call print_string
    ret

.aborted:
    call model_save_state
    mov si, msg_scan_aborted
    call print_string
    mov si, msg_bench_ticks
    call print_string
    mov ax, [bench_tick_delta]
    call print_decimal16_ax
    mov si, msg_bench_ticks_suffix
    call print_string
    ret

complete_scan_epoch:
    inc word [scan_epoch]
    call maybe_decay_model_counts
    ret

model_bootstrap:
    call model_load_state
    jnc .loaded

    mov si, msg_model_seeded
    call print_string
    call model_clear_state
    mov dword [ram_scan_start], DEFAULT_RAM_SCAN_LINEAR_BASE
    mov dword [ram_scan_page_count], DEFAULT_RAM_SCAN_PAGES
    mov dword [disk_scan_lba], DEFAULT_DISK_SCAN_LBA
    mov dword [disk_scan_page_count], DEFAULT_DISK_SCAN_PAGES
    mov dword [model_signature], MODEL_MAGIC
    ret

.loaded:
    call clear_top_pages
    mov dword [ram_scan_start], DEFAULT_RAM_SCAN_LINEAR_BASE
    mov dword [ram_scan_page_count], DEFAULT_RAM_SCAN_PAGES
    mov dword [disk_scan_lba], DEFAULT_DISK_SCAN_LBA
    mov dword [disk_scan_page_count], DEFAULT_DISK_SCAN_PAGES
    mov si, msg_model_loaded
    call print_string
    ret

model_clear_state:
    push ax
    push cx
    push di
    push es
    xor ax, ax
    mov es, ax
    mov di, model_state_start
    mov cx, model_state_size
    rep stosb
    pop es
    pop di
    pop cx
    pop ax
    ret

model_load_state:
    push ax
    push dx
    push si

    mov ah, 0x42
    mov dl, [boot_drive]
    mov si, model_state_packet
    int 0x13
    jc .fail

    cmp dword [model_signature], MODEL_MAGIC
    jne .fail

    pop si
    pop dx
    pop ax
    clc
    ret

.fail:
    pop si
    pop dx
    pop ax
    stc
    ret

model_save_state:
    push ax
    push dx
    push si

    mov dword [model_signature], MODEL_MAGIC
    mov ah, 0x43
    xor al, al
    mov dl, [boot_drive]
    mov si, model_state_packet
    int 0x13

    pop si
    pop dx
    pop ax
    ret

model_scan_corpus:
    mov byte [scan_aborted], 0
    mov byte [scan_max_score], 0
    mov byte [scan_max_source], SOURCE_NONE
    mov dword [scan_max_label], 0
    call clear_top_pages
    call model_scan_ram_pages
    cmp byte [scan_aborted], 1
    je .done
    call model_scan_disk_pages

.done:
    ret

model_scan_ram_pages:
    push ax
    push bx
    push cx
    push dx

    call unreal_init

    mov eax, [ram_scan_start]
    mov [ram_scan_linear], eax
    mov eax, [ram_scan_page_count]
    mov si, msg_scan_progress_ram
    call scan_progress_begin

.loop:
    mov eax, [scan_pages_done]
    cmp eax, [scan_total_pages]
    jae .done

    mov eax, [ram_scan_linear]
    mov [current_page_label], eax
    mov byte [current_page_source], SOURCE_RAM
    call model_scan_ram_page
    call model_store_page_score

    mov eax, [ram_scan_linear]
    add eax, PAGE_BYTES
    mov [ram_scan_linear], eax
    call scan_progress_advance
    cmp byte [scan_aborted], 1
    jne .loop

.done:
    cmp byte [scan_aborted], 1
    je .exit
    call scan_progress_finish

.exit:
    pop dx
    pop cx
    pop bx
    pop ax
    ret

model_scan_ram_page:
    mov eax, [ram_scan_linear]
    cmp eax, 0x000A0000
    jb .scan
    cmp eax, 0x00100000
    jb .skip

.scan:
    mov esi, eax
    call model_scan_page_fsesi
    ret

.skip:
    xor al, al
    ret

model_scan_disk_pages:
    push ax
    push bx
    push cx
    push dx
    push di
    push si

    mov eax, [disk_scan_lba]
    mov [disk_scan_cursor], eax
    mov eax, [disk_scan_page_count]
    mov si, msg_scan_progress_disk
    call scan_progress_begin
    mov ecx, [disk_scan_page_count]

.loop:
    test ecx, ecx
    jz .done
    cmp byte [scan_aborted], 1
    je .done

    mov eax, ecx
    cmp eax, DISK_TRANSFER_PAGES
    jbe .chunk_size_ready
    mov eax, DISK_TRANSFER_PAGES

.chunk_size_ready:
    mov [disk_chunk_pages], eax
    mov [disk_scan_packet_count], ax
    mov eax, [disk_scan_cursor]

    call disk_read_pages_eax
    jc .read_fail
    mov di, disk_page_buffer
    jmp .process_chunk

.read_fail:
    mov di, disk_page_buffer
    jmp .process_failed_chunk

.process_chunk:
    mov eax, [disk_chunk_pages]
    test eax, eax
    jz .loop
    cmp byte [scan_aborted], 1
    je .done

    mov eax, [disk_scan_cursor]
    mov [current_page_label], eax
    mov byte [current_page_source], SOURCE_DISK
    mov si, di
    call model_scan_page_buffer
    call model_store_page_score
    add di, PAGE_BYTES
    jmp .advance_page

.process_failed_chunk:
    mov eax, [disk_chunk_pages]
    test eax, eax
    jz .loop
    cmp byte [scan_aborted], 1
    je .done

    mov eax, [disk_scan_cursor]
    mov [current_page_label], eax
    mov byte [current_page_source], SOURCE_DISK
    mov al, 0xff
    call model_store_page_score
    jmp .advance_failed_page

.advance_page:
    mov eax, [disk_scan_cursor]
    inc eax
    mov [disk_scan_cursor], eax
    dec dword [disk_chunk_pages]
    call scan_progress_advance
    dec ecx
    jmp .process_chunk

.advance_failed_page:
    mov eax, [disk_scan_cursor]
    inc eax
    mov [disk_scan_cursor], eax
    dec dword [disk_chunk_pages]
    call scan_progress_advance
    dec ecx
    jmp .process_failed_chunk

.done:
    cmp byte [scan_aborted], 1
    je .exit
    call scan_progress_finish

.exit:
    pop si
    pop di
    pop dx
    pop cx
    pop bx
    pop ax
    ret

disk_read_pages_eax:
    push dx
    push si
    mov [disk_scan_lba_low], eax
    mov dword [disk_scan_lba_high], 0
    mov ah, 0x42
    mov dl, [boot_drive]
    mov si, disk_scan_packet
    int 0x13
    pop si
    pop dx
    ret

model_scan_page_buffer:
    push bx
    push cx
    push dx
    push si

    xor bx, bx
    mov byte [current_page_surprise], 0
    mov cx, PAGE_BYTES

.loop:
    lodsb
    mov dl, al
    mov al, dl
    shr al, 4
    call model_observe_nibble
    mov al, dl
    and al, 0x0f
    call model_observe_nibble
    loop .loop

    mov al, [current_page_surprise]
    pop si
    pop dx
    pop cx
    pop bx
    ret

model_scan_page_fsesi:
    push bx
    push cx
    push dx
    push si

    xor bx, bx
    mov byte [current_page_surprise], 0
    mov cx, PAGE_BYTES

.loop:
    mov al, [fs:esi]
    inc esi
    mov dl, al
    mov al, dl
    shr al, 4
    call model_observe_nibble
    mov al, dl
    and al, 0x0f
    call model_observe_nibble
    loop .loop

    mov al, [current_page_surprise]
    pop si
    pop dx
    pop cx
    pop bx
    ret

model_observe_nibble:
    push dx
    push si

    mov dl, al
    mov al, bl
    shl al, 4
    or al, dl
    xor ah, ah
    shl ax, 1
    mov si, model_counts
    add si, ax
    mov ax, [si]
    cmp ax, PAGE_NIBBLE_WARN
    jae .count_only
    cmp byte [current_page_surprise], 0xff
    je .count_only
    inc byte [current_page_surprise]

.count_only:
    cmp ax, 0xffff
    je .set_prev
    inc word [si]

.set_prev:
    mov bl, dl
    pop si
    pop dx
    ret

model_store_page_score:
    push ax
    test al, al
    jz .max_only
    cmp al, [scan_max_score]
    jbe .done
    mov [scan_max_score], al
    mov dl, [current_page_source]
    mov [scan_max_source], dl
    mov eax, [current_page_label]
    mov [scan_max_label], eax

.done:
    call update_top_page_entries
    pop ax
    ret

.max_only:
    cmp byte [scan_max_source], SOURCE_NONE
    jne .done_no_insert
    mov dl, [current_page_source]
    mov [scan_max_source], dl
    mov eax, [current_page_label]
    mov [scan_max_label], eax

.done_no_insert:
    pop ax
    ret

update_top_page_entries:
    push ax
    push bx
    push cx
    push dx
    push si
    push di

    mov dl, al
    test dl, dl
    jz .done

    xor bx, bx

.find_slot:
    cmp bx, MAP_TOP_COUNT
    jae .done
    mov si, TOP_PAGE_SOURCES
    cmp byte [si + bx], SOURCE_NONE
    je .insert_here
    mov si, TOP_PAGE_SCORES
    cmp dl, [si + bx]
    ja .insert_here
    inc bx
    jmp .find_slot

.insert_here:
    mov di, bx
    mov bx, MAP_TOP_COUNT - 1

.shift_down:
    cmp bx, di
    jbe .store

    mov si, TOP_PAGE_SCORES
    mov al, [si + bx - 1]
    mov [si + bx], al

    mov si, TOP_PAGE_SOURCES
    mov al, [si + bx - 1]
    mov [si + bx], al

    mov si, TOP_PAGE_LABELS
    mov ax, bx
    shl ax, 2
    add si, ax
    sub si, 4
    mov eax, [si]
    add si, 4
    mov [si], eax

    dec bx
    jmp .shift_down

.store:
    mov bx, di
    mov si, TOP_PAGE_SCORES
    mov [si + bx], dl

    mov si, TOP_PAGE_SOURCES
    mov al, [current_page_source]
    mov [si + bx], al

    mov si, TOP_PAGE_LABELS
    mov ax, bx
    shl ax, 2
    add si, ax
    mov eax, [current_page_label]
    mov [si], eax

.done:
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    pop ax
    ret

clear_top_pages:
    push ax
    push cx
    push di
    push es

    xor ax, ax
    mov es, ax
    mov di, TOP_PAGE_SCORES
    mov cx, TOP_PAGE_BYTES
    rep stosb

    pop es
    pop di
    pop cx
    pop ax
    ret

print_scan_summary:
    mov si, msg_scan_prefix
    call print_string
    mov ax, [scan_epoch]
    call print_hex16_ax
    mov si, msg_scan_mid
    call print_string
    mov dl, [scan_max_source]
    mov eax, [scan_max_label]
    call print_page_descriptor
    mov si, msg_scan_suffix
    call print_string
    mov al, [scan_max_score]
    call print_hex_byte_al
    mov si, newline
    call print_string
    ret

print_page_map:
    push ax
    push bx
    push dx
    push si

    mov si, TOP_PAGE_SOURCES
    cmp byte [si], SOURCE_NONE
    jne .entries
    mov si, msg_map_empty
    call print_string
    jmp .done

.entries:
    xor bx, bx
    mov byte [map_last_source], SOURCE_NONE
    mov dword [map_last_label], 0xFFFFFFFF

.loop:
    cmp bx, MAP_TOP_COUNT
    jae .done
    mov si, TOP_PAGE_SOURCES
    mov dl, [si + bx]
    cmp dl, SOURCE_NONE
    je .done
    mov si, TOP_PAGE_LABELS
    mov ax, bx
    shl ax, 2
    add si, ax
    mov eax, [si]
    cmp dl, [map_last_source]
    jne .emit
    cmp eax, [map_last_label]
    je .next

.emit:
    call print_page_descriptor
    mov [map_last_source], dl
    mov [map_last_label], eax
    mov si, msg_map_score
    call print_string
    mov si, TOP_PAGE_SCORES
    mov al, [si + bx]
    call print_hex_byte_al
    mov si, newline
    call print_string

.next:
    inc bx
    jmp .loop

.done:
    pop si
    pop dx
    pop bx
    pop ax
    ret

print_page_descriptor:
    push ax
    push dx

    push eax
    mov dh, dl
    mov dl, '?'
    cmp dh, SOURCE_RAM
    jne .check_disk
    mov dl, 'R'
    jmp .emit

.check_disk:
    cmp dh, SOURCE_DISK
    jne .emit
    mov dl, 'D'

.emit:
    mov al, '['
    call print_char
    mov al, dl
    call print_char
    mov al, ' '
    call print_char
    pop eax
    call print_hex32_eax
    mov al, ']'
    call print_char

    pop dx
    pop ax
    ret

print_scan_config:
    mov si, msg_config_start
    call print_string
    mov eax, [ram_scan_start]
    call print_hex32_eax
    mov si, msg_config_pages
    call print_string
    mov eax, [ram_scan_page_count]
    call print_hex32_eax
    mov si, msg_config_mib
    call print_string
    mov eax, [ram_scan_page_count]
    add eax, 2047
    shr eax, 11
    call print_decimal16_ax
    mov si, msg_config_disk_start
    call print_string
    mov eax, [disk_scan_lba]
    call print_hex32_eax
    mov si, msg_config_disk_pages
    call print_string
    mov eax, [disk_scan_page_count]
    call print_hex32_eax
    mov si, msg_config_disk_mib
    call print_string
    mov eax, [disk_scan_page_count]
    add eax, 2047
    shr eax, 11
    call print_decimal16_ax
    mov si, newline
    call print_string
    ret

scan_progress_begin:
    push eax
    push ecx
    push edx

    mov [scan_total_pages], eax
    mov dword [scan_pages_done], 0
    mov [scan_progress_label], si
    mov byte [scan_progress_increment], 10
    mov ecx, 10
    cmp eax, 0x00080000
    jb .divisor_ready
    mov byte [scan_progress_increment], 1
    mov ecx, 100

.divisor_ready:
    mov al, [scan_progress_increment]
    mov [scan_progress_percent], al
    xor edx, edx
    div ecx
    test eax, eax
    jnz .store
    mov eax, 1

.store:
    mov [scan_progress_step], eax
    mov [scan_progress_next], eax

    pop edx
    pop ecx
    pop eax
    ret

scan_progress_advance:
    inc dword [scan_pages_done]
    mov eax, [scan_pages_done]
    test al, 0x3f
    jnz .thresholds
    call poll_escape
    jnc .thresholds
    mov byte [scan_aborted], 1
    ret

.thresholds:
    cmp byte [scan_aborted], 1
    je .done

.check:
    mov al, [scan_progress_percent]
    cmp al, 100
    jae .done
    mov eax, [scan_pages_done]
    cmp eax, [scan_progress_next]
    jb .done
    call scan_progress_emit
    mov eax, [scan_progress_next]
    add eax, [scan_progress_step]
    mov [scan_progress_next], eax
    mov al, [scan_progress_increment]
    add byte [scan_progress_percent], al
    jmp .check

.done:
    ret

scan_progress_finish:
    mov byte [scan_progress_percent], 100
    call scan_progress_emit
    ret

scan_progress_emit:
    mov si, [scan_progress_label]
    call print_string
    xor ax, ax
    mov al, [scan_progress_percent]
    call print_decimal16_ax
    mov si, msg_percent_suffix
    call print_string
    ret

set_program:
    call advance_command_token
    cmp byte [si], 0
    je .show

    mov eax, [ram_scan_start]
    mov [pending_ram_start], eax
    mov eax, [ram_scan_page_count]
    mov [pending_ram_page_count], eax
    mov eax, [disk_scan_lba]
    mov [pending_disk_lba], eax
    mov eax, [disk_scan_page_count]
    mov [pending_disk_page_count], eax

.loop:
    call parse_set_option
    jc .invalid
    call skip_spaces
    cmp byte [si], 0
    jne .loop

    call validate_pending_ram_window
    jc .invalid
    call validate_pending_disk_window
    jc .invalid

    mov eax, [pending_ram_start]
    mov [ram_scan_start], eax
    mov eax, [pending_ram_page_count]
    mov [ram_scan_page_count], eax
    mov eax, [pending_disk_lba]
    mov [disk_scan_lba], eax
    mov eax, [pending_disk_page_count]
    mov [disk_scan_page_count], eax
    mov si, msg_set_ok
    call print_string

.show:
    call print_scan_config
    ret

.invalid:
    mov si, msg_set_invalid
    call print_string
    ret

parse_set_option:
    push si
    mov di, opt_ram_start
    call cmdreq
    cmp al, 1
    jne .next_option
    pop si
    call advance_command_token
    call parse_u32
    jc .fail
    and eax, 0xFFFFFE00
    mov [pending_ram_start], eax
    clc
    ret

.next_option:
    pop si
    push si
    mov di, opt_ram_mib
    call cmdreq
    cmp al, 1
    jne .check_disk_lba
    pop si
    call advance_command_token
    call parse_u32
    jc .fail
    shl eax, 11
    mov [pending_ram_page_count], eax
    clc
    ret

.check_disk_lba:
    pop si
    push si
    mov di, opt_disk_lba
    call cmdreq
    cmp al, 1
    jne .check_disk_mib
    pop si
    call advance_command_token
    call parse_u32
    jc .fail
    mov [pending_disk_lba], eax
    clc
    ret

.check_disk_mib:
    pop si
    push si
    mov di, opt_disk_mib
    call cmdreq
    cmp al, 1
    jne .fail_pop
    pop si
    call advance_command_token
    call parse_u32
    jc .fail
    shl eax, 11
    mov [pending_disk_page_count], eax
    clc
    ret

.fail_pop:
    pop si

.fail:
    stc
    ret

validate_pending_ram_window:
    mov eax, [pending_ram_page_count]
    test eax, eax
    jz .fail

    mov edx, [pending_ram_start]
    mov ecx, edx
    shr ecx, 9
    add ecx, eax
    jc .fail
    cmp ecx, MAX_RAM_PAGE_INDEX
    ja .fail
    clc
    ret

.fail:
    stc
    ret

validate_pending_disk_window:
    mov eax, [pending_disk_page_count]
    test eax, eax
    jz .fail

    mov ecx, [pending_disk_lba]
    add ecx, eax
    jc .fail
    cmp ecx, MAX_DISK_PAGE_INDEX
    ja .fail
    clc
    ret

.fail:
    stc
    ret

advance_command_token:
    cmp byte [si], 0
    je .done

.loop:
    cmp byte [si], 0
    je .done
    cmp byte [si], ' '
    je .done
    inc si
    jmp .loop

.done:
    call skip_spaces
    ret

cmdreq:
    push si
    push di

.loop:
    mov al, [di]
    test al, al
    jz .maybe
    cmp al, [si]
    jne .not_equal
    inc si
    inc di
    jmp .loop

.maybe:
    mov al, [si]
    test al, al
    je .equal
    cmp al, ' '
    je .equal

.not_equal:
    xor al, al
    jmp .done

.equal:
    mov al, 1

.done:
    pop di
    pop si
    ret

parse_u32:
    push bx
    push cx
    push dx

    call skip_spaces
    xor eax, eax
    xor bx, bx
    cmp byte [si], 0
    je .fail
    cmp byte [si], '0'
    jne .decimal
    cmp byte [si + 1], 'x'
    je .hex
    cmp byte [si + 1], 'X'
    je .hex

.decimal:
    mov dl, [si]
    test dl, dl
    je .decimal_done
    cmp dl, ' '
    je .decimal_done
    cmp dl, '0'
    jb .fail
    cmp dl, '9'
    ja .fail
    mov ecx, eax
    shl eax, 1
    mov edx, ecx
    shl edx, 3
    add eax, edx
    jc .fail
    xor edx, edx
    mov dl, [si]
    sub dl, '0'
    add eax, edx
    jc .fail
    inc si
    inc bx
    jmp .decimal

.decimal_done:
    test bx, bx
    jz .fail
    clc
    jmp .done

.hex:
    add si, 2

.hex_loop:
    mov dl, [si]
    test dl, dl
    je .hex_done
    cmp dl, ' '
    je .hex_done
    shl eax, 4
    jc .fail
    cmp dl, '0'
    jb .fail
    cmp dl, '9'
    jbe .hex_digit
    cmp dl, 'A'
    jb .hex_lower
    cmp dl, 'F'
    jbe .hex_upper

.hex_lower:
    cmp dl, 'a'
    jb .fail
    cmp dl, 'f'
    ja .fail
    sub dl, 'a' - 10
    jmp .hex_store

.hex_upper:
    sub dl, 'A' - 10
    jmp .hex_store

.hex_digit:
    sub dl, '0'

.hex_store:
    xor edx, edx
    mov dl, [si]
    cmp dl, '0'
    jb .fail
    cmp dl, '9'
    jbe .hex_store_digit
    cmp dl, 'A'
    jb .hex_store_lower
    cmp dl, 'F'
    jbe .hex_store_upper

.hex_store_lower:
    cmp dl, 'a'
    jb .fail
    cmp dl, 'f'
    ja .fail
    sub dl, 'a' - 10
    jmp .hex_apply

.hex_store_upper:
    sub dl, 'A' - 10
    jmp .hex_apply

.hex_store_digit:
    sub dl, '0'

.hex_apply:
    add eax, edx
    jc .fail
    inc si
    inc bx
    jmp .hex_loop

.hex_done:
    test bx, bx
    jz .fail
    clc
    jmp .done

.fail:
    stc

.done:
    pop dx
    pop cx
    pop bx
    ret

maybe_decay_model_counts:
    push ax
    push bx
    push cx
    push si

    mov ax, [scan_epoch]
    xor dx, dx
    mov bx, 10
    div bx
    test dx, dx
    jnz .done

    mov cx, 256
    mov si, model_counts

.loop:
    shr word [si], 1
    add si, 2
    loop .loop

.done:
    pop si
    pop cx
    pop bx
    pop ax
    ret

bios_get_ticks:
    mov ah, 0x00
    int 0x1a
    ret

seed_generation_from_buffer:
    mov byte [generation_prev_nibble], 0

.loop:
    mov al, [si]
    test al, al
    jz .done
    mov dl, al
    shr dl, 4
    mov [generation_prev_nibble], dl
    and al, 0x0f
    mov [generation_prev_nibble], al
    inc si
    jmp .loop

.done:
    ret

model_predict_byte:
    push bx
    push dx

    mov bl, [generation_prev_nibble]
    call model_predict_nibble
    mov dl, al
    mov bl, al
    call model_predict_nibble
    shl dl, 4
    or al, dl
    mov [generation_prev_nibble], al
    and byte [generation_prev_nibble], 0x0f

    pop dx
    pop bx
    ret

model_predict_nibble:
    push bx
    push cx
    push dx
    push si

    shl bx, 4
    shl bx, 1
    mov si, model_counts
    add si, bx
    mov cx, 16
    xor bx, bx
    xor dx, dx

.scan:
    mov ax, [si]
    cmp ax, dx
    jbe .next
    mov dx, ax
    mov bl, 16
    sub bl, cl

.next:
    add si, 2
    loop .scan

    mov al, bl
    pop si
    pop dx
    pop cx
    pop bx
    ret

poll_escape:
    call poll_input_char
    jc .no_key
    cmp al, 27
    jne .no_key
    stc
    ret

.no_key:
    clc
    ret

print_generated_byte:
    cmp al, 10
    je .newline
    cmp al, 13
    je .newline
    cmp al, 32
    jb .dot
    cmp al, 126
    ja .dot
    call print_char
    inc byte [stream_column]
    cmp byte [stream_column], 64
    jb .done
    mov byte [stream_column], 0
    mov si, newline
    call print_string
    ret

.dot:
    mov al, '.'
    call print_char
    inc byte [stream_column]
    cmp byte [stream_column], 64
    jb .done
    mov byte [stream_column], 0
    mov si, newline
    call print_string
    ret

.newline:
    mov byte [stream_column], 0
    mov si, newline
    call print_string

.done:
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
.loop:
    call poll_input_char
    jc .loop
    ret

poll_input_char:
    call serial_poll_char
    jnc .done
    mov ah, 0x01
    int 0x16
    jz .none
    xor ah, ah
    int 0x16

.done:
    clc
    ret

.none:
    stc
    ret

skip_spaces:
.loop:
    cmp byte [si], ' '
    jne .done
    inc si
    jmp .loop

.done:
    ret

streq:
    push si
    push di

.loop:
    mov al, [si]
    cmp al, [di]
    jne .not_equal
    test al, al
    je .equal
    inc si
    inc di
    jmp .loop

.not_equal:
    xor al, al
    jmp .done

.equal:
    mov al, 1

.done:
    pop di
    pop si
    ret

set_text_mode:
    mov ax, 0x0003
    int 0x10
    ret

print_string:
    lodsb
    test al, al
    jz .done
    call print_model_char
    jmp print_string

.done:
    ret

print_model_char:
    cmp al, 10
    jne .raw
    push ax
    mov al, 13
    call print_char
    pop ax

.raw:
    call print_char
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
    call serial_write
    ret

print_hex16_ax:
    push ax
    mov al, ah
    shr al, 4
    call print_hex_nibble_al
    pop ax
    push ax
    mov al, ah
    and al, 0x0f
    call print_hex_nibble_al
    pop ax
    push ax
    shr al, 4
    call print_hex_nibble_al
    pop ax
    and al, 0x0f
    call print_hex_nibble_al
    ret

print_hex32_eax:
    push eax
    shr eax, 16
    call print_hex16_ax
    pop eax
    call print_hex16_ax
    ret

print_hex_byte_al:
    push ax
    shr al, 4
    call print_hex_nibble_al
    pop ax
    and al, 0x0f
    call print_hex_nibble_al
    ret

print_hex_nibble_al:
    and al, 0x0f
    cmp al, 10
    jb .digit
    add al, 'A' - 10
    jmp .emit

.digit:
    add al, '0'

.emit:
    call print_char
    ret

print_decimal16_ax:
    push ax
    push bx
    push cx
    push dx

    test ax, ax
    jnz .convert
    mov al, '0'
    call print_char
    jmp .done

.convert:
    xor cx, cx
    mov bx, 10

.divide:
    xor dx, dx
    div bx
    push dx
    inc cx
    test ax, ax
    jnz .divide

.emit:
    pop dx
    mov al, dl
    add al, '0'
    call print_char
    loop .emit

.done:
    pop dx
    pop cx
    pop bx
    pop ax
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
    mov al, 0xC7
    out dx, al

    mov dx, COM1_PORT + 4
    mov al, 0x0B
    out dx, al
    ret

enable_a20_fast:
    in al, 0x92
    or al, 0x02
    and al, 0xFE
    out 0x92, al
    ret

unreal_init:
    cmp byte [unreal_ready], 1
    je .done
    call enable_a20_fast
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    lgdt [unreal_gdt_descriptor]
    mov eax, cr0
    or eax, 1
    mov cr0, eax
    jmp word UNREAL32_CODE_SEL:unreal_pm32_entry

.done:
    ret

[bits 32]
unreal_pm32_entry:
    mov ax, UNREAL32_DATA_SEL
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    jmp word UNREAL16_CODE_SEL:unreal_exit16

[bits 16]
unreal_exit16:
    mov ax, UNREAL16_DATA_SEL
    mov ds, ax
    mov es, ax
    mov gs, ax
    mov ss, ax
    mov eax, cr0
    and eax, 0xFFFFFFFE
    mov cr0, eax
    jmp 0x0000:unreal_rm_resume

unreal_rm_resume:
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov gs, ax
    mov ss, ax
    mov byte [unreal_ready], 1
    sti
    ret

serial_poll_char:
    push dx
    mov dx, COM1_PORT + 5
    in al, dx
    test al, 0x01
    jz .none
    mov dx, COM1_PORT
    in al, dx
    pop dx
    clc
    ret

.none:
    pop dx
    stc
    ret

serial_write:
    push bx
    push dx
    mov bl, al

.wait:
    mov dx, COM1_PORT + 5
    in al, dx
    test al, 0x20
    jz .wait

    mov dx, COM1_PORT
    mov al, bl
    out dx, al
    pop dx
    pop bx
    ret

msg_banner db "kernel_os v2.0", 10, 0
msg_hint db "page model online. commands: help scan map train chat stream set bench halt", 10, 10, 0
msg_help db "commands:", 10
         db " help    show this message", 10
         db " scan    one pass over the configured RAM and disk windows", 10
         db " map     print the top surprise pages", 10
         db " train   repeated corpus scans until ESC", 10
         db " chat    prompt once, then sample the page model until ESC", 10
         db " stream  sample the page model continuously", 10
         db " set     set ram-start / ram-mib / disk-lba / disk-mib or show scan config", 10
         db " bench   run one timed scan pass", 10
         db " halt    stop the cpu", 10, 0
msg_busy db "command busy: train/chat/stream already own the live loop", 10, 0
msg_unknown db "unknown command", 10, 0
msg_halt db "halting cpu", 10, 0
msg_scan_intro db "scan: scoring the configured unreal RAM and disk windows", 10, 0
msg_scan_prefix db "scan epoch 0x", 0
msg_scan_mid db " top ", 0
msg_scan_suffix db " surprise=0x", 0
msg_map_intro db "page surprise map (top 64, highest first):", 10, 0
msg_map_empty db "page surprise map empty. run scan or train first", 10, 0
msg_map_score db " surprise=0x", 0
msg_train_intro db "train: repeated page scans. press ESC to stop", 10, 0
msg_train_exit db "train: checkpoint saved", 10, 0
msg_chat_intro db "chat: prompt once, then sample the page predictor. press ESC to stop", 10, 0
msg_chat_prefix db "model> ", 0
msg_chat_done db "chat: nothing entered", 10, 0
msg_stream_intro db "stream: sampling page predictor only. generated output no longer executes. press ESC to stop", 10, 0
msg_scan_aborted db "scan: aborted; partial updates were kept", 10, 0
msg_bench_intro db "bench: timing one scan pass", 10, 0
msg_bench_ticks db "bench: BIOS ticks=", 0
msg_bench_ticks_suffix db 10, 0
msg_config_start db "scan-config: ram-start=0x", 0
msg_config_pages db " ram-pages=0x", 0
msg_config_mib db " ram-mib=", 0
msg_config_disk_start db 10, "             disk-lba=0x", 0
msg_config_disk_pages db " disk-pages=0x", 0
msg_config_disk_mib db " disk-mib=", 0
msg_scan_progress_ram db "scan ram ", 0
msg_scan_progress_disk db "scan disk ", 0
msg_percent_suffix db "%", 10, 0
msg_set_ok db "set: updated", 10, 0
msg_set_invalid db "set: usage is `set ram-start 0x100000 ram-mib 16 disk-lba 0x1000 disk-mib 3390`", 10, 0
msg_model_loaded db "model: page state loaded", 10, 0
msg_model_seeded db "model: empty page state initialized; run scan or train to build the corpus map", 10, 0
prompt db "kernel_os> ", 0
prompt_chat db "chat> ", 0
newline db 10, 0
cmd_help db "help", 0
cmd_scan db "scan", 0
cmd_map db "map", 0
cmd_train db "train", 0
cmd_chat db "chat", 0
cmd_stream db "stream", 0
cmd_set db "set", 0
cmd_bench db "bench", 0
cmd_halt db "halt", 0
cmd_exit db "exit", 0
opt_ram_start db "ram-start", 0
opt_ram_mib db "ram-mib", 0
opt_disk_lba db "disk-lba", 0
opt_disk_mib db "disk-mib", 0

boot_drive db 0
active_mode db 0
unreal_ready db 0
current_page_surprise db 0
scan_max_score db 0
scan_max_source db 0
scan_max_label dd 0
generation_prev_nibble db 0
stream_column db 0
ram_scan_linear dd 0
ram_scan_start dd DEFAULT_RAM_SCAN_LINEAR_BASE
ram_scan_page_count dd DEFAULT_RAM_SCAN_PAGES
pending_ram_start dd DEFAULT_RAM_SCAN_LINEAR_BASE
pending_ram_page_count dd DEFAULT_RAM_SCAN_PAGES
disk_scan_lba dd DEFAULT_DISK_SCAN_LBA
disk_scan_page_count dd DEFAULT_DISK_SCAN_PAGES
pending_disk_lba dd DEFAULT_DISK_SCAN_LBA
pending_disk_page_count dd DEFAULT_DISK_SCAN_PAGES
disk_scan_cursor dd 0
disk_chunk_pages dd 0
scan_total_pages dd 0
scan_pages_done dd 0
scan_progress_step dd 0
scan_progress_next dd 0
scan_progress_label dw msg_scan_progress_ram
current_page_label dd 0
scan_progress_percent db 0
scan_progress_increment db 0
scan_aborted db 0
current_page_source db 0
map_last_source db 0
map_last_label dd 0
bench_tick_start dw 0
bench_tick_delta dw 0
input_buffer times INPUT_MAX + 1 db 0
disk_page_buffer times (PAGE_BYTES * DISK_TRANSFER_PAGES) db 0

unreal_gdt:
    dq 0x0000000000000000
    dq 0x00CF9A000000FFFF
    dq 0x00CF92000000FFFF
    dq 0x00009A000000FFFF
    dq 0x000092000000FFFF
unreal_gdt_end:

unreal_gdt_descriptor:
    dw unreal_gdt_end - unreal_gdt - 1
    dw unreal_gdt
    dw 0

model_state_packet:
    db 0x10, 0x00
    dw MODEL_STATE_SECTORS
    dw model_state_start
    dw 0x0000
    dd MODEL_STATE_LBA
    dd 0x00000000

disk_scan_packet:
    db 0x10, 0x00
disk_scan_packet_count dw DISK_TRANSFER_PAGES
    dw disk_page_buffer
    dw 0x0000
disk_scan_lba_low dd DEFAULT_DISK_SCAN_LBA
disk_scan_lba_high dd 0x00000000

model_state_start:
model_signature dd 0
scan_epoch dw 0
page_scores times TOP_PAGE_BYTES db 0
model_counts times 256 dw 0
model_state_end:

model_state_size equ model_state_end - model_state_start
MODEL_STATE_SECTORS equ (model_state_size + PAGE_BYTES - 1) / PAGE_BYTES
