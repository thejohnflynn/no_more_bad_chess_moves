import chess
import chess.engine
import os
import yaml
import random
import math
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageTk

root = tk.Tk()
root.geometry("1000x700")
root.resizable(True, True)
engine = None
board = None
positions = []
position_idx = 0
canvas = None
eval_canvas = None
status_label = None
log_text_widget = None
highlight_squares = []
flip_board = False
piece_images = {}

STOCKFISH_PATH = "/opt/homebrew/bin/stockfish"
POSITIONS_FILE = "positions.txt"
ENGINE_TIME_LIMIT = 0.5
TOP_N = 3
DARK_COLOR = "#669966"
LIGHT_COLOR = "#99CC99"
SHOW_EVAL_BAR = False


def load_positions():
    global positions
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            positions = [line.strip() for line in f if line.strip()]
    else:
        positions = [""]
    random.shuffle(positions)


def load_piece_images(scale: float = 1.0):
    """
    Loads bP.png, wK.png, etc., resizes each by `scale` (e.g. 0.8), and
    stores a PhotoImage in piece_images['wK'], etc.
    """
    for color in ("b", "w"):
        for pt in ("P", "R", "N", "B", "Q", "K"):
            fname = f"images/{color}{pt}.png"
            try:
                pil = Image.open(fname)
            except Exception as e:
                raise RuntimeError(f"Failed to open {fname}: {e}")
            if scale != 1.0:
                w, h = pil.size
                pil = pil.resize(
                    (int(w * scale), int(h * scale)), resample=Image.LANCZOS
                )
            piece_images[color + pt] = ImageTk.PhotoImage(pil)


def log_message(msg, tag=None):
    print(msg)
    if log_text_widget:
        log_text_widget.insert("end", msg + "\n", tag)
        log_text_widget.see("end")


def get_top_moves(board):
    infos = engine.analyse(
        board, chess.engine.Limit(time=ENGINE_TIME_LIMIT), multipv=TOP_N
    )
    top_moves = []
    for info in infos:
        pv_list = info.get("pv", [])
        score = info["score"].white().score(mate_score=10000) / 100
        top_moves.append((pv_list, score))
    return top_moves


def display_top_lines(board, top_moves):
    for i, (pv_list, sc) in enumerate(top_moves):
        temp_board = board.copy()
        san_line = []
        for m in pv_list:
            if m is None:
                break
            san_line.append(temp_board.san(m))
            temp_board.push(m)
        first_san = san_line[0] if san_line else ""
        continuation = " ".join(san_line) if san_line else ""
        log_message(f"Top {i+1}: {first_san} (score={sc:.2f}) ({continuation})")


def evaluate_move(board, move):
    tmp = board.copy()
    tmp.push(move)
    info = engine.analyse(tmp, chess.engine.Limit(time=ENGINE_TIME_LIMIT))
    return info["score"].white().score(mate_score=10000) / 100


def determine_diff_rank(move, top_moves, player_score):
    best_score = top_moves[0][1]
    first_moves = [pv_list[0] for pv_list, _ in top_moves if pv_list]
    if move == first_moves[0]:
        return 0.0, "Top 1"
    diff = player_score - best_score
    rank_num = next((i + 1 for i, mv in enumerate(first_moves) if mv == move), None)
    rank = f"Top {rank_num}" if rank_num else ""
    return diff, rank


def evaluate_position(board):
    info = engine.analyse(board, chess.engine.Limit(time=ENGINE_TIME_LIMIT))
    return info["score"].white().score(mate_score=10000) / 100


def draw_eval_bar(val):
    eval_canvas.delete("all")
    h, w = 480, 30
    C = 2.0
    # Transfer curve (atan) normalized to [-1,1]
    n = math.atan(val / C) / (math.pi / 2)
    # Compute position
    y = (1 - n) / 2 * h
    # Invert if board flipped
    if flip_board:
        y = h - y
    if not flip_board:
        eval_canvas.create_rectangle(0, 0, w, y, fill="black", outline="")
        eval_canvas.create_rectangle(0, y, w, h, fill="white", outline="")
    else:
        eval_canvas.create_rectangle(0, 0, w, y, fill="white", outline="")
        eval_canvas.create_rectangle(0, y, w, h, fill="black", outline="")
    eval_canvas.create_text(
        w / 2, h - 10, text=f"{val:.2f}", font=("Arial", 9), fill="#888888"
    )


def lighten_hex_color(hex_color, factor=0.2):
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = min(int(r + (255 - r) * factor), 255)
    g = min(int(g + (255 - g) * factor), 255)
    b = min(int(b + (255 - b) * factor), 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def get_base_square_color(row, col):
    return DARK_COLOR if (row + col) % 2 == 0 else LIGHT_COLOR


def draw_board():
    for r in range(8):
        for c in range(8):
            sq = chess.square(7 - c, r) if flip_board else chess.square(c, 7 - r)
            base = get_base_square_color(r, c)
            color = lighten_hex_color(base, 0.3) if sq in highlight_squares else base
            x0, y0 = c * 60, r * 60
            x1, y1 = x0 + 60, y0 + 60
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline=color)
            p = board.piece_at(sq)
            if p:
                color = "w" if p.color else "b"
                key = color + p.symbol().upper()  # e.g. 'wN', 'bK'
                img = piece_images.get(key)
                canvas.create_image(x0 + 30, y0 + 30, image=img)


def update_display():
    canvas.delete("all")
    draw_board()


def on_board_click(event):
    global selected_square
    c, r = event.x // 60, event.y // 60
    sq = chess.square(7 - c, r) if flip_board else chess.square(c, 7 - r)
    if selected_square is None:
        if board.piece_at(sq):
            selected_square = sq
            highlight_squares.clear()
            highlight_squares.append(sq)
    else:
        mv = chess.Move(selected_square, sq)
        highlight_squares.clear()
        highlight_squares.extend([selected_square, sq])
        if mv in board.legal_moves:
            process_move(mv)
        selected_square = None
    update_display()


def process_move(move):
    top_moves = get_top_moves(board)
    display_top_lines(board, top_moves)
    player_score = evaluate_move(board, move)
    diff, rank = determine_diff_rank(move, top_moves, player_score)
    san = board.san(move)
    rank_text = f"{rank}: " if rank else ""
    if board.turn:  # White to move
        if diff >= -1:
            tag = "Good"
        elif -3 <= diff < -1:
            tag = "Mistake"
        else:
            tag = "Blunder"
    else:  # Black to move
        if diff <= 1:
            tag = "Good"
        elif 1 < diff <= 3:
            tag = "Mistake"
        else:
            tag = "Blunder"
    msg = f"Your move: {rank_text}{san} (score={player_score:.2f}) (change={diff:.2f}) {tag}"
    log_message(msg, tag)
    board.push(move)
    update_display()
    announce_board_state()
    stockfish_move()


def stockfish_move():
    global highlight_squares
    if board.is_game_over():
        log_message("Game over.")
        return
    res = engine.play(board, chess.engine.Limit(time=ENGINE_TIME_LIMIT))
    mv = res.move
    mv_san = board.san(mv)
    highlight_squares.clear()
    highlight_squares.extend([mv.from_square, mv.to_square])
    board.push(mv)
    update_display()
    log_message(f"Engine plays: {mv_san}")
    ev = evaluate_position(board)
    log_message(f"Evaluation: {ev:.2f}")
    if SHOW_EVAL_BAR:
        draw_eval_bar(ev)
    announce_board_state()


def announce_board_state():
    if board.is_checkmate():
        log_message("Checkmate! Game Over.")
    elif board.is_stalemate():
        log_message("Stalemate! Game Over.")
    elif board.is_insufficient_material():
        log_message("Draw (insufficient material). Game Over.")
    elif board.is_check():
        log_message("Check!")


def next_position():
    global position_idx, board, flip_board, selected_square, highlight_squares
    position_idx = (position_idx + 1) % len(positions)
    fen = positions[position_idx]
    try:
        board = chess.Board(fen) if fen else chess.Board()
    except:
        log_message("Invalid FEN; using start position.")
        board = chess.Board()
    flip_board = not board.turn
    selected_square = None
    highlight_squares.clear()
    log_text_widget.delete("1.0", "end")
    update_display()
    log_message(f"FEN: {fen}")
    ev = evaluate_position(board)
    log_message(f"Evaluation: {ev:.2f}")
    if SHOW_EVAL_BAR:
        draw_eval_bar(ev)


def reload_position():
    global board, flip_board, selected_square, highlight_squares
    fen = positions[position_idx]
    try:
        board = chess.Board(fen) if fen else chess.Board()
    except:
        log_message("Invalid FEN; using start position.")
        board = chess.Board()
    flip_board = not board.turn
    selected_square = None
    highlight_squares.clear()
    log_text_widget.delete("1.0", "end")
    update_display()
    log_message(f"FEN: {fen}")
    ev = evaluate_position(board)
    log_message(f"Evaluation: {ev:.2f}")
    if SHOW_EVAL_BAR:
        draw_eval_bar(ev)


def init_main_window():
    global canvas, eval_canvas, status_label, log_text_widget
    root.title("mychess")
    btn_frame = tk.Frame(root)
    btn_frame.pack(side="top", fill="x")
    inner_btn_frame = tk.Frame(btn_frame)
    inner_btn_frame.pack()
    tk.Button(inner_btn_frame, text="Reload Position", command=reload_position).pack(
        side="left", padx=5, pady=5
    )
    tk.Button(inner_btn_frame, text="Next Position", command=next_position).pack(
        side="left", padx=5, pady=5
    )
    frame = tk.Frame(root)
    frame.pack(side="top")
    eval_canvas = tk.Canvas(frame, width=30, height=480)
    eval_canvas.pack(side="left")
    canvas = tk.Canvas(frame, width=480, height=480)
    canvas.pack(side="left")
    canvas.bind("<Button-1>", on_board_click)
    status_label = tk.Label(root, text="", font=("Arial", 12), pady=3, anchor="w")
    status_label.pack(side="bottom", fill="x")
    txt_frame = tk.Frame(root)
    txt_frame.pack(side="bottom", fill="both", expand=True)
    log_text_widget = ScrolledText(txt_frame, height=6, wrap="word")
    log_text_widget.pack(side="left", fill="both", expand=True)
    log_text_widget.tag_configure("Good", background="#669966")
    log_text_widget.tag_configure("Mistake", background="#b4722f")
    log_text_widget.tag_configure("Blunder", background="#df5757")
    return canvas, status_label, log_text_widget


def main():
    global engine, board, positions, canvas, status_label, log_text_widget, position_idx, flip_board, selected_square
    load_positions()
    load_piece_images(scale=0.725)
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    fen = positions[position_idx]
    try:
        board = chess.Board(fen) if fen else chess.Board()
    except:
        log_message("Invalid FEN; using start position.")
        board = chess.Board()
    flip_board = not board.turn
    selected_square = None
    canvas, status_label, log_text_widget = init_main_window()
    update_display()
    log_message(f"FEN: {fen}")
    ev = evaluate_position(board)
    log_message(f"Evaluation: {ev:.2f}")
    if SHOW_EVAL_BAR:
        draw_eval_bar(ev)
    root.update_idletasks()
    root.deiconify()
    root.attributes("-topmost", True)
    root.mainloop()
    engine.quit()


if __name__ == "__main__":
    main()
