import sys
import os
import io
import re

import chess
import chess.pgn
import chess.engine
import pandas as pd
import numpy as np

ENGINE_DEPTH = 12

INACCURACY_DROP = -0.08
MISTAKE_DROP = -0.15
BLUNDER_DROP = -0.22

NUM_GAMES_TO_ANALYSE = 100
COLUMNS = ["position", "time_to_complete"]


def win_probability(cp: float) -> float:
    return 1 / (1 + np.exp(-cp / 116.0))


def get_eval_and_score(info):
    score = info["score"].white()
    if score.is_mate():
        cp = 10000 if score.mate() > 0 else -10000
        eval_str = f"#{score.mate()}"
    else:
        cp = score.score()
        eval_str = f"{cp/100:.2f}"
    return cp, eval_str


def classify_move(prev_cp, curr_cp, pov):
    nags = []

    if pov == "black":
        prev_cp = -prev_cp
        curr_cp = -curr_cp

    prev_wp = win_probability(prev_cp)
    curr_wp = win_probability(curr_cp)
    drop = curr_wp - prev_wp

    if drop <= BLUNDER_DROP:
        nags = [chess.pgn.NAG_BLUNDER]
    elif drop <= MISTAKE_DROP:
        nags = [chess.pgn.NAG_MISTAKE]
    elif drop <= INACCURACY_DROP:
        nags = [chess.pgn.NAG_DUBIOUS_MOVE]

    return nags


def build_comment(curr_eval, nags):
    label = ""
    if nags:
        if nags == [chess.pgn.NAG_BLUNDER]:
            label = "Blunder. "
        elif nags == [chess.pgn.NAG_MISTAKE]:
            label = "Mistake. "
        elif nags == [chess.pgn.NAG_DUBIOUS_MOVE]:
            label = "Inaccuracy. "
    comment = f"{label}[%eval {curr_eval}]"
    return comment.strip()


def analyse_pgn(pgn_text, stockfish_path="stockfish", depth=20, df_positions=None):
    pgn = chess.pgn.read_game(io.StringIO(pgn_text))
    white_player = pgn.headers.get("White", "")
    black_player = pgn.headers.get("Black", "")
    board = pgn.board()

    if df_positions is None:
        df_positions = pd.DataFrame(columns=COLUMNS)

    engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
    info_before = engine.analyse(board, chess.engine.Limit(depth=depth))

    node = pgn
    while node.variations:
        prev_cp, _ = get_eval_and_score(info_before)
        pov = "white" if board.turn == chess.WHITE else "black"

        next_node = node.variations[0]
        move = next_node.move
        board.push(move)
        info_after = engine.analyse(board, chess.engine.Limit(depth=depth))
        curr_cp, curr_eval = get_eval_and_score(info_after)
        nags = classify_move(prev_cp, curr_cp, pov)
        for nag in nags:
            next_node.nags.add(nag)
        next_node.comment = build_comment(curr_eval, nags)

        if chess.pgn.NAG_BLUNDER in nags:
            mover = white_player if board.turn == chess.WHITE else black_player
            if mover in ("saintidle", "John"):
                df_positions.loc[len(df_positions)] = [board.fen(), 300.0]

        node = next_node
        info_before = info_after

    engine.quit()

    output = io.StringIO()
    exporter = chess.pgn.FileExporter(output)
    pgn.accept(exporter)
    annotated_pgn = (
        output.getvalue().replace(" $2", "?").replace(" $4", "??").replace(" $6", "?!")
    )

    return annotated_pgn, df_positions


def main():
    if len(sys.argv) != 2:
        print("Usage: python analyse_games.py input.pgn")
        sys.exit(1)

    input_pgn_path = sys.argv[1]
    base, _ = os.path.splitext(input_pgn_path)
    output_pgn_path = f"{base}_analysed.pgn"

    df_positions = pd.DataFrame(columns=COLUMNS)

    count = 1
    annotated_games = []
    with open(input_pgn_path, "r", encoding="utf-8") as fin:
        while count <= NUM_GAMES_TO_ANALYSE:
            print(f"Analysing game {count}...")
            game = chess.pgn.read_game(fin)
            if game is None:
                break

            raw_pgn = str(game)
            annotated, df_positions = analyse_pgn(
                raw_pgn,
                stockfish_path="stockfish",
                depth=ENGINE_DEPTH,
                df_positions=df_positions,
            )
            annotated_games.append(annotated)
            count += 1

    with open(output_pgn_path, "w", encoding="utf-8") as fout:
        fout.write("\n\n".join(annotated_games))
    print(f"Written {output_pgn_path}")

    df_positions.to_csv("positions_auto.csv", index=False)
    print("Written positions_auto.csv")


if __name__ == "__main__":
    main()
