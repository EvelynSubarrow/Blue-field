#!/usr/bin/env python3

import sys, select, threading, queue

EMPTY_CELL = (" ",'',"B")

class Matrix:
    def __init__(self, dimensions_y, dimensions_x, matrix=None, default=None):
        self.dimensions_x,self.dimensions_y = dimensions_x,dimensions_y
        self.default = default
        self.reset()
        if matrix:
            self.dimensions_x = len(matrix[0])
            self.dimensions_y = len(matrix)
            self._list = matrix

    def reset(self):
        self._list = []
        for y in range(self.dimensions_y):
            self._list.append([self.default for x in range(self.dimensions_x)])

    def __getitem__(self, coordinates):
        if isinstance(coordinates, int):
            return self._list[coordinates-1]
        else:
            return self._list[coordinates[0]-1][coordinates[1]-1]

    def __setitem__(self, coordinates, content):
        if isinstance(coordinates, int):
            self._list[coordinates-1] = content
        else:
            self._list[coordinates[0]-1][coordinates[1]-1] = content

    def get(self, y, x, default=None):
        if y<1 or x<1 or y>self.dimensions_y or x>self.dimensions_x:
            return default
        else:
            return self[y,x]

class CharMatrix(Matrix):
    def put(self, y, x, string, attrib='', charset="B"):
        cy,cx = y,x
        for ch in string:
            if ch=="\r":
                cx = x
            elif ch=="\n":
                cy += 1
            else:
                self[cy,cx] = (ch, attrib, charset)
                cx += 1

class Terminal:
    def __init__(self, file):
        self.file = file
        self.cursor_visible = True
        self.buffer_read = b""
        self.buffer_write = b""
        self.thread = None
        self.live = True
        self.receive_queue = queue.Queue()

    def __enter__(self):
        self.file.__enter__()
        self._start()
        return self

    def __exit__(self, type, value, tb):
        self.live = False
        return self.file.__exit__(type, value, tb)

    def send(self, text):
        self.send_raw(text.encode("ascii"))

    def send_raw(self, text):
        self.buffer_write += text

    def _thread_fn(self):
        while self.live:
            ready_read, ready_write, error = select.select([self.file],[self.file]*bool(self.buffer_write), [], 0.5)
            if self.file in ready_write and self.buffer_write:
                self.buffer_write = self.buffer_write[self.file.write(self.buffer_write):]
            if self.file in ready_read:
                self.buffer_read += self.file.read(4096)
                sequence = b""

                for ch in self.buffer_read:
                    ch = ch.to_bytes(1, sys.byteorder)
                    if len(sequence):
                        sequence += ch
                        if ch.isalpha():
                            self.receive_queue.put(sequence)
                            self.buffer_read = self.buffer_read[len(sequence):]
                            sequence = b""
                    elif ch==b"\x9B":
                        sequence = ch
                    else:
                        self.receive_queue.put(ch)
                        self.buffer_read = self.buffer_read[1:]

    def _start(self):
        self.thread = threading.Thread(target=self._thread_fn)
        self.thread.start()

class VT220(Terminal):
    CSI = b"\x9B"
    ESC = b"\x1B"

    def __init__(self, file):
        super().__init__(file)
        self._current_charset = ""
        self._current_attributes = ""
        self._current_cursor_pos = (None,None)
        self._state = CharMatrix(24,80, default=EMPTY_CELL)
        self._next_state = CharMatrix(24,80, default=EMPTY_CELL)

    def flush(self):
        self._frame_erasure = {}
        for y in range(self._next_state.dimensions_y):
            y +=1
            erasure = []
            for x in range(self._next_state.dimensions_x):
                x +=1
                if self._next_state[y,x]!=self._state[y,x]:
                    char, attributes, charset = self._next_state[y,x]
                    if (not char or char==" ") and not attributes and charset=="B":
                        if not len(erasure)&1:
                            erasure.append(x)
                    else:
                        if len(erasure)&1:
                            erasure.append(x)
                        self.cursor_position(y,x)
                        self.set_attributes(attributes)
                        self.set_charset(charset)
                        self._puts(char)
                        self._state[y,x] = self._next_state[y,x]
                else:
                    char, attributes, charset = self._state[y,x]
                    if len(erasure)&1 and (char and char!=" " or attributes or charset!="B"):
                        erasure.append(x)
            if erasure and len(erasure)&1:
                erasure.append(81)
            if erasure:
                for erase_start, erase_end in list(zip(*[iter(erasure)]*2)):
                    self.cursor_position(y,erase_start)
                    self.set_attributes("0")
                    self.send_raw(b"\x9B%dX" % (erase_end-erase_start))
                for x in range(erase_start,erase_end):
                    self._state[y,x] = (" ", '', "B")
                    self._frame_erasure[(y,x)] = True

    def clear(self):
        self.send_raw(b"\x1B[J")

    def reset(self):
        self.send_raw(b"\x9B!p")

    def hard_reset(self):
        self.send_raw(b"\x1Bc")

    def cursor_position(self,y,x):
        if self._current_cursor_pos!=(y,x):
            self.send_raw(b"\x9B%d;%dH" % (y,x))
            self._current_cursor_pos = (y,x)

    def _cursor_up(self,n=1):
        if n and n!=1:
            self.send_raw(b"\x9B%dA" % n)
        else:
            self.send_raw(b"\x9BA")

    def _cursor_down(self,n=1):
        if n and n!=1:
            self.send_raw(b"\x9B%dB" % n)
        else:
            self.send_raw(b"\x9BB")

    def _cursor_left(self,n=1):
        if n and n!=1:
            self.send_raw(b"\x9B%dC" % n)
        else:
            self.send_raw(b"\x9BC")

    def _cursor_right(self,n=1):
        if n and n!=1:
            self.send_raw(b"\x9B%dD" % n)
        else:
            self.send_raw(b"\x9BD")

    def cursor_on(self, state):
        self.cursor_visible = bool(state)
        if state:
            self.send_raw(b"\x9B?25h")
        else:
            self.send_raw(b"\x9B?25l")

    def inverted_video(self):
        self.send_raw(b"\x9B?5h")

    def non_inverted_video(self):
        self.send_raw(b"\x9B?5l")

    def set_cols_80(self):
        self.send_raw(b"\x9B?3l")

    def set_cols_132(self):
        self.send_raw(b"\x9B?3h")

    def set_charset(self, charset):
        if charset!=self._current_charset:
            self.send_raw(b"\x1B(%s" % charset.encode("ascii"))
            self._current_charset = charset

    def set_attributes(self, attributes):
        if sorted(attributes)==sorted(self._current_attributes): return
        if any([a not in attributes for a in self._current_attributes]) and not attributes.startswith("0"):
            attributes = "0" + attributes
        self.send_raw(b"\x9B" + b';'.join([{"0":b"0", "b": b"1", "u": b"4", "f": b"5", "r": b"7"}[a] for a in attributes]) + b"m")

        for a in attributes:
            if a=="0":
                self._current_attributes = ""
            elif a not in self._current_attributes:
                self._current_attributes += a

    def soft_reset(self):
        self.set_cols_80()
        self.set_charset("B")
        self.set_attributes("0")
        self.cursor_position(1,1)
        self._state.reset()
        self.clear()

    def _puts(self, text):
        self.send(text)
        self._current_cursor_pos = (self._current_cursor_pos[0],min(self._current_cursor_pos[1]+len(text),80))
