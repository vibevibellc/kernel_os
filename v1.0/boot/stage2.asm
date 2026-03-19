[bits 16]
[org 0x8000]

%include "boot/stage2/01_entry_io.asm"
%include "boot/stage2/02_systems.asm"
%include "boot/stage2/03_programs.asm"
%include "boot/stage2/04_commands_messages.asm"
%include "boot/stage2/05_state_tables.asm"
