#!/usr/bin/env python3
"""16x16 byte-grid pointer simulation with terminal visualization."""

from __future__ import annotations

import argparse
import time


GRID_SIZE = 16
BYTE_MASK = 0xFF


def clear_screen() -> None:
    print("\033[2J\033[H", end="")


def render(grid: list[list[int]], row: int, col: int, step: int) -> None:
    clear_screen()
    print(f"16x16 Byte Grid Simulation | Step: {step} | Pointer: ({row}, {col})")
    print("Press Ctrl+C to stop.\n")

    for i, line in enumerate(grid):
        cells = []
        for j, value in enumerate(line):
            cell = f"{value:02X}"
            if i == row and j == col:
                cells.append(f"[{cell}]")
            else:
                cells.append(f" {cell} ")
        print("".join(cells))


def run_simulation(delay: float) -> None:
    grid = [[0 for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
    pointer = 0
    step = 0
    total_cells = GRID_SIZE * GRID_SIZE

    while True:
        row, col = divmod(pointer, GRID_SIZE)
        grid[row][col] = (grid[row][col] + 1) & BYTE_MASK
        step += 1

        render(grid, row, col, step)
        time.sleep(delay)

        pointer = (pointer + 1) % total_cells


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Visualize a 16x16 byte grid. A pointer moves across each cell and "
            "increments it with a fixed delay between updates."
        )
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay in seconds between pointer increments (default: 0.5).",
    )
    args = parser.parse_args()

    if args.delay < 0:
        parser.error("--delay must be >= 0.")

    return args


def main() -> None:
    args = parse_args()
    try:
        run_simulation(args.delay)
    except KeyboardInterrupt:
        print("\nSimulation stopped.")


if __name__ == "__main__":
    main()
