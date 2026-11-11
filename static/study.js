(() => {
  const rangeInputs = document.querySelectorAll('input[type="range"]');
  rangeInputs.forEach((input) => {
    input.addEventListener("input", () => {
      input.setAttribute("aria-valuenow", input.value);
    });
  });

  const study = document.querySelector(".study-main");
  if (!study) return;

  const startedAt = performance.now();
  let lastMoveAt = startedAt;
  let selectedSquare = null;
  const feedback = document.querySelector("#move-feedback");
  const advanceButton = document.querySelector("#advance-button");
  const retryButton = document.querySelector("#retry-button");
  const showAnswerButton = document.querySelector("#show-answer-button");
  const answerOptions = document.querySelector("#answer-options");
  const answerDisplay = document.querySelector("#answer-display");
  const hintButton = document.querySelector("#hint-button");
  const squares = [...document.querySelectorAll(".square")];
  const elapsed = () => Math.min(Math.round(performance.now() - startedAt), 86400000);

  const clearMarks = () => {
    squares.forEach((square) => square.classList.remove("selected", "target"));
  };

  const showError = (message) => {
    if (feedback) feedback.textContent = message;
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

  const submitMove = async (from, to) => {
    try {
      const now = performance.now();
      const result = await postJson("/move", {
        move: `${from}${to}`,
        elapsed_ms: Math.round(now - startedAt),
        move_elapsed_ms: Math.round(now - lastMoveAt),
      });
      lastMoveAt = now;
      if (feedback) feedback.textContent = result.message;
      if (result.can_advance && advanceButton) advanceButton.disabled = false;
      if (result.can_advance) {
        squares.forEach((square) => {
          square.disabled = true;
        });
        if (hintButton) hintButton.disabled = true;
        if (retryButton) retryButton.hidden = true;
        if (answerOptions) answerOptions.hidden = true;
      }
      if (result.condition === "answer" && !result.correct && retryButton) {
        answerOptions.hidden = false;
      }
      clearMarks();
      selectedSquare = null;
    } catch (error) {
      showError(error.message);
    }
  };

  squares.forEach((square) => {
    square.addEventListener("click", () => {
      if (advanceButton?.disabled === false) return;
      const name = square.dataset.square;
      if (!selectedSquare) {
        selectedSquare = name;
        clearMarks();
        square.classList.add("selected");
        return;
      }
      if (selectedSquare === name) {
        clearMarks();
        selectedSquare = null;
        return;
      }
      const from = selectedSquare;
      square.classList.add("target");
      submitMove(from, name);
    });
  });

  if (hintButton) {
    hintButton.addEventListener("click", async () => {
      try {
        const result = await postJson("/hint", { elapsed_ms: elapsed() });
        showError(`Hint ${result.hint_number}: ${result.message}`);
      } catch (error) {
        showError(error.message);
      }
    });
  }

  if (retryButton) {
    retryButton.addEventListener("click", async () => {
      try {
        await postJson("/retry", { elapsed_ms: elapsed() });
        clearMarks();
        selectedSquare = null;
        retryButton.hidden = true;
        answerOptions.hidden = true;
        showError("Try the move again on the board.");
      } catch (error) {
        showError(error.message);
      }
    });
  }

  if (showAnswerButton) {
    showAnswerButton.addEventListener("click", async () => {
      try {
        const result = await postJson("/show-answer", { elapsed_ms: elapsed() });
        if (answerDisplay) answerDisplay.textContent = `Answer: ${result.answer}`;
        answerOptions.hidden = true;
        if (advanceButton) advanceButton.disabled = false;
        squares.forEach((square) => {
          square.disabled = true;
        });
        showError("Answer shown. Continue when you're ready.");
      } catch (error) {
        showError(error.message);
      }
    });
  }

  document.querySelectorAll("form[action$='/advance']").forEach((form) => {
    form.addEventListener("submit", () => {
      form.querySelector(".elapsed-input").value = elapsed();
    });
  });
})();
