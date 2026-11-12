import { Chessground } from "https://cdn.jsdelivr.net/npm/chessground@9.2.1/+esm";
import { Chess } from "https://cdn.jsdelivr.net/npm/chess.js@1.4.0/+esm";

const study = document.querySelector(".study-main");
const boardEl = document.querySelector("#board");

if (study && boardEl) {
  const startFen = boardEl.dataset.fen;
  const startedAt = performance.now();
  let lastMoveAt = startedAt;
  let locked = false;

  const feedback = document.querySelector("#move-feedback");
  const advanceButton = document.querySelector("#advance-button");
  const retryButton = document.querySelector("#retry-button");
  const showAnswerButton = document.querySelector("#show-answer-button");
  const answerOptions = document.querySelector("#answer-options");
  const answerDisplay = document.querySelector("#answer-display");
  const hintButton = document.querySelector("#hint-button");
  const elapsed = () => Math.min(Math.round(performance.now() - startedAt), 86400000);

  const showMessage = (message) => {
    if (feedback) feedback.textContent = message;
  };

  // Legal destinations for every piece of the side to move, in chessground's format.
  const legalDests = (chess) => {
    const dests = new Map();
    for (const move of chess.moves({ verbose: true })) {
      if (!dests.has(move.from)) dests.set(move.from, []);
      dests.get(move.from).push(move.to);
    }
    return dests;
  };

  const colorOf = (chess) => (chess.turn() === "w" ? "white" : "black");

  let chess = new Chess(startFen);
  const ground = Chessground(boardEl, {
    fen: startFen,
    orientation: colorOf(chess),
    turnColor: colorOf(chess),
    check: chess.inCheck(),
    coordinates: true,
    animation: { enabled: true, duration: 200 },
    highlight: { lastMove: true, check: true },
    movable: {
      free: false,
      color: colorOf(chess),
      dests: legalDests(chess),
      showDests: true,
      events: { after: (from, to) => onUserMove(from, to) },
    },
    premovable: { enabled: false },
    draggable: { showGhost: true },
  });

  // Put the board back to the puzzle's starting position, ready for another try.
  const resetBoard = () => {
    chess = new Chess(startFen);
    ground.set({
      fen: startFen,
      turnColor: colorOf(chess),
      check: chess.inCheck(),
      lastMove: undefined,
      movable: { color: locked ? undefined : colorOf(chess), dests: legalDests(chess) },
    });
  };

  const lockBoard = () => {
    locked = true;
    ground.set({ movable: { color: undefined, dests: new Map() } });
  };

  const waitForRetry = () => {
    ground.set({ movable: { color: undefined, dests: new Map() } });
  };

  const postJson = async (url, body) => {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "The action could not be saved.");
    return result;
  };

  async function onUserMove(from, to) {
    if (locked) return;
    // Auto-promote to a queen, like Lichess puzzles do by default.
    const move = chess.move({ from, to, promotion: "q" });
    const uci = `${from}${to}${move?.promotion ?? ""}`;
    ground.set({ fen: chess.fen(), turnColor: colorOf(chess), check: chess.inCheck() });
    ground.set({ movable: { color: undefined, dests: new Map() } });

    try {
      const now = performance.now();
      const result = await postJson("/move", {
        move: uci,
        elapsed_ms: Math.round(now - startedAt),
        move_elapsed_ms: Math.round(now - lastMoveAt),
      });
      lastMoveAt = now;
      showMessage(result.message);

      if (result.can_advance) {
        lockBoard();
        if (advanceButton) advanceButton.disabled = false;
        if (hintButton) hintButton.disabled = true;
        if (answerOptions) answerOptions.hidden = true;
        return;
      }
      if (result.condition === "answer" && !result.correct) {
        // Leave the wrong move visible until the player picks Retry or Show answer.
        if (answerOptions) answerOptions.hidden = false;
        if (retryButton) retryButton.hidden = false;
        waitForRetry();
        return;
      }
      // Question-based practice: show the wrong move briefly, then let them try again.
      setTimeout(resetBoard, 700);
    } catch (error) {
      showMessage(error.message);
      resetBoard();
    }
  }

  if (hintButton) {
    hintButton.addEventListener("click", async () => {
      try {
        const result = await postJson("/hint", { elapsed_ms: elapsed() });
        showMessage(`Hint ${result.hint_number}: ${result.message}`);
      } catch (error) {
        showMessage(error.message);
      }
    });
  }

  if (retryButton) {
    retryButton.addEventListener("click", async () => {
      try {
        await postJson("/retry", { elapsed_ms: elapsed() });
        if (answerOptions) answerOptions.hidden = true;
        resetBoard();
        showMessage("Try the move again on the board.");
      } catch (error) {
        showMessage(error.message);
      }
    });
  }

  if (showAnswerButton) {
    showAnswerButton.addEventListener("click", async () => {
      try {
        const result = await postJson("/show-answer", { elapsed_ms: elapsed() });
        if (answerDisplay) answerDisplay.textContent = `Answer: ${result.answer}`;
        if (answerOptions) answerOptions.hidden = true;
        lockBoard();
        resetBoard();
        if (result.solution && result.solution.length >= 4) {
          const from = result.solution.slice(0, 2);
          const to = result.solution.slice(2, 4);
          ground.setAutoShapes([{ orig: from, dest: to, brush: "green" }]);
        }
        if (advanceButton) advanceButton.disabled = false;
        showMessage("Answer shown. Continue when you're ready.");
      } catch (error) {
        showMessage(error.message);
      }
    });
  }

  document.querySelectorAll("form[action$='/advance']").forEach((form) => {
    form.addEventListener("submit", () => {
      form.querySelector(".elapsed-input").value = elapsed();
    });
  });
}
