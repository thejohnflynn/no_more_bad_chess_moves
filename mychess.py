import chess
import chess.engine
import os
import yaml
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

root = tk.Tk()
engine = None
board = None
positions = []
position_idx = 0
canvas = None
status_label = None
log_text_widget = None
highlight_squares = []
flip_board = False  # If True, display from Black's perspective

# Path to resources
STOCKFISH_PATH = "/opt/homebrew/bin/stockfish"
POSITIONS_FILE = "positions.txt"
ENGINE_TIME_LIMIT = 0.5  # Seconds
TOP_N = 3  # Number of top engine moves to display


def load_positions():
    global positions
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            positions = [line.strip() for line in f if line.strip()]
    else:
        positions = [""]  # empty = start position


def log_message(msg: str):
    print(msg)
    if log_text_widget:
        log_text_widget.insert("end", msg + "\n")
        log_text_widget.see("end")

DARK_COLOR = "#669966"
LIGHT_COLOR = "#99CC99"

def lighten_hex_color(hex_color, factor=0.2):
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = min(int(r + (255 - r) * factor), 255)
    g = min(int(g + (255 - g) * factor), 255)
    b = min(int(b + (255 - b) * factor), 255)
    return f"#{r:02x}{g:02x}{b:02x}"

def get_base_square_color(row, col):
    return DARK_COLOR if (row + col) % 2 == 0 else LIGHT_COLOR


def draw_board():
    symbol_map = {
        **{p: s for p, s in zip("prnbqk", "♟♜♞♝♛♚")},
        **{p.upper(): s for p, s in zip("prnbqk", "♟♜♞♝♛♚")},
    }
    for row in range(8):
        for col in range(8):
            if flip_board:
                sq = chess.square(7 - col, row)
            else:
                sq = chess.square(col, 7 - row)
            base = get_base_square_color(row, col)
            color = lighten_hex_color(base) if sq in highlight_squares else base
            x0, y0 = col * 60, row * 60
            x1, y1 = x0 + 60, y0 + 60
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline=color)
            piece = board.piece_at(sq)
            if piece:
                symbol = symbol_map[piece.symbol()]
                fill_col = "white" if piece.symbol().isupper() else "black"
                canvas.create_text(
                    x0 + 30,
                    y0 + 30,
                    text=symbol,
                    font=("Arial", 58),
                    fill=fill_col,
                )


def update_display():
    canvas.delete("all")
    draw_board()


def on_board_click(event):
    global selected_square
    col, row = event.x // 60, event.y // 60
    if flip_board:
        sq = chess.square(7 - col, row)
    else:
        sq = chess.square(col, 7 - row)
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
    # Multi-PV: gather top lines and display
    infos = engine.analyse(
        board, chess.engine.Limit(time=ENGINE_TIME_LIMIT), multipv=TOP_N
    )
    top_moves = []
    for info in infos:
        pv_list = info.get("pv", [])
        score = info["score"].white().score(mate_score=10000) / 100
        top_moves.append((pv_list, score))

    # Display each top line with continuation in parentheses
    for i, (pv_list, sc) in enumerate(top_moves):
        # Build SAN continuation
        san_line = []
        temp_board = board.copy()
        for m in pv_list:
            if m is None:
                break
            san_line.append(temp_board.san(m))
            temp_board.push(m)
        if san_line:
            first_san = san_line[0]
            continuation = " ".join(san_line)
        else:
            first_san = ""
            continuation = ""
        log_message(f"Top {i+1}: {first_san} (score={sc:.2f}) ({continuation})")

    best_score = top_moves[0][1]
    # Evaluate player's move
    tmp = board.copy()
    tmp.push(move)
    ps = (
        engine.analyse(tmp, chess.engine.Limit(time=ENGINE_TIME_LIMIT))["score"]
        .white()
        .score(mate_score=10000)
        / 100
    )

    # Determine diff & rank
    first_moves = [pv_list[0] for pv_list, _ in top_moves if pv_list]
    if move == first_moves[0]:
        diff = 0.0
        rank = "Top 1"
    else:
        diff = ps - best_score
        rank_num = next(
            (i + 1 for i, mv in enumerate(first_moves) if mv == move),
            None,
        )
        rank = f"Top {rank_num}" if rank_num else ""

    your_san = board.san(move)
    if rank:
        msg = f"Your move: {rank}: {your_san} (score={ps:.2f}, diff={diff:.2f})"
    else:
        msg = f"Your move: {your_san} (score={ps:.2f}, diff={diff:.2f})"
    log_message(msg)
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


def init_main_window():
    global canvas, status_label, log_text_widget
    root.title("mychess")
    btn_frame = tk.Frame(root)
    btn_frame.pack(side="top", fill="x")
    next_btn = tk.Button(btn_frame, text="Next Position", command=next_position)
    next_btn.pack(padx=5, pady=5)
    c = tk.Canvas(root, width=480, height=480)
    c.pack()
    c.bind("<Button-1>", on_board_click)
    st = tk.Label(root, text="", font=("Arial", 12), pady=3, anchor="w")
    st.pack(side="bottom", fill="x")
    frame = tk.Frame(root)
    frame.pack(side="bottom", fill="both", expand=True)
    txt = ScrolledText(frame, height=6, wrap="word")
    txt.pack(side="left", fill="both", expand=True)
    return c, st, txt


def main():
    global engine, board, positions, canvas, status_label, log_text_widget, position_idx, flip_board, selected_square
    load_positions()
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    posit = positions[position_idx]
    try:
        board = chess.Board(posit) if posit else chess.Board()
    except:
        log_message("Invalid FEN; using start position.")
        board = chess.Board()
    flip_board = not board.turn
    selected_square = None
    canvas, status_label, log_text_widget = init_main_window()
    update_display()
    root.update_idletasks()
    root.deiconify()
    root.attributes("-topmost", True)
    root.mainloop()
    engine.quit()

if __name__ == "__main__":
    main()
