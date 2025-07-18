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
ENGINE_TIME_LIMIT = 0.25
MAX_MOVES_TO_EVALUATE = 50
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
        self.eval_data = pd.DataFrame()
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
        weighted by how long the puzzle took to complete previously"""
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
        self.eval_data = pd.DataFrame  # Clear it out
        self.evaluate_position_with_engine()
        self.evaluate_position_with_maia()
        num_legal_moves = self.board.legal_moves.count()
        assert num_legal_moves == len(
            self.eval_data
        ), f"num_legal_moves {num_legal_moves} != len(self.eval_data){len(self.eval_data)}"

    def evaluate_position_with_engine(self):
        infos = self.engine.analyse(
            self.board,
            chess.engine.Limit(time=ENGINE_TIME_LIMIT),
            multipv=MAX_MOVES_TO_EVALUATE,
        )
        pa = []
        for rank, info in enumerate(infos, start=1):
            pv = info.get("pv", [])
            move = self.board.san(pv[0])
            pv = self.board.variation_san(pv)
            score = info["score"].white().score(mate_score=10000) / 100
            pa.append(
                {"engine_rank": rank, "move": move, "engine_eval": score, "pv": pv}
            )
        self.eval_data = pd.DataFrame(pa)

    def evaluate_position_with_maia(self):
        move_probs, win_prob = inference.inference_each(
            self.maia2_model,
            self.maia2_prepared,
            self.board.fen(),
            MAIA2_ELO,
            MAIA2_ELO,
        )
        self.eval_data["maia_prob"] = 0.0
        for uci_str, prob in move_probs.items():
            move = chess.Move.from_uci(uci_str)
            if self.board.is_legal(move):
                san = self.board.san(move)
                if prob > 0.01:  # Skip tiny and zero prob moves
                    self.eval_data.loc[self.eval_data["move"] == san, "maia_prob"] = (
                        round(prob, 2)
                    )
        self.eval_data["humanness"] = (
            (self.eval_data["maia_prob"] / self.eval_data["maia_prob"].max() * 100)
            .round()
            .astype(int)
        )

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
        self.root.geometry("1600x900")
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
        self.model.evaluate_position()
        current_eval = self.model.eval_data.loc[0, "engine_eval"]
        self.view.log(f"Evaluation: {current_eval:.2f}")
        self.model.start_timer()
        self.result_recorded = False

    def _get_promote_friendly_move(self, from_square, to_square):
        mv = chess.Move(from_square, to_square, promotion=chess.QUEEN)
        return (
            mv
            if mv in self.model.board.legal_moves
            else chess.Move(from_square, to_square, promotion=None)
        )

    def on_click(self, event):

        # TODO: TEST THAT EVALUATION HAS FINISHED!, Otherwise the data isn't ready yet, disallow player input until it's ready

        c, r = event.x // 60, event.y // 60
        sq = chess.square(7 - c, r) if self.model.flip_board else chess.square(c, 7 - r)
        if self.view.selected_square is None:
            if self.model.board.piece_at(sq):
                self.view.selected_square = sq
                self.view.highlight_squares.clear()
                self.view.highlight_squares.append(sq)
        else:
            mv = self._get_promote_friendly_move(self.view.selected_square, sq)
            self.view.highlight_squares.clear()
            self.view.highlight_squares.extend([self.view.selected_square, sq])
            if mv in self.model.board.legal_moves:
                self._process_move(mv)
            else:
                self.view.log("Illegal move!!! Try again...")
            self.view.selected_square = None
        self.view.draw_board()

    def _process_move(self, move):
        current_eval = self.model.eval_data.loc[0, "engine_eval"]
        tag, player_score, diff = self._log_player_move(move, current_eval)
        self._record_time(tag)
        self.model.board.push(move)
        self.view.draw_board()
        self._announce_state()

        self._engine_move()

    def _log_player_move(self, move, best_eval):
        san = self.model.board.san(move)
        move_eval = self.model.eval_data.loc[
            self.model.eval_data["move"] == san, "engine_eval"
        ].iloc[0]
        diff = move_eval - best_eval
        tag = ChessModel.classify_move(
            self.model.board.turn, diff
        )  # TODO: Here? or classify ALL moves at analysis time?!
        rank = self.model.eval_data.loc[
            self.model.eval_data["move"] == san, "engine_rank"
        ].iloc[0]
        self.view.log(self.model.eval_data[:10].to_string())
        self.view.log(
            f"Your move: Top {rank} {san} "
            f"(score={move_eval:.2f}) "
            f"(change={diff:.2f}) {tag}"
        )
        return tag, move_eval, diff

    def _record_time(self, tag):
        if not self.result_recorded:
            correct = tag.startswith("Good")
            ttc = self.model.record_result(self.model.position, correct)
            self.result_recorded = True
            if correct:
                self.view.log(f"Took {time.strftime('%M:%S', time.gmtime(ttc))} ⏰")

    def _engine_move(self):
        if self.model.board.is_game_over():
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
        self._announce_state()
        if self.model.board.is_game_over():
            return
        self.model.evaluate_position()
        current_eval = self.model.eval_data.loc[0, "engine_eval"]
        self.view.log(f"Evaluation: {current_eval:.2f}")

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
