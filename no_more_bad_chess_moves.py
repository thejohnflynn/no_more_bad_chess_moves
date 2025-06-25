import os
import random
import math
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageTk
import chess
import chess.engine


STOCKFISH_PATH = "/opt/homebrew/bin/stockfish"
POSITIONS_FILE = "positions.txt"
ENGINE_TIME_LIMIT = 0.5
TOP_N = 3
DARK_COLOR = "#669966"
LIGHT_COLOR = "#99CC99"


class ChessModel:
    def __init__(self):
        self.engine = None
        self.board = None
        self.positions = []
        self.position_idx = 0
        self.flip_board = False
        self.piece_images = {}

    def start_engine(self):
        self.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)

    def stop_engine(self):
        if self.engine:
            self.engine.quit()

    def load_positions(self):
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE) as f:
                self.positions = [line.strip() for line in f if line.strip()]
        else:
            self.positions = [""]
        random.shuffle(self.positions)

    def load_piece_images(self, scale=1.0):
        for color in ("b", "w"):
            for pt in ("P", "R", "N", "B", "Q", "K"):
                fname = f"images/{color}{pt}.png"
                pil = Image.open(fname)
                if scale != 1.0:
                    w, h = pil.size
                    pil = pil.resize(
                        (int(w * scale), int(h * scale)), resample=Image.LANCZOS
                    )
                self.piece_images[color + pt] = ImageTk.PhotoImage(pil)

    def new_position(self):
        fen = self.positions[self.position_idx]
        try:
            self.board = chess.Board(fen) if fen else chess.Board()
        except ValueError:
            self.board = chess.Board()
        self.flip_board = not self.board.turn
        return fen

    def next_position(self):
        self.position_idx = (self.position_idx + 1) % len(self.positions)
        return self.new_position()

    def evaluate_position(self):
        info = self.engine.analyse(
            self.board, chess.engine.Limit(time=ENGINE_TIME_LIMIT)
        )
        return info["score"].white().score(mate_score=10000) / 100

    def get_top_moves(self):
        infos = self.engine.analyse(
            self.board, chess.engine.Limit(time=ENGINE_TIME_LIMIT), multipv=TOP_N
        )
        top = []
        for info in infos:
            pv = info.get("pv", [])
            score = info["score"].white().score(mate_score=10000) / 100
            top.append((pv, score))
        return top

    def evaluate_move(self, move):
        tmp = self.board.copy()
        tmp.push(move)
        info = self.engine.analyse(tmp, chess.engine.Limit(time=ENGINE_TIME_LIMIT))
        return info["score"].white().score(mate_score=10000) / 100

    @staticmethod
    def classify_move(is_white_to_move, diff):
        if is_white_to_move:
            if diff >= -1:
                return "Good"
            elif diff >= -3:
                return "Mistake"
            else:
                return "Blunder"
        else:
            if diff <= 1:
                return "Good"
            elif diff <= 3:
                return "Mistake"
            else:
                return "Blunder"


class ChessView:
    def __init__(self, root, model):
        self.root = root
        self.model = model
        self.selected_square = None
        self.highlight_squares = []

        self.root.title("no more bad chess moves")
        self.root.geometry("1000x700")
        self.root.resizable(True, True)

        btn_frame = tk.Frame(root)
        btn_frame.pack(side="top", fill="x")
        inner = tk.Frame(btn_frame)
        inner.pack()
        self.reload_btn = tk.Button(inner, text="Reload Position")
        self.next_btn = tk.Button(inner, text="Next Position")
        self.reload_btn.pack(side="left", padx=0, pady=5)
        self.next_btn.pack(side="left", padx=5, pady=5)

        frame = tk.Frame(root)
        frame.pack(side="top")
        self.board_canvas = tk.Canvas(frame, width=480, height=480)
        self.board_canvas.pack(side="left")

        self.status_label = tk.Label(
            root, text="", font=("Arial", 12), pady=3, anchor="w"
        )
        self.status_label.pack(side="bottom", fill="x")

        txt_frame = tk.Frame(root)
        txt_frame.pack(side="bottom", fill="both", expand=True)
        self.log_text = ScrolledText(txt_frame, height=6, wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.tag_configure("Good", background="#669966")
        self.log_text.tag_configure("Mistake", background="#b4722f")
        self.log_text.tag_configure("Blunder", background="#df5757")

    def draw_board(self):
        self.board_canvas.delete("all")
        board = self.model.board
        for r in range(8):
            for c in range(8):
                sq = (
                    chess.square(7 - c, r)
                    if self.model.flip_board
                    else chess.square(c, 7 - r)
                )
                base = DARK_COLOR if (r + c) % 2 == 0 else LIGHT_COLOR
                color = base
                if sq in self.highlight_squares:
                    color = self._lighten(color, 0.3)
                x0, y0 = c * 60, r * 60
                x1, y1 = x0 + 60, y0 + 60
                self.board_canvas.create_rectangle(
                    x0, y0, x1, y1, fill=color, outline=color
                )
                p = board.piece_at(sq)
                if p:
                    key = ("w" if p.color else "b") + p.symbol().upper()
                    img = self.model.piece_images.get(key)
                    self.board_canvas.create_image(x0 + 30, y0 + 30, image=img)

    def log(self, msg, tag=None):
        print(msg)
        self.log_text.insert("end", msg + "\n", tag)
        self.log_text.see("end")

    @staticmethod
    def _lighten(hex_color, factor):
        hex_color = hex_color.lstrip("#")
        r, g, b = [int(hex_color[i : i + 2], 16) for i in (0, 2, 4)]
        r = min(int(r + (255 - r) * factor), 255)
        g = min(int(g + (255 - g) * factor), 255)
        b = min(int(b + (255 - b) * factor), 255)
        return f"#{r:02x}{g:02x}{b:02x}"


class ChessController:
    def __init__(self, root):
        self.model = ChessModel()
        self.view = ChessView(root, self.model)
        self._bind_events()
        self._setup()

    def _bind_events(self):
        self.view.board_canvas.bind("<Button-1>", self.on_click)
        self.view.reload_btn.config(command=self.reload_position)
        self.view.next_btn.config(command=self.next_position)

    def _setup(self):
        self.model.start_engine()
        self.model.load_positions()
        self.model.load_piece_images(scale=0.725)
        fen = self.model.new_position()
        self._refresh(fen)

    def reload_position(self):
        fen = self.model.new_position()
        self._refresh(fen)

    def next_position(self):
        fen = self.model.next_position()
        self._refresh(fen)

    def _refresh(self, fen):
        self.view.highlight_squares.clear()
        self.view.selected_square = None
        self.view.log_text.delete("1.0", "end")
        self.view.draw_board()
        self.view.log(f"FEN: {fen}")
        ev = self.model.evaluate_position()
        self.view.log(f"Evaluation: {ev:.2f}")

    def on_click(self, event):
        c, r = event.x // 60, event.y // 60
        sq = chess.square(7 - c, r) if self.model.flip_board else chess.square(c, 7 - r)
        if self.view.selected_square is None:
            if self.model.board.piece_at(sq):
                self.view.selected_square = sq
                self.view.highlight_squares.clear()
                self.view.highlight_squares.append(sq)
        else:
            mv = chess.Move(self.view.selected_square, sq)
            self.view.highlight_squares.clear()
            self.view.highlight_squares.extend([self.view.selected_square, sq])
            if mv in self.model.board.legal_moves:
                self._process_move(mv)
            self.view.selected_square = None
        self.view.draw_board()

    def _process_move(self, move):
        top = self.model.get_top_moves()
        for i, (pv, sc) in enumerate(top):
            temp = self.model.board.copy()
            san_line = []
            for m in pv:
                if m is None:
                    break
                san_line.append(temp.san(m))
                temp.push(m)
            first = san_line[0] if san_line else ""
            cont = " ".join(san_line)
            self.view.log(f"Top {i+1}: {first} (score={sc:.2f}) ({cont})")
        player_sc = self.model.evaluate_move(move)
        diff = player_sc - top[0][1]
        tag = ChessModel.classify_move(self.model.board.turn, diff)
        san = self.model.board.san(move)
        # rank detection
        first_moves = [pv[0] for pv, _ in top if pv]
        rank = ""
        if move in first_moves:
            rank = f"Top {first_moves.index(move)+1}: "
        self.view.log(
            f"Your move: {rank}{san} (score={player_sc:.2f}) (change={diff:.2f}) {tag}",
            tag,
        )
        self.model.board.push(move)
        self.view.draw_board()
        self._announce_state()
        self._engine_move()

    def _engine_move(self):
        if self.model.board.is_game_over():
            self.view.log("Game over.")
            return
        res = self.model.engine.play(
            self.model.board, chess.engine.Limit(time=ENGINE_TIME_LIMIT)
        )
        mv = res.move
        san = self.model.board.san(mv)
        self.model.board.push(mv)
        self.view.highlight_squares.clear()
        self.view.highlight_squares.extend([mv.from_square, mv.to_square])
        self.view.draw_board()
        self.view.log(f"Engine plays: {san}")
        ev = self.model.evaluate_position()
        self.view.log(f"Evaluation: {ev:.2f}")
        self._announce_state()

    def _announce_state(self):
        b = self.model.board
        if b.is_checkmate():
            self.view.log("Checkmate! Game Over.")
        elif b.is_stalemate():
            self.view.log("Stalemate! Game Over.")
        elif b.is_insufficient_material():
            self.view.log("Draw (insufficient material). Game Over.")
        elif b.is_check():
            self.view.log("Check!")


if __name__ == "__main__":
    root = tk.Tk()
    app = ChessController(root)
    root.mainloop()
    app.model.stop_engine()
