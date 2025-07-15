import chess
import chess.pgn
import chess.engine
import io
import sys
import os


def get_eval_and_score(info):
    """
    Extract centipawn score and formatted evaluation from engine info.
    Returns (cp_score, eval_str).
    """
    score = info["score"].white()
    if score.is_mate():
        cp = 10000 if score.mate() > 0 else -10000
        eval_str = f"#{score.mate()}"
    else:
        cp = score.score()
        eval_str = f"{cp/100:.2f}"
    return cp, eval_str


def get_best_line_sans(info, board, length=8):
    """
    Return list of SAN strings for the principal variation from info.
    """
    sans = []
    if "pv" in info:
        temp = board.copy(stack=False)
        for mv in info["pv"][:length]:
            sans.append(temp.san(mv))
            temp.push(mv)
    return sans


def detect_miss_or_only(info, board, move, engine, depth, threshold=300):
    """
    Determine if a move is a 'Miss' or 'Only move':
    - 'Only Move': move is engine top recommendation and its advantage over second best exceeds threshold
    - 'Miss': same but the move wasn't made!
    Returns 'Only move', 'Miss', or None.
    """
    multi = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=2)
    if isinstance(multi, list) and len(multi) > 1:
        best_info, second_info = multi[0], multi[1]
        best_mv = best_info["pv"][0]
        best_cp, _ = get_eval_and_score(best_info)
        second_cp, _ = get_eval_and_score(second_info)
        diff = best_cp - second_cp
        if diff > threshold:
            if move == best_mv:
                return "Only move. "
            else:
                return "Miss. "
    return None


def classify_move(prev_cp, curr_cp, move, best_sans, board, engine, info_before, depth):
    """
    Classify a move as Best/Only move/Miss/Mistake/Inaccuracy/Blunder.
    Returns a list of NAGs and a label.
    """
    nags = []
    comment = ""
    # Only move or Miss detection
    special = detect_miss_or_only(info_before, board, move, engine, depth)
    if special:
        comment += special
    # Best move detection
    if best_sans and move == board.parse_san(best_sans[0]):
        comment += "Best move. "
    # Centipawn-based classification
    diff = abs(prev_cp - curr_cp)
    if diff > 300:
        nags = [chess.pgn.NAG_BLUNDER]
        comment += "Blunder. "
    elif diff > 100:
        nags = [chess.pgn.NAG_MISTAKE]
        comment += "Mistake. "
    elif diff > 66:
        nags = [chess.pgn.NAG_DUBIOUS_MOVE]
        comment += "Inaccuracy. "
    return nags, comment


def format_variation_text(sans, board):
    """
    Format SANs with move numbers like Lichess style, combining white's first two plies.
    """
    var = board.copy(stack=False)
    parts = []
    mvnum = var.fullmove_number
    idx = 0
    # Handle first move differently if white starts
    if var.turn == chess.WHITE:
        if len(sans) >= 2:
            parts.append(f"{mvnum}. {sans[0]} {sans[1]}")
            idx = 2
        else:
            parts.append(f"{mvnum}. {sans[0]}")
            idx = 1
    else:
        # Black starts
        parts.append(f"{mvnum}... {sans[0]}")
        idx = 1
    # Subsequent pairs
    while idx < len(sans):
        mvnum += 1
        if idx + 1 < len(sans):
            parts.append(f"{mvnum}. {sans[idx]} {sans[idx+1]}")
            idx += 2
        else:
            parts.append(f"{mvnum}. {sans[idx]}")
            idx += 1
    return " ".join(parts)


def build_comment(existing, prev_eval, curr_eval, label, best_sans, temp_board):
    """
    Build the comment string based on classification label and best move sans.
    """
    comment = f"{existing} [%eval {curr_eval}]"
    if label and best_sans:
        if "Best move" in label:
            comment = f"{existing} {label}[%eval {curr_eval}]"
        else:
            variation_text = format_variation_text(best_sans, temp_board)
            comment = (f"{existing} ({prev_eval} -> {curr_eval}) {label}{best_sans[0]} was best."
                       f" [%eval {curr_eval}] ({variation_text})")
    return comment.strip()


def analyse_pgn(pgn_text, stockfish_path="stockfish", depth=10):
    pgn = chess.pgn.read_game(io.StringIO(pgn_text))
    board = pgn.board()
    engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
    node = pgn

    # Initial analysis before any move
    info_before = engine.analyse(board, chess.engine.Limit(depth=depth))

    while node.variations:
        next_node = node.variations[0]
        temp_board = board.copy(stack=False)
        move = next_node.move

        # Get previous centipawn & eval
        prev_cp, prev_eval = get_eval_and_score(info_before)

        # Best line SANs
        best_sans = get_best_line_sans(info_before, temp_board)

        # Apply the move
        board.push(move)
        info_after = engine.analyse(board, chess.engine.Limit(depth=depth))
        curr_cp, curr_eval = get_eval_and_score(info_after)

        # Classify move
        nags, label = classify_move(prev_cp, curr_cp, move, best_sans, temp_board, engine, info_before, depth)
        for nag in nags:
            next_node.nags.add(nag)

        # Build and set comment
        existing = next_node.comment or ""
        comment = build_comment(existing, prev_eval, curr_eval, label, best_sans, temp_board)
        next_node.comment = comment

        node = next_node
        info_before = info_after

    engine.quit()
    output = io.StringIO()
    exporter = chess.pgn.FileExporter(output)
    pgn.accept(exporter)
    raw = output.getvalue()
    return raw.replace(" $2", "?").replace(" $4", "??").replace(" $6", "?!")


def main():
    if len(sys.argv) != 2:
        print("Usage: python whychess.py input.pgn")
        sys.exit(1)

    input_pgn_path = sys.argv[1]
    base, _ = os.path.splitext(input_pgn_path)

    with open(input_pgn_path, "r", encoding="utf-8") as f:
        pgn_text = f.read()

    analysed = analyse_pgn(pgn_text)
    with open(f"{base}_analysed.pgn", "w", encoding="utf-8") as f:
        f.write(analysed)

    print(f"Written {base}_analysed.pgn")

if __name__ == "__main__":
    main()
