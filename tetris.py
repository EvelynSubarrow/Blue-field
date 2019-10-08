#!/usr/bin/env python3

import time, random, queue, copy
import serial
import bluefield

# If bluefield is changed to allow for slightly more intelligent detection
# Then this should probably be substituted
DISPLAY_WIDTH = 80
DISPLAY_HEIGHT = 24

# This, on the other hand, is canonically how it ought to be
TETRIS_WIDTH = 10
TETRIS_HEIGHT = 24

# For 24x80 displays, two characters gives the appearance of a square.
# Alternative display modes might render this necessary
TETRIS_WIDTH_MULTIPLIER =2

TETRIS_START_COLS = (DISPLAY_WIDTH>>1) - ((TETRIS_WIDTH*TETRIS_WIDTH_MULTIPLIER)>>1)

class Tetromino(bluefield.Matrix):
    def __init__(self, matrix):
        super().__init__(0,0, matrix=matrix)
        self.y, self.x = 1,1

    def copy(self):
        return Tetromino(self._list)

    def is_occupying(self, y,x):
        for matrix_y, row in enumerate(self._list):
            for matrix_x, col in enumerate(row):
                if (self.y+matrix_y, self.x+matrix_x)==(y,x):
                    return bool(col)
        return 0

    def occupation(self):
        out = []
        for matrix_y, row in enumerate(self._list):
            for matrix_x, col in enumerate(row):
                if bool(col):
                    out.append((self.y+matrix_y, self.x+matrix_x))
        return out

    def try_rotate(self, width_limit):
        newlist = copy.deepcopy(self._list)
        for y, row in enumerate(self._list):
            for x, col in enumerate(row):
                #newlist[self.dimensions_x-1-x][y] = col
                newlist[x][self.dimensions_y-1-y] = col
                if self.x+x < 0 or self.x+x >= width_limit:
                    return False
        self._list = newlist
        return True

tetrominoes = []
def add_tetromino(m):
    tetrominoes.append(Tetromino(matrix=m))

# Null piece
NULL_PIECE = Tetromino(matrix=[
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    ])

# 'I'
add_tetromino([
    [0, 0, 0, 0],
    [1, 1, 1, 1],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    ])

# 'J'
add_tetromino([
    [0, 0, 1],
    [1, 1, 1],
    [0, 0, 0],
    ])

# 'O'
add_tetromino([
    [1, 1],
    [1, 1],
    ])

# 'S'
add_tetromino([
    [0, 1, 1],
    [1, 1, 0],
    [0, 0, 0],
    ])

# 'T'
add_tetromino([
    [0, 1, 0],
    [1, 1, 1],
    [0, 0, 0],
    ])

# 'Z'
add_tetromino([
    [1, 1, 0],
    [0, 1, 1],
    [0, 0, 0],
    ])

with bluefield.VT220(serial.Serial('/dev/ttyUSB1', 9600, timeout=1)) as t:
    t.soft_reset()
    t.cursor_on = False

    next_piece = NULL_PIECE
    current_piece = NULL_PIECE

    tetris_field = bluefield.Matrix(TETRIS_HEIGHT,TETRIS_WIDTH, None)

    # Places initial borders
    for x in [TETRIS_START_COLS-1, TETRIS_START_COLS+TETRIS_WIDTH*TETRIS_WIDTH_MULTIPLIER]:
        for y in range(1,TETRIS_HEIGHT+1):
            t._next_state[y,x] = ("x", '', "0")

    high_score = 0
    score = 0
    game_over = True

    iteration_counter = 0
    while True:
        iteration_counter += 1

        # Interpret left arrow (D), right arrow (C), and up (A)
        try:
            while True:
                ch = t.receive_queue.get(False)
                if game_over:
                    game_over = False
                    tetris_field.reset()
                    score = 0
                    next_piece = random.choice(tetrominoes).copy()
                    current_piece = random.choice(tetrominoes).copy()
                else:
                    if ch==b"\x9BA":
                        if not current_piece.try_rotate(TETRIS_WIDTH):
                            t.send("\x07")
                    elif ch==b"\x9BD":
                        if any([x==1 or tetris_field[y,x-1] for y,x in current_piece.occupation()]):
                            t.send("\x07")
                        else:
                            current_piece.x -=1
                    elif ch==b"\x9BC":
                        if any([x==TETRIS_WIDTH or tetris_field[y,x+1] for y,x in current_piece.occupation()]):
                            t.send("\x07")
                        else:
                            current_piece.x += 1
        except queue.Empty:
            pass

        # Get rid of filled lines, drop anything above, add to the score
        for y in range(TETRIS_HEIGHT, 0, -1):
            # Clear out the line
            if tetris_field[y]==[1]*TETRIS_WIDTH:
                tetris_field[y] = [0]*TETRIS_WIDTH
                score += 100
                high_score = max(score, high_score)
            # ... and drop the line above
            if tetris_field[y]==[0]*TETRIS_WIDTH and y!=1:
                tetris_field[y]=tetris_field[y-1]
                tetris_field[y-1]=[0]*TETRIS_WIDTH

        # Display current scores, high score flashing if you're currently setting it
        t._next_state.put(2,2, "Current Score {:>6}".format(score))
        t._next_state.put(3,2, "High Score    {:>6}".format(high_score), "f"*(score and score==high_score))

        # Useful to know if true
        t._next_state.put(5,2, "Any key for new game"*game_over or " "*20)

        # If the piece is at the bottom, or there's anything below it
        if any([y==TETRIS_HEIGHT or tetris_field.get(y+1,x) for y,x in current_piece.occupation()]):
            # Write the piece into the field
            for y,x in current_piece.occupation():
                tetris_field[y,x] = 1

            # Game over
            if current_piece.y==1:
                game_over = True
                next_piece = NULL_PIECE
                current_piece = NULL_PIECE
            else:
                # Introduce a new piece, select a new next piece
                current_piece = next_piece
                next_piece = random.choice(tetrominoes).copy()
        else:
            # Gravity hurts
            current_piece.y += 1

        # Interpolation - this ensures that the finalised tetrominoes are
        # correctly translated, and doubles as an eraser for the moving tetris pieces
        for x in range(1, TETRIS_WIDTH+1):
            translated_x = x*TETRIS_WIDTH_MULTIPLIER + TETRIS_START_COLS - TETRIS_WIDTH_MULTIPLIER
            for y in range(1, TETRIS_HEIGHT+1):
                for m in range(TETRIS_WIDTH_MULTIPLIER):
                    if tetris_field[y, x] or current_piece.is_occupying(y,x):
                        t._next_state[y, translated_x + m] = (" ", "r", "B")
                    else:
                        t._next_state[y, translated_x + m] = (" "*bool(m&1) or "~", '', "0")

        # Draw the next piece
        next_y, next_x = (DISPLAY_HEIGHT>>1)-2, TETRIS_START_COLS-5*TETRIS_WIDTH_MULTIPLIER

        for x in range(1,5):
            translated_x = x*TETRIS_WIDTH_MULTIPLIER + next_x - TETRIS_WIDTH_MULTIPLIER
            for y in range(1,5):
                for m in range(TETRIS_WIDTH_MULTIPLIER):
                    if next_piece.is_occupying(y,x):
                        t._next_state[next_y+y, translated_x + m] = (" ", "r", "B")
                    else:
                        t._next_state[next_y+y, translated_x + m] = (" ", '', "B")

        # Write it to the terminal
        t.flush()

        # Terminals don't like being given too much at once
        if iteration_counter==1:
            time.sleep(2)
        else:
            time.sleep(0.5)
