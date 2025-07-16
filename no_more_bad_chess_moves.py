import time
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageTk
import pandas as pd
import chess
import chess.engine
from maia2 import model, inference


STOCKFISH_PATH = "/opt/homebrew/bin/stockfish"
POSITIONS_FILE = "positions_auto.csv"
ENGINE_TIME_LIMIT = 0.5
TOP_N = 3
INACCURACY_THRESHOLD = -0.8
MISTAKE_THRESHOLD = -1.7
BLUNDER_THRESHOLD = -2.8
DARK_COLOR = "#669966"
LIGHT_COLOR = "#99CC99"
DEFAULT_TIME_TO_COMPLETE = 300
MAIA2_ELO = 2000


class ChessModel:
    def __init__(self):
        self.engine = None
        self.board = None
        self.positions = pd.DataFrame()
        self.position = ""
        self.flip_board = False
        self.piece_images = {}
        self.maia2_model = model.from_pretrained(type="rapid", device="cpu")
        self.maia2_prepared = inference.prepare()

    def start_engine(self):
        self.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)

    def stop_engine(self):
        if self.engine:
            self.engine.quit()

    def load_positions(self):
        self.positions = pd.read_csv(POSITIONS_FILE)

    def save_positions(self):
        self.positions.sort_values(by="time_to_complete", ascending=True, inplace=True)
        self.positions.to_csv(POSITIONS_FILE, index=False)

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

    def sample_new_position(self):
        """Samples a position from dataset
        weighted by how long it took to complete previously"""
        sample = self.positions.sample(n=1, weights="time_to_complete")
        fen = sample.iloc[0]["position"].strip()
        self.position = fen
        self.load_position_to_board(fen)
        return fen

    def load_position_to_board(self, fen):
        try:
            self.board = chess.Board(fen) if fen else chess.Board()
        except ValueError:
            self.board = chess.Board()
        self.flip_board = not self.board.turn

    def reload_position(self):
        self.load_position_to_board(self.position)
        return self.position

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

        move_probs, win_prob = inference.inference_each(
            self.maia2_model,
            self.maia2_prepared,
            self.board.fen(),
            MAIA2_ELO,
            MAIA2_ELO,
        )
        move_probs_san = {}
        for uci_str, prob in move_probs.items():
            try:
                move = chess.Move.from_uci(uci_str)
                if self.board.is_legal(move):
                    san = self.board.san(move)
                    if prob > 0.01:  # Skip tiny and zero prob moves
                        move_probs_san[san] = round(prob, 2)
            except:
                pass  # Skip invalid or illegal moves

        return top, move_probs_san

    def evaluate_move(self, move):
        tmp = self.board.copy()
        tmp.push(move)
        info = self.engine.analyse(tmp, chess.engine.Limit(time=ENGINE_TIME_LIMIT))
        return info["score"].white().score(mate_score=10000) / 100

    def start_timer(self):
        self._timer_start = time.time()

    def record_result(self, fen: str, correct: bool):
        elapsed = time.time() - self._timer_start
        ttc = elapsed if correct else DEFAULT_TIME_TO_COMPLETE
        self.positions.loc[
            self.positions["position"].str.strip() == fen.strip(), "time_to_complete"
        ] = ttc
        self.save_positions()
        return ttc

    @staticmethod
    def classify_move(is_white_to_move, diff):
        val = diff if is_white_to_move else -diff
        if val >= INACCURACY_THRESHOLD:
            return "Good ✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅"
        if val >= MISTAKE_THRESHOLD:
            return "Inaccuracy 🟦 🟦 🟦 🟦 🟦 🟦 🟦 🟦 🟦"
        if val >= BLUNDER_THRESHOLD:
            return "Mistake ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️"
        return "Blunder 🛑 🛑 🛑 🛑 🛑 🛑 🛑 🛑 🛑"


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

    def log(self, msg):
        print(msg)
        self.log_text.insert("end", msg + "\n")
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
        self.result_recorded = False
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
        fen = self.model.sample_new_position()
        self._refresh(fen)

    def reload_position(self):
        fen = self.model.reload_position()
        self._refresh(fen)

    def next_position(self):
        fen = self.model.sample_new_position()
        self._refresh(fen)

    def _refresh(self, fen):
        self.view.highlight_squares.clear()
        self.view.selected_square = None
        self.view.log_text.delete("1.0", "end")
        self.view.draw_board()
        self.view.log(f"FEN: {fen}")
        ev = self.model.evaluate_position()
        self.view.log(f"Evaluation: {ev:.2f}")
        self.model.start_timer()
        self.result_recorded = False

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
        top, maia2_move_probs = self.model.get_top_moves()
        self._log_top_engine_lines(top, maia2_move_probs)

        tag, player_score, diff = self._log_player_move(move, top[0][1])
        self._record_time(tag)

        self.model.board.push(move)
        self.view.draw_board()
        self._announce_state()

        self._engine_move()

    def _log_top_engine_lines(self, top, maia2_move_probs):
        for i, (pv, score) in enumerate(top, start=1):
            tmp = self.model.board.copy()
            san_list = []
            for m in pv:
                if m is None:
                    break
                san_list.append(tmp.san(m))
                tmp.push(m)
            first = san_list[0] if san_list else ""
            cont = " ".join(san_list)
            self.view.log(f"Top {i}: {first} (score={score:.2f}) ({cont})")
        self.view.log(f"Maia2: {maia2_move_probs}")

    def _log_player_move(self, move, top_score):
        player_score = self.model.evaluate_move(move)
        diff = player_score - top_score
        tag = ChessModel.classify_move(self.model.board.turn, diff)
        san = self.model.board.san(move)

        # detect ranking in the PV
        top, _ = self.model.get_top_moves()
        first_moves = [pv[0] for pv, _ in top if pv]
        rank = f"Top {first_moves.index(move)+1}: " if move in first_moves else ""
        self.view.log(
            f"Your move: {rank}{san} "
            f"(score={player_score:.2f}) "
            f"(change={diff:.2f}) {tag}"
        )
        return tag, player_score, diff

    def _record_time(self, tag):
        if not self.result_recorded:
            correct = tag.startswith("Good")
            ttc = self.model.record_result(self.model.position, correct)
            self.result_recorded = True
            if correct:
                self.view.log(f"Took {time.strftime('%M:%S', time.gmtime(ttc))} ⏰")

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
